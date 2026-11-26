"""A stand-in for the animals service, served over real HTTP on a random local
port.

The donations tests use it to exercise the HTTP adapters through an actual
network connection (timeouts, status codes, a stopped service) without running
the animals service itself. It answers the two endpoints donations calls,
GET /api/animals/<id> and GET /api/animals/names?ids=..., in the same shape as
the real ones (services/animals/openapi.yaml; contracts/check_contracts.py
keeps the client and that file in step).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class AnimalsStub:
    """Start with `with AnimalsStub({7}) as stub:` and point the code under
    test at `stub.url`. Change `mode` to make it misbehave:
    "ok" answers normally, "error" answers 500, "teapot" answers an unexpected
    418, "slow" waits `delay_s` first, "malformed" answers 200 with a body that
    is not the documented shape.
    """

    def __init__(self, known_ids: set[int]) -> None:
        self.known_ids = set(known_ids)
        self.mode = "ok"
        self.delay_s = 1.0
        self.requests: list[str] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (name fixed by http.server)
                stub.requests.append(self.path)
                if stub.mode == "slow":
                    time.sleep(stub.delay_s)
                if stub.mode == "teapot":
                    return self._send(418, {"error": "unexpected"})
                if stub.mode == "error":
                    return self._send(500, {"error": "internal_server_error"})
                if stub.mode == "malformed":
                    return self._send(200, {"unexpected": True})
                url = urlsplit(self.path)
                if url.path == "/api/animals/names":
                    raw = parse_qs(url.query).get("ids", [""])[0]
                    if not raw or not all(part.isdigit() for part in raw.split(",")):
                        return self._send(400, {"error": "validation_failed"})
                    wanted = sorted({int(part) for part in raw.split(",")} & stub.known_ids)
                    return self._send(200, {"animals": [{"id": i, "name": f"Animal {i}"} for i in wanted]})
                parts = self.path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["api", "animals"] and parts[2].isdigit():
                    animal_id = int(parts[2])
                    if animal_id in stub.known_ids:
                        return self._send(200, {"id": animal_id, "name": f"Animal {animal_id}"})
                return self._send(404, {"error": "not_found"})

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up first, as a timeout test intends

            def log_message(self, *args) -> None:
                pass  # keep test output quiet

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> AnimalsStub:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
