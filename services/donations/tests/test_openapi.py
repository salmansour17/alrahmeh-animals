"""openapi.yaml must describe exactly the routes Flask serves: no route
missing from the document, and no documented path or method that Flask does
not have. The document is written by hand, so this is what keeps it honest."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app import create_app

OPENAPI = Path(__file__).resolve().parent.parent / "openapi.yaml"
HTTP_METHODS = {"get", "put", "post", "delete", "patch"}
# Flask's <int:animal_id> becomes OpenAPI's {animal_id}.
FLASK_PARAMETER = re.compile(r"<(?:[a-z_]+:)?([a-z_]+)>")


def _document() -> dict:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))


def _flask_operations(config, database) -> set[tuple[str, str]]:
    app = create_app(config, database=database)
    operations = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = FLASK_PARAMETER.sub(r"{\1}", rule.rule)
        # HEAD and OPTIONS are added by Flask to every route automatically.
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            operations.add((method.lower(), path))
    return operations


def _documented_operations() -> set[tuple[str, str]]:
    return {(method, path) for path, item in _document()["paths"].items() for method in item if method in HTTP_METHODS}


def test_every_flask_route_is_documented(config, database):
    missing = _flask_operations(config, database) - _documented_operations()
    assert missing == set(), f"routes missing from openapi.yaml: {sorted(missing)}"


def test_every_documented_operation_has_a_flask_route(config, database):
    extra = _documented_operations() - _flask_operations(config, database)
    assert extra == set(), f"openapi.yaml documents routes Flask does not have: {sorted(extra)}"


def _resolve(document: dict, node: dict) -> dict:
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        section = node["$ref"].split("/")[2]
        node = document["components"][section][name]
    return node


def test_path_parameters_match_the_placeholders_in_each_path():
    document = _document()
    for path, item in document["paths"].items():
        placeholders = set(re.findall(r"{([a-z_]+)}", path))
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            declared = {
                parameter["name"]
                for parameter in (_resolve(document, p) for p in operation.get("parameters", []))
                if parameter["in"] == "path"
            }
            assert declared == placeholders, f"{method.upper()} {path}: path parameters {declared}"


def test_every_operation_documents_its_responses():
    for path, item in _document()["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                assert operation.get("responses"), f"{method.upper()} {path} has no responses"
