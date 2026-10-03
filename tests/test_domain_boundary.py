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


DOMAIN_NAMES = ("animals", "donations", "enquiries")


@pytest.mark.parametrize(
    ("domain", "forbidden"),
    [(a, b) for a in DOMAIN_NAMES for b in DOMAIN_NAMES if a != b],
)
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


PROJECT = DOMAINS.parent
PAYMENT_ADAPTER = DOMAINS / "donations" / "payments.py"


def test_only_the_payment_adapter_imports_stripe():
    """The Stripe SDK is a detail behind PaymentGateway. If any other piece of
    application code imports it, Stripe has leaked past the adapter. Tests are
    exempt: they drive the adapter and fake Stripe's responses."""
    application_code = [
        path
        for path in PROJECT.rglob("*.py")
        if not {"tests", ".venv", "venv", "node_modules"} & set(path.relative_to(PROJECT).parts)
    ]
    importers = sorted(
        str(path.relative_to(PROJECT))
        for path in application_code
        if any(m == "stripe" or m.startswith("stripe.") for m in _imported_modules(path))
    )
    assert importers == [str(PAYMENT_ADAPTER.relative_to(PROJECT))]
