"""Our own software composition analysis (SCA): are our dependencies pinned,
and does any version we use have a known HIGH or CRITICAL vulnerability?

    # In a clean virtual environment holding exactly one service's packages:
    python security/sca.py python --requirements services/animals/requirements.txt
    # The website:
    python security/sca.py npm --project ui

Exit codes: 0 clean; 1 a HIGH/CRITICAL (or unknown-severity) vulnerability,
an unpinned requirement or a missing lock file; 2 the scanner could not do
its job (bad arguments, unreadable file, OSV unreachable).

What is checked
  python  Every line of each requirements file must pin one exact version with
          `==`. Then EVERY package installed in the environment this runs in,
          transitive dependencies included (read with importlib.metadata), is
          looked up in OSV. Run it in a fresh virtual environment that holds
          only the service's requirements, so "installed" means "shipped".
  npm     <project>/package-lock.json must exist (lockfile v2 or v3), and
          every package in it is looked up in OSV, dev dependencies included:
          they run on the build machine, and a compromised build tool can put
          anything into the files we publish.

Decisions, each made to fail closed
  Severity comes from, in order: the advisory's own rating
  (database_specific.severity), the rating on the affected package entry, the
  CVSS v3 vector (base score computed here), and finally the same facts on
  the advisory's aliases (a PYSEC entry often has no rating while its GHSA
  twin does). If none of these gives a rating, the vulnerability is reported
  as UNKNOWN and FAILS the run: an advisory nobody has rated yet is not
  evidence that it is harmless. A CVSS v4-only vector is not computed here
  (its formula is a lookup table of 270 entries); it is UNKNOWN unless an
  alias has a rating.

  If OSV cannot be reached after a few retries, the run stops with exit 2
  and says so. It never reports "no vulnerabilities" for a query it could not
  make.

The network sits behind one injected function, fetch_json, so the tests
never touch it. Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

OSV_API = "https://api.osv.dev/v1"
# OSV accepts at most 1000 queries in one querybatch request.
BATCH_LIMIT = 1000
REQUEST_TIMEOUT_S = 20
RETRIES = 3

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_TOOL_ERROR = 2

PYPI = "PyPI"
NPM = "npm"


class Severity(IntEnum):
    """Ordered, so `severity >= Severity.HIGH` reads as it should. UNKNOWN is
    above CRITICAL on purpose: it fails the run, like the worst case."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    UNKNOWN = 5


FAILING = Severity.HIGH

_RATINGS = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "moderate": Severity.MEDIUM,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
}


class ScaError(Exception):
    """The scanner cannot do its job: exit 2."""


class OsvUnavailable(ScaError):
    """OSV could not be reached, or answered with something unusable."""


class OsvNotFound(Exception):
    """OSV has no record with this id (a 404). Only for alias lookups."""


FetchJson = Callable[[str, "dict[str, Any] | None"], Any]


@dataclass(frozen=True, order=True)
class Package:
    ecosystem: str
    name: str
    version: str

    def __str__(self) -> str:
        return f"{self.name}=={self.version}" if self.ecosystem == PYPI else f"{self.name}@{self.version}"


@dataclass(frozen=True, order=True)
class Vulnerability:
    package: Package
    id: str
    severity: Severity
    fixed: tuple[str, ...]

    def __str__(self) -> str:
        fixed = f"fixed in {', '.join(self.fixed)}" if self.fixed else "no fixed version yet"
        return f"{self.package}  {self.id}  {self.severity.name}  {fixed}"


@dataclass(frozen=True, order=True)
class Violation:
    """A policy problem that is not a vulnerability: an unpinned requirement,
    a missing lock file."""

    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}  {self.message}"


# --- Names --------------------------------------------------------------------


def normalise_pypi(name: str) -> str:
    """PEP 503: case-insensitive, and runs of -, _ and . are the same."""
    return re.sub(r"[-_.]+", "-", name).lower()


# --- Requirements files ---------------------------------------------------------

_REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?P<spec>[^;]*)(?:;.*)?$")
_EXACT_PIN = re.compile(r"^==\s*[A-Za-z0-9][A-Za-z0-9.+!_-]*$")


