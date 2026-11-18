"""Cross-origin requests from the website, allowed in code (CORS).

The website is served from its own address (an Azure Storage static website,
or nginx in Docker Compose) and calls this service at another, so the browser
treats every call as cross-origin. It sends the call only if this service
answers with the website's origin in Access-Control-Allow-Origin.

This is done here rather than with Azure Container Apps' own CORS setting: the
setup guide warns that the ingress setting rejects the browser's preflight for
JSON requests, so reads work and every POST fails with "Failed to fetch".

Rules:
- Only the origins listed in CORS_ORIGINS are allowed. There is no wildcard:
  "*" in the list is ignored with a warning.
- The allowed origin is echoed back exactly, with `Vary: Origin`, so a cache
  in between never serves one origin's answer to another.
- No cookies are used anywhere (the staff token travels in the Authorization
  header), so Access-Control-Allow-Credentials is never sent.
- CORS is enforced by browsers, not servers. A request from an origin that is
  not allowed is still answered; it simply carries no CORS headers, so the
  browser refuses to hand the answer to the page. Access control for staff
  endpoints is security.py's job, not this module's.

Each service has its own copy of this file (ADR-6).
"""

from __future__ import annotations

from flask import Flask, Response, request

ALLOWED_METHODS = "GET, POST, PUT, OPTIONS"
# Content-Type because the website sends JSON (and photos), which makes the
# browser ask first; Authorization for the staff portal.
ALLOWED_HEADERS = "Content-Type, Authorization"
# How long a browser may reuse a preflight answer before asking again.
PREFLIGHT_MAX_AGE_S = "600"


def enable_cors(app: Flask, allowed_origins: frozenset[str]) -> None:
    """Answer preflight requests and add CORS headers for allowed origins."""

    @app.before_request
    def answer_preflight():
        # A preflight is an OPTIONS request carrying the method the page wants
        # to use. Answer it here, before routing, for every path.
        if request.method != "OPTIONS" or "Access-Control-Request-Method" not in request.headers:
            return None
        origin = request.headers.get("Origin")
        if origin not in allowed_origins:
            return Response(status=403)
        response = Response(status=204)
        response.headers["Access-Control-Allow-Methods"] = ALLOWED_METHODS
        response.headers["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
        response.headers["Access-Control-Max-Age"] = PREFLIGHT_MAX_AGE_S
        return response

    @app.after_request
    def add_cors_headers(response: Response) -> Response:
        response.vary.add("Origin")
        origin = request.headers.get("Origin")
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
        return response
