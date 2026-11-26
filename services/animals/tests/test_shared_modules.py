"""The modules every service keeps its own copy of, instead of a shared
package (ADR-6: a shared package would tie the services back together). The
price of copies is that they can drift apart; this test makes that a failing
build instead of a surprise. Identical in every service.

To change one of these files: change it in one service, copy it to the
other two, and commit all three together.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

SERVICES = ("animals", "donations", "enquiries")
SHARED = (
    "db.py",
    "migrate.py",
    "cors.py",
    "security.py",
    "hardening.py",
    "security_events.py",
    "tests/test_hardening_unit.py",
    "tests/test_shared_modules.py",
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", SHARED)
def test_every_service_has_the_same_copy(name):
    digests = {service: hashlib.sha256((ROOT / service / name).read_bytes()).hexdigest() for service in SERVICES}
    assert len(set(digests.values())) == 1, f"{name} differs between services: {digests}"


def test_every_module_at_the_service_root_is_copied_into_the_image():
    # The Dockerfile copies files by name (never COPY . .), so a new module
    # must be added to its COPY line by hand. When hardening.py and
    # security_events.py were not, every test still passed, because tests run
    # from the source folder, but the container could not start.
    service = Path(__file__).resolve().parents[1]
    copy_lines = [
        line.split()[1:-1]
        for line in (service / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY ")
    ]
    copied = {name for line in copy_lines for name in line}
    modules = {path.name for path in service.glob("*.py")}
    assert modules - copied == set(), f"not copied into the image: {sorted(modules - copied)}"