def check_pins(path: str, text: str) -> list[Violation]:
    """Every requirement must be `name==version`. Anything else is reported:
    ranges (>=, ~=, <), wildcards (==3.*), no version, URLs, VCS and editable
    installs, and includes (-r/-c), which this check does not follow."""
    violations: list[Violation] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        where = f"{path}:{number}"
        if line.startswith(("-e", "--editable")) or re.match(r"^(git|hg|svn|bzr)\+", line):
            violations.append(Violation(where, f"{line!r} installs from a repository; pin a released version with =="))
        elif line.startswith("-"):
            violations.append(Violation(where, f"{line!r} is an option or include this check does not follow"))
        elif "://" in line or " @ " in line or line.startswith("@"):
            violations.append(Violation(where, f"{line!r} installs from a URL; pin a released version with =="))
        elif not (match := _REQUIREMENT.match(line)):
            violations.append(Violation(where, f"{line!r} is not a requirement this check understands"))
        elif not _EXACT_PIN.match(spec := match.group("spec").strip()) or "*" in spec:
            shown = spec or "no version"
            violations.append(Violation(where, f"{match.group('name')} is not pinned ({shown}); use =="))
    return violations


def installed_packages() -> list[Package]:
    """Every distribution installed where this interpreter runs, transitive
    dependencies included."""
    packages = {
        Package(PYPI, normalise_pypi(dist.metadata["Name"]), dist.version)
        for dist in importlib.metadata.distributions()
        if dist.metadata["Name"]
    }
    return sorted(packages)


# --- npm lock files -----------------------------------------------------------------


def parse_package_lock(text: str) -> list[Package]:
    """Every package in a v2 or v3 package-lock.json, from its `packages`
    map. The root project ("") and workspace links are not packages we
    download, so they are skipped. A v1 lock file has no `packages` map and
    is refused rather than half-read."""
    try:
        lock = json.loads(text)
    except json.JSONDecodeError as error:
        raise ScaError(f"package-lock.json is not valid JSON: {error}") from error
    version = lock.get("lockfileVersion") if isinstance(lock, dict) else None
    if version not in (2, 3) or not isinstance(lock.get("packages"), dict):
        raise ScaError(f"unsupported package-lock.json (lockfileVersion {version!r}); run npm 7 or later")
    packages = set()
    for path, entry in lock["packages"].items():
        if path == "" or entry.get("link"):
            continue
        # "node_modules/a/node_modules/@scope/b" is the package @scope/b.
        name = entry.get("name") or path.rsplit("node_modules/", 1)[-1]
        if "version" not in entry:
            raise ScaError(f"package-lock.json entry {path!r} has no version")
        packages.add(Package(NPM, name, entry["version"]))
    return sorted(packages)


# --- CVSS v3 --------------------------------------------------------------------------

_CVSS3_WEIGHTS: dict[str, dict[str, float]] = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
# Privileges Required weighs more when the scope changes.
_CVSS3_PR = {"U": {"N": 0.85, "L": 0.62, "H": 0.27}, "C": {"N": 0.85, "L": 0.68, "H": 0.5}}


def _roundup(value: float) -> float:
    """CVSS 3.1's Roundup: the smallest number with one decimal that is >= value,
    computed on integers to avoid floating-point surprises (spec, Appendix A)."""
    as_int = round(value * 100_000)
    if as_int % 10_000 == 0:
        return as_int / 100_000
    return (math.floor(as_int / 10_000) + 1) / 10.0


def cvss3_base_score(vector: str) -> float:
    """The base score of a CVSS v3.0/v3.1 vector, per the FIRST specification.
    Raises ValueError for anything that is not a complete v3 vector."""
    parts = vector.split("/")
    if not parts or not parts[0].startswith("CVSS:3."):
        raise ValueError(f"not a CVSS v3 vector: {vector!r}")
    metrics = dict(part.split(":", 1) for part in parts[1:] if ":" in part)
    try:
        scope = metrics["S"]
        weight = {key: _CVSS3_WEIGHTS[key][metrics[key]] for key in _CVSS3_WEIGHTS}
        privileges = _CVSS3_PR[scope][metrics["PR"]]
    except KeyError as error:
        raise ValueError(f"incomplete or invalid CVSS v3 vector: {vector!r}") from error
    iss = 1 - (1 - weight["C"]) * (1 - weight["I"]) * (1 - weight["A"])
    if scope == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    exploitability = 8.22 * weight["AV"] * weight["AC"] * privileges * weight["UI"]
    if impact <= 0:
        return 0.0
    if scope == "U":
        return _roundup(min(impact + exploitability, 10))
    return _roundup(min(1.08 * (impact + exploitability), 10))


def rating_for_score(score: float) -> Severity:
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    if score > 0.0:
        return Severity.LOW
    return Severity.NONE


# --- Reading one OSV record ---------------------------------------------------------


