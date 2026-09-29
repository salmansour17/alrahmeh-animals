"""The seam between the two feature domains, enforced.

Neither domain package may import the other. They refer to each other only by
primary-key value (donations.earmarked_animal_id holds an animals.id). This
test reads the source of every module rather than importing it, so it catches
an import anywhere in the file, including inside a function.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAINS = Path(__file__).resolve().parent.parent / "domains"


def _imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(("domain", "forbidden"), [("animals", "donations"), ("donations", "animals")])
def test_domain_does_not_import_its_sibling(domain, forbidden):
    offenders = {
        str(source.relative_to(DOMAINS)): sorted(
            module
            for module in _imported_modules(source)
            if module == f"domains.{forbidden}" or module.startswith(f"domains.{forbidden}.")
        )
        for source in (DOMAINS / domain).rglob("*.py")
    }
    offenders = {path: modules for path, modules in offenders.items() if modules}
    assert offenders == {}, f"domains/{domain} imports domains/{forbidden}: {offenders}"
