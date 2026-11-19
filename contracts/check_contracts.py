"""Checks that the system's machine-readable descriptions match each other and
the code. Run by .github/workflows/contracts.yml, from the repository root:

    python contracts/check_contracts.py

1. system.yaml is valid against system.schema.json.
2. Each service's openapi.yaml is a valid OpenAPI 3 document.
3. Every path system.yaml names (folders, OpenAPI files, migrations) exists,
   and each service documents its health endpoint.
4. Every call between services is documented on both sides: the endpoint is
   in the called service's openapi.yaml, and the donations service's client
   uses exactly that method, path and set of answers, with the timeout
   system.yaml states.
5. The environment variables each service reads are exactly the ones
   system.yaml lists for it.

It prints every problem it finds, then exits 1 if there were any. Needs
jsonschema, openapi-spec-validator and pyyaml, which CI installs for this job
only; they are not dependencies of any service.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_openapi

ROOT = Path(__file__).resolve().parent.parent
HTTP_METHODS = {"get", "put", "post", "delete", "patch"}

problems: list[str] = []


def problem(message: str) -> None:
    problems.append(message)
    print(f"FAIL  {message}")


def ok(message: str) -> None:
    print(f"ok    {message}")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_schema(system: dict) -> None:
    schema = json.loads((ROOT / "system.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(system), key=lambda e: list(e.path))
    for error in errors:
        where = "/".join(str(p) for p in error.path) or "(top level)"
        problem(f"system.yaml {where}: {error.message}")
    if not errors:
        ok("system.yaml is valid against system.schema.json")


def check_openapi(name: str, document: dict) -> None:
    try:
        validate_openapi(document)
    except Exception as error:  # noqa: BLE001 (report whatever the validator found)
        problem(f"{name} openapi.yaml is not a valid OpenAPI 3 document: {error}")
    else:
        ok(f"{name} openapi.yaml is a valid OpenAPI 3 document")


def check_paths(name: str, service: dict, document: dict) -> None:
    for key in ("path", "openapi", "migrations"):
        if not (ROOT / service[key]).exists():
            problem(f"{name}: {key} {service[key]} does not exist")
    health = service["health"]
    if "get" not in document.get("paths", {}).get(health, {}):
        problem(f"{name}: health endpoint GET {health} is not in its openapi.yaml")
    else:
        ok(f"{name}: paths exist and GET {health} is documented")


def operation(document: dict, method: str, path: str) -> dict | None:
    return document.get("paths", {}).get(path, {}).get(method.lower())


def client_constants(path: Path) -> dict:
    """Module-level constants of the donations client, read without importing
    it, so this check needs none of the service's dependencies."""
    values = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return values


def check_calls(system: dict, documents: dict[str, dict]) -> None:
    services = system["services"]
    for caller, service in services.items():
        for call in service.get("calls", []):
            target = call["service"]
            if target not in services:
                problem(f"{caller} calls unknown service {target}")
                continue
            if call["url_env"] not in service["env"]:
                problem(f"{caller}: url_env {call['url_env']} is not among its env variables")
            for endpoint in call["endpoints"]:
                method, path = endpoint.split(" ", 1)
                if operation(documents[target], method, path) is None:
                    problem(f"{caller} calls {endpoint}, which is not in {target}'s openapi.yaml")
                else:
                    ok(f"{caller} -> {target}: {endpoint} is documented by {target}")

    # The one call in this system, checked against the code that makes it.
    client = client_constants(ROOT / "services/donations/donations/animals_client.py")
    endpoint = f"{client['ANIMAL_METHOD']} {client['ANIMAL_PATH']}"
    calls = [c for c in services["donations"].get("calls", []) if c["service"] == "animals"]
    if not calls or endpoint not in calls[0]["endpoints"]:
        problem(f"donations' client calls {endpoint}, which system.yaml does not list")
        return
    answers = set(client["ANSWERS"])
    documented = operation(documents["animals"], client["ANIMAL_METHOD"], client["ANIMAL_PATH"])
    codes = {int(code) for code in documented["responses"]}
    if codes != answers:
        problem(f"animals documents {endpoint} answering {sorted(codes)}, but donations handles {sorted(answers)}")
    else:
        ok(f"{endpoint}: animals answers {sorted(codes)}, exactly what donations' client handles")
    parameters = {p["name"] for p in documented.get("parameters", []) if "$ref" not in p}
    parameters |= {
        documents["animals"]["components"]["parameters"][p["$ref"].rsplit("/", 1)[-1]]["name"]
        for p in documented.get("parameters", [])
        if "$ref" in p
    }
    placeholders = set(re.findall(r"{([a-z_]+)}", client["ANIMAL_PATH"]))
    if parameters != placeholders:
        problem(f"{endpoint}: animals documents parameters {parameters}, the client fills {placeholders}")
    timeout = services["donations"]["env"]["ANIMALS_TIMEOUT_S"]["default"]
    if calls[0]["timeout_s"] != timeout:
        problem(f"donations: calls timeout_s {calls[0]['timeout_s']} differs from ANIMALS_TIMEOUT_S default {timeout}")


ENV_READS = [
    re.compile(r'os\.environ\.get\("([A-Z_][A-Z0-9_]*)"'),
    re.compile(r'_read_(?:optional|timeout)\("([A-Z_][A-Z0-9_]*)"'),
]
SHELL_READS = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)")


def env_read_by(service_path: Path) -> set[str]:
    names: set[str] = set()
    for source in service_path.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        for pattern in ENV_READS:
            names |= set(pattern.findall(text))
    entrypoint = service_path / "entrypoint.sh"
    if entrypoint.exists():
        names |= set(SHELL_READS.findall(entrypoint.read_text(encoding="utf-8")))
    # GIT_SHA reaches the code through config.py like the others; PORT through
    # config.py too (the entrypoint asks config.py for it).
    return names


def check_env(system: dict) -> None:
    for name, service in system["services"].items():
        read = env_read_by(ROOT / service["path"])
        listed = set(service["env"])
        if read - listed:
            problem(f"{name} reads {sorted(read - listed)}, missing from system.yaml")
        if listed - read:
            problem(f"{name}: system.yaml lists {sorted(listed - read)}, which the code never reads")
        if read == listed:
            ok(f"{name}: system.yaml lists exactly the {len(read)} environment variables the code reads")


def main() -> int:
    system = load_yaml(ROOT / "system.yaml")
    check_schema(system)
    documents = {}
    for name, service in system.get("services", {}).items():
        document = load_yaml(ROOT / service["openapi"])
        documents[name] = document
        check_openapi(name, document)
        check_paths(name, service, document)
    check_calls(system, documents)
    check_env(system)
    print()
    print(f"{len(problems)} problem(s)" if problems else "All contract checks passed.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