def _matches(affected: dict[str, Any], package: Package) -> bool:
    pkg = affected.get("package", {})
    if pkg.get("ecosystem") != package.ecosystem:
        return False
    name = pkg.get("name", "")
    return normalise_pypi(name) == package.name if package.ecosystem == PYPI else name == package.name


def own_severity(record: dict[str, Any], package: Package) -> Severity | None:
    """The severity a record states for this package, or None if it states none."""
    rating = (record.get("database_specific") or {}).get("severity")
    if isinstance(rating, str) and rating.lower() in _RATINGS:
        return _RATINGS[rating.lower()]
    for affected in record.get("affected", []):
        if _matches(affected, package):
            for key in ("database_specific", "ecosystem_specific"):
                rating = (affected.get(key) or {}).get("severity")
                if isinstance(rating, str) and rating.lower() in _RATINGS:
                    return _RATINGS[rating.lower()]
    for entry in record.get("severity", []):
        if entry.get("type") == "CVSS_V3":
            try:
                return rating_for_score(cvss3_base_score(entry.get("score", "")))
            except ValueError:
                continue
    return None


def fixed_versions(record: dict[str, Any], package: Package) -> tuple[str, ...]:
    fixed = {
        event["fixed"]
        for affected in record.get("affected", [])
        if _matches(affected, package)
        for range_ in affected.get("ranges", [])
        for event in range_.get("events", [])
        if "fixed" in event
    }
    return tuple(sorted(fixed))


# --- Talking to OSV ---------------------------------------------------------------


