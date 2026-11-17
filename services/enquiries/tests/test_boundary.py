"""The seams between the services, enforced from this side (ADR-2, ADR-6).

The enquiries service must never import another service's domain package. In the
monolith that was what kept the domains separable; now that each service runs
from its own folder, it is also what keeps this service deployable on its own.
The other services carry the same test. It reads the source of every module
rather than importing it, so it catches an import anywhere in a file,
including inside a function.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SERVICE = Path(__file__).resolve().parent.parent
OTHER_SERVICES = {'animals', 'donations', 'sample_animals'}
SKIP = {"tests", ".venv", "venv", "node_modules", "__pycache__", "data"}


def _imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _source_files() -> list[Path]:
    return [path for path in SERVICE.rglob("*.py") if not SKIP & set(path.relative_to(SERVICE).parts)]


@pytest.mark.parametrize("other", sorted(OTHER_SERVICES))
def test_this_service_never_imports_another(other):
    offenders = {
        str(path.relative_to(SERVICE)): sorted(
            module for module in _imported_modules(path) if module == other or module.startswith(other + ".")
        )
        for path in _source_files()
    }
    offenders = {path: modules for path, modules in offenders.items() if modules}
    assert offenders == {}, f"the enquiries service imports {other}: {offenders}"