def _query(package: Package, page_token: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {
        "package": {"name": package.name, "ecosystem": package.ecosystem},
        "version": package.version,
    }
    if page_token:
        query["page_token"] = page_token
    return query


def vulnerability_ids(
    packages: Sequence[Package], fetch_json: FetchJson, batch_limit: int = BATCH_LIMIT
) -> dict[Package, list[str]]:
    """The OSV ids affecting each package, from querybatch: in chunks of at
    most batch_limit queries, following next_page_token until every package
    is complete."""
    found: dict[Package, list[str]] = {package: [] for package in packages}
    pending: list[tuple[Package, str | None]] = [(package, None) for package in packages]
    while pending:
        next_round: list[tuple[Package, str | None]] = []
        for start in range(0, len(pending), batch_limit):
            chunk = pending[start : start + batch_limit]
            reply = fetch_json(f"{OSV_API}/querybatch", {"queries": [_query(p, t) for p, t in chunk]})
            results = reply.get("results") if isinstance(reply, dict) else None
            if not isinstance(results, list) or len(results) != len(chunk):
                raise OsvUnavailable("OSV querybatch answered with an unexpected shape; refusing to guess")
            for (package, _), result in zip(chunk, results, strict=True):
                found[package].extend(v["id"] for v in (result or {}).get("vulns", []))
                if token := (result or {}).get("next_page_token"):
                    next_round.append((package, token))
        pending = next_round
    return found


class Advisories:
    """OSV records by id, each fetched at most once per run."""

    def __init__(self, fetch_json: FetchJson) -> None:
        self._fetch_json = fetch_json
        self._records: dict[str, dict[str, Any] | None] = {}

    def get(self, vuln_id: str) -> dict[str, Any]:
        record = self._lookup(vuln_id)
        if record is None:
            raise OsvUnavailable(f"OSV listed {vuln_id} but has no record of it")
        return record

    def get_alias(self, vuln_id: str) -> dict[str, Any] | None:
        """An alias may be an id OSV does not hold (many CVE ids): None then."""
        return self._lookup(vuln_id)

    def _lookup(self, vuln_id: str) -> dict[str, Any] | None:
        if vuln_id not in self._records:
            try:
                self._records[vuln_id] = self._fetch_json(f"{OSV_API}/vulns/{vuln_id}", None)
            except OsvNotFound:
                self._records[vuln_id] = None
        return self._records[vuln_id]


def assess(package: Package, vuln_id: str, advisories: Advisories) -> Vulnerability:
    record = advisories.get(vuln_id)
    severity = own_severity(record, package)
    if severity is None:
        for alias in sorted(record.get("aliases", [])):
            alias_record = advisories.get_alias(alias)
            if alias_record is not None and (severity := own_severity(alias_record, package)) is not None:
                break
    return Vulnerability(
        package, vuln_id, Severity.UNKNOWN if severity is None else severity, fixed_versions(record, package)
    )


def find_vulnerabilities(
    packages: Sequence[Package], fetch_json: FetchJson, batch_limit: int = BATCH_LIMIT
) -> list[Vulnerability]:
    advisories = Advisories(fetch_json)
    ids = vulnerability_ids(packages, fetch_json, batch_limit)
    return sorted(assess(package, vuln_id, advisories) for package in packages for vuln_id in sorted(set(ids[package])))


# --- The real HTTP layer -------------------------------------------------------------


def make_fetch_json(
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = RETRIES,
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> FetchJson:
    """fetch_json over urllib: POST JSON when given a body, GET otherwise.

    Retries a limited number of times, with growing pauses, on what can pass
    on its own: timeouts, connection failures, 429 and 5xx. A 404 is
    OsvNotFound. Anything else, or running out of retries, is OsvUnavailable.
    """

    def fetch_json(url: str, body: dict[str, Any] | None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(url, data=data, headers=headers, method="GET" if body is None else "POST")
        last_error = ""
        for attempt in range(retries + 1):
            if attempt:
                sleep(2 ** (attempt - 1))
            try:
                with opener(request, timeout=timeout_s) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    raise OsvNotFound(url) from error
                if error.code != 429 and error.code < 500:
                    raise OsvUnavailable(f"OSV refused {url}: HTTP {error.code}") from error
                last_error = f"HTTP {error.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = str(getattr(error, "reason", error))
            except json.JSONDecodeError as error:
                raise OsvUnavailable(f"OSV answered {url} with something that is not JSON") from error
        raise OsvUnavailable(f"OSV unreachable after {retries + 1} attempts ({last_error}); nothing was checked")

    return fetch_json


# --- Running it -------------------------------------------------------------------------


@dataclass(frozen=True)
class Report:
    violations: tuple[Violation, ...]
    vulnerabilities: tuple[Vulnerability, ...]

    @property
    def failing(self) -> tuple[Vulnerability, ...]:
        return tuple(v for v in self.vulnerabilities if v.severity >= FAILING)

    def lines(self) -> Iterator[str]:
        yield from (str(v) for v in self.violations)
        yield from (str(v) for v in self.vulnerabilities)

    @property
    def exit_code(self) -> int:
        return EXIT_FINDINGS if self.violations or self.failing else EXIT_CLEAN


def scan_python(
    requirement_files: Iterable[Path],
    fetch_json: FetchJson,
    installed: Callable[[], list[Package]] = installed_packages,
    read_text: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8"),
) -> Report:
    violations: list[Violation] = []
    for path in requirement_files:
        try:
            text = read_text(path)
        except OSError as error:
            raise ScaError(f"cannot read {path.as_posix()}: {error}") from error
        violations.extend(check_pins(path.as_posix(), text))
    packages = installed()
    if not packages:
        raise ScaError("no installed packages found; run this inside the service's virtual environment")
    return Report(tuple(violations), tuple(find_vulnerabilities(packages, fetch_json)))


def scan_npm(
    project: Path,
    fetch_json: FetchJson,
    read_text: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8"),
) -> Report:
    lock = project / "package-lock.json"
    try:
        text = read_text(lock)
    except FileNotFoundError:
        missing = Violation(
            lock.as_posix(), "missing: without a lock file every install can resolve different versions"
        )
        return Report((missing,), ())
    except OSError as error:
        raise ScaError(f"cannot read {lock.as_posix()}: {error}") from error
    return Report((), tuple(find_vulnerabilities(parse_package_lock(text), fetch_json)))


def main(argv: Sequence[str] | None = None, fetch_json: FetchJson | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hand-written SCA for this repository.")
    sub = parser.add_subparsers(dest="ecosystem", required=True)
    py = sub.add_parser("python", help="pinning of requirements files + the installed environment")
    py.add_argument("--requirements", action="append", type=Path, required=True, metavar="FILE")
    npm = sub.add_parser("npm", help="the lock file of a JavaScript project")
    npm.add_argument("--project", type=Path, required=True, metavar="DIR")
    args = parser.parse_args(argv)
    fetch = fetch_json or make_fetch_json()
    try:
        if args.ecosystem == "python":
            report = scan_python(args.requirements, fetch)
        else:
            report = scan_npm(args.project, fetch)
    except ScaError as error:
        print(f"sca: error: {error}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    for line in report.lines():
        print(line)
    print(
        f"sca: {len(report.violations)} policy violation(s), {len(report.vulnerabilities)} vulnerability(ies), "
        f"{len(report.failing)} at {FAILING.name} or above (or unknown)",
        file=sys.stderr,
    )
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
