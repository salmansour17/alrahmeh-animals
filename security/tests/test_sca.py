"""Tests for sca.py. OSV is replaced by FakeOsv, so nothing here uses the
network, the clock or the installed environment."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

import sca
from sca import NPM, PYPI, Package, Severity

FLASK = Package(PYPI, "flask", "3.1.0")
JINJA = Package(PYPI, "jinja2", "3.1.4")


def record(
    vuln_id: str,
    package: Package,
    rating: str | None = None,
    cvss: str | None = None,
    fixed: str | None = "9.9.9",
    aliases: tuple[str, ...] = (),
) -> dict[str, Any]:
    """An OSV record shaped like the real ones."""
    rec: dict[str, Any] = {
        "id": vuln_id,
        "aliases": list(aliases),
        "affected": [
            {
                "package": {"ecosystem": package.ecosystem, "name": package.name},
                "ranges": [
                    {"type": "ECOSYSTEM", "events": [{"introduced": "0"}] + ([{"fixed": fixed}] if fixed else [])}
                ],
            }
        ],
    }
    if rating:
        rec["database_specific"] = {"severity": rating}
    if cvss:
        rec["severity"] = [{"type": "CVSS_V3", "score": cvss}]
    return rec


class FakeOsv:
    """Answers querybatch and vulns/{id} from dictionaries, and remembers
    every call. page_size > 0 splits each package's ids into pages."""

    def __init__(
        self,
        affecting: dict[Package, list[str]] | None = None,
        records: dict[str, dict[str, Any]] | None = None,
        page_size: int = 0,
    ) -> None:
        self.affecting = affecting or {}
        self.records = records or {}
        self.page_size = page_size
        self.batches: list[list[dict[str, Any]]] = []
        self.fetched: list[str] = []

    def __call__(self, url: str, body: dict[str, Any] | None) -> Any:
        if url.endswith("/querybatch"):
            assert body is not None
            self.batches.append(body["queries"])
            return {"results": [self._answer(q) for q in body["queries"]]}
        vuln_id = url.rsplit("/", 1)[1]
        self.fetched.append(vuln_id)
        if vuln_id not in self.records:
            raise sca.OsvNotFound(url)
        return self.records[vuln_id]

    def _answer(self, query: dict[str, Any]) -> dict[str, Any]:
        package = Package(query["package"]["ecosystem"], query["package"]["name"], query["version"])
        ids = self.affecting.get(package, [])
        if not ids:
            return {}
        if not self.page_size:
            return {"vulns": [{"id": i} for i in ids]}
        start = int(query.get("page_token", 0))
        page = ids[start : start + self.page_size]
        answer: dict[str, Any] = {"vulns": [{"id": i} for i in page]}
        if start + self.page_size < len(ids):
            answer["next_page_token"] = str(start + self.page_size)
        return answer


def scan(packages: list[Package], osv: FakeOsv, requirements: str = "flask==3.1.0\n") -> sca.Report:
    return sca.scan_python(
        [Path("services/x/requirements.txt")],
        osv,
        installed=lambda: packages,
        read_text=lambda path: requirements,
    )


# --- Outcomes ----------------------------------------------------------------------


def test_clean_environment_passes() -> None:
    report = scan([FLASK, JINJA], FakeOsv())
    assert report.exit_code == sca.EXIT_CLEAN
    assert list(report.lines()) == []


def test_one_high_fails() -> None:
    osv = FakeOsv({FLASK: ["GHSA-high"]}, {"GHSA-high": record("GHSA-high", FLASK, rating="HIGH", fixed="3.1.3")})
    report = scan([FLASK, JINJA], osv)
    assert report.exit_code == sca.EXIT_FINDINGS
    assert list(report.lines()) == ["flask==3.1.0  GHSA-high  HIGH  fixed in 3.1.3"]


def test_one_critical_fails() -> None:
    osv = FakeOsv({JINJA: ["GHSA-crit"]}, {"GHSA-crit": record("GHSA-crit", JINJA, rating="CRITICAL", fixed=None)})
    report = scan([FLASK, JINJA], osv)
    assert report.exit_code == sca.EXIT_FINDINGS
    assert list(report.lines()) == ["jinja2==3.1.4  GHSA-crit  CRITICAL  no fixed version yet"]


def test_only_low_and_medium_pass_but_are_listed() -> None:
    osv = FakeOsv(
        {FLASK: ["GHSA-low", "GHSA-mod"]},
        {"GHSA-low": record("GHSA-low", FLASK, rating="LOW"), "GHSA-mod": record("GHSA-mod", FLASK, rating="MODERATE")},
    )
    report = scan([FLASK], osv)
    assert report.exit_code == sca.EXIT_CLEAN
    assert [v.severity for v in report.vulnerabilities] == [Severity.LOW, Severity.MEDIUM]


def test_unknown_severity_fails_closed() -> None:
    osv = FakeOsv({FLASK: ["PYSEC-x"]}, {"PYSEC-x": record("PYSEC-x", FLASK)})
    report = scan([FLASK], osv)
    assert report.exit_code == sca.EXIT_FINDINGS
    assert list(report.lines()) == ["flask==3.1.0  PYSEC-x  UNKNOWN  fixed in 9.9.9"]


# --- Where the severity comes from ---------------------------------------------------


def test_severity_from_cvss_vector_when_no_rating() -> None:
    osv = FakeOsv(
        {FLASK: ["PYSEC-x"]},
        {"PYSEC-x": record("PYSEC-x", FLASK, cvss="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")},
    )
    assert [v.severity for v in scan([FLASK], osv).vulnerabilities] == [Severity.CRITICAL]


def test_severity_from_affected_entry() -> None:
    rec = record("GHSA-a", FLASK)
    rec["affected"][0]["database_specific"] = {"severity": "HIGH"}
    assert sca.own_severity(rec, FLASK) == Severity.HIGH


def test_affected_entry_for_another_package_is_ignored() -> None:
    rec = record("GHSA-a", JINJA)
    rec["affected"][0]["ecosystem_specific"] = {"severity": "HIGH"}
    assert sca.own_severity(rec, FLASK) is None


def test_affected_entry_in_another_ecosystem_is_ignored() -> None:
    rec = record("GHSA-a", Package(NPM, "flask", "3.1.0"))
    rec["affected"][0]["database_specific"] = {"severity": "HIGH"}
    assert sca.own_severity(rec, FLASK) is None


def test_severity_from_an_alias_when_the_record_has_none() -> None:
    osv = FakeOsv(
        {FLASK: ["PYSEC-x"]},
        {
            "PYSEC-x": record("PYSEC-x", FLASK, aliases=("CVE-1", "GHSA-y")),
            "GHSA-y": record("GHSA-y", FLASK, rating="MODERATE"),
        },
    )
    report = scan([FLASK], osv)
    assert [v.severity for v in report.vulnerabilities] == [Severity.MEDIUM]
    assert osv.fetched == ["PYSEC-x", "CVE-1", "GHSA-y"]  # CVE-1 is not in OSV: skipped


def test_invalid_cvss_vector_is_skipped() -> None:
    rec = record("X", FLASK, cvss="CVSS:3.1/AV:Q")
    assert sca.own_severity(rec, FLASK) is None


def test_cvss_v4_alone_is_unknown() -> None:
    rec = record("X", FLASK)
    rec["severity"] = [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"}]
    assert sca.own_severity(rec, FLASK) is None


@pytest.mark.parametrize(
    ("vector", "score"),
    [
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
        ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", 5.5),
        ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N", 5.9),
        ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 8.8),
        ("CVSS:3.0/AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:H", 8.8),
        ("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:N/I:N/A:N", 0.0),
    ],
)
def test_cvss3_base_score_matches_the_specification(vector: str, score: float) -> None:
    assert sca.cvss3_base_score(vector) == score


@pytest.mark.parametrize(
    "vector", ["", "CVSS:2.0/AV:N", "CVSS:3.1/AV:N/AC:L", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:X/C:H/I:H/A:H"]
)
def test_cvss3_rejects_bad_vectors(vector: str) -> None:
    with pytest.raises(ValueError):
        sca.cvss3_base_score(vector)


@pytest.mark.parametrize(
    ("score", "rating"),
    [(0.0, Severity.NONE), (0.1, Severity.LOW), (4.0, Severity.MEDIUM), (7.0, Severity.HIGH), (9.0, Severity.CRITICAL)],
)
def test_score_ratings(score: float, rating: Severity) -> None:
    assert sca.rating_for_score(score) == rating


def test_roundup_keeps_exact_tenths() -> None:
    assert sca._roundup(4.0) == 4.0
    assert sca._roundup(4.02) == 4.1
    assert sca._roundup(4.000001) == 4.0  # within floating-point noise, per the spec


# --- Pinning ------------------------------------------------------------------------------


def test_pinned_requirements_pass() -> None:
    text = (
        "# comment\n\nflask==3.1.0  # why\nPillow==13.0.0\n"
        "uvicorn[standard]==0.30.0\nfoo==1.0 ; python_version < '3.12'\n"
    )
    assert sca.check_pins("r.txt", text) == []


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        ("flask>=3.1", "flask is not pinned (>=3.1)"),
        ("flask~=3.1", "flask is not pinned (~=3.1)"),
        ("flask", "flask is not pinned (no version)"),
        ("flask==3.*", "flask is not pinned (==3.*)"),
        ("flask==3.1,<4", "flask is not pinned (==3.1,<4)"),
        ("https://example.com/flask.tar.gz", "installs from a URL"),
        ("flask @ https://example.com/flask.whl", "installs from a URL"),
        ("git+https://github.com/pallets/flask", "installs from a repository"),
        ("-e ./local", "installs from a repository"),
        ("-r other.txt", "option or include"),
        ("!!!", "not a requirement this check understands"),
    ],
)
def test_unpinned_requirements_are_violations(line: str, fragment: str) -> None:
    violations = sca.check_pins("r.txt", f"ok==1.0\n{line}\n")
    assert len(violations) == 1
    assert violations[0].location == "r.txt:2"
    assert fragment in violations[0].message


def test_pinning_violation_fails_even_without_vulnerabilities() -> None:
    report = scan([FLASK], FakeOsv(), requirements="flask>=3\n")
    assert report.exit_code == sca.EXIT_FINDINGS
    assert list(report.lines()) == ["services/x/requirements.txt:1  flask is not pinned (>=3); use =="]


def test_unreadable_requirements_file_is_a_tool_error() -> None:
    def refuse(path: Path) -> str:
        raise FileNotFoundError(path)

    with pytest.raises(sca.ScaError, match="cannot read"):
        sca.scan_python([Path("missing.txt")], FakeOsv(), installed=lambda: [FLASK], read_text=refuse)


def test_empty_environment_is_a_tool_error() -> None:
    with pytest.raises(sca.ScaError, match="no installed packages"):
        scan([], FakeOsv())


def test_pypi_names_are_normalised() -> None:
    assert sca.normalise_pypi("Flask_SQLAlchemy.ext") == "flask-sqlalchemy-ext"


def test_installed_packages_reads_this_environment() -> None:
    names = {p.name for p in sca.installed_packages()}
    assert "pytest" in names  # it is running these tests
    assert all(p.ecosystem == PYPI for p in sca.installed_packages())


# --- npm lock files ------------------------------------------------------------------------


def lock(version: int, packages: dict[str, Any]) -> str:
    return json.dumps({"name": "ui", "lockfileVersion": version, "packages": {"": {"name": "ui"}, **packages}})


@pytest.mark.parametrize("version", [2, 3])
def test_lock_v2_and_v3_are_parsed(version: int) -> None:
    text = lock(
        version,
        {
            "node_modules/react": {"version": "19.0.0"},
            "node_modules/@scope/pkg": {"version": "1.0.0", "dev": True},
            "node_modules/a/node_modules/react": {"version": "18.3.1"},
            "node_modules/b/node_modules/@scope/deep": {"version": "2.0.0"},
            "packages/local": {"version": "0.0.1", "link": True},
            "node_modules/aliased": {"name": "real-name", "version": "3.0.0"},
        },
    )
    assert sca.parse_package_lock(text) == [
        Package(NPM, "@scope/deep", "2.0.0"),
        Package(NPM, "@scope/pkg", "1.0.0"),
        Package(NPM, "react", "18.3.1"),
        Package(NPM, "react", "19.0.0"),
        Package(NPM, "real-name", "3.0.0"),
    ]


def test_lock_v1_is_refused() -> None:
    with pytest.raises(sca.ScaError, match="unsupported"):
        sca.parse_package_lock(json.dumps({"lockfileVersion": 1, "dependencies": {}}))


def test_lock_that_is_not_json_is_refused() -> None:
    with pytest.raises(sca.ScaError, match="not valid JSON"):
        sca.parse_package_lock("{")


def test_lock_entry_without_version_is_refused() -> None:
    with pytest.raises(sca.ScaError, match="no version"):
        sca.parse_package_lock(lock(3, {"node_modules/x": {}}))


def test_missing_lock_file_is_a_violation(tmp_path: Path) -> None:
    report = sca.scan_npm(tmp_path, FakeOsv())
    assert report.exit_code == sca.EXIT_FINDINGS
    assert [v.message.split(":")[0] for v in report.violations] == ["missing"]


def test_unreadable_lock_file_is_a_tool_error(tmp_path: Path) -> None:
    def refuse(path: Path) -> str:
        raise PermissionError(path)

    with pytest.raises(sca.ScaError, match="cannot read"):
        sca.scan_npm(tmp_path, FakeOsv(), read_text=refuse)


def test_npm_vulnerability_is_found(tmp_path: Path) -> None:
    vite = Package(NPM, "vite", "8.3.2")
    (tmp_path / "package-lock.json").write_text(lock(3, {"node_modules/vite": {"version": "8.3.2", "dev": True}}))
    osv = FakeOsv({vite: ["GHSA-v"]}, {"GHSA-v": record("GHSA-v", vite, rating="HIGH", fixed="8.3.3")})
    report = sca.scan_npm(tmp_path, osv)
    assert list(report.lines()) == ["vite@8.3.2  GHSA-v  HIGH  fixed in 8.3.3"]
    assert osv.batches[0][0]["package"] == {"name": "vite", "ecosystem": "npm"}


# --- Batching and pagination ----------------------------------------------------------------


def test_queries_are_chunked_to_the_batch_limit() -> None:
    packages = [Package(PYPI, f"pkg{i}", "1.0") for i in range(7)]
    osv = FakeOsv({packages[6]: ["GHSA-z"]}, {"GHSA-z": record("GHSA-z", packages[6], rating="LOW")})
    found = sca.find_vulnerabilities(packages, osv, batch_limit=3)
    assert [len(b) for b in osv.batches] == [3, 3, 1]
    assert [v.id for v in found] == ["GHSA-z"]


def test_pagination_is_followed_until_the_end() -> None:
    ids = [f"GHSA-{i}" for i in range(5)]
    osv = FakeOsv({FLASK: ids}, {i: record(i, FLASK, rating="LOW") for i in ids}, page_size=2)
    found = sca.find_vulnerabilities([FLASK, JINJA], osv)
    assert sorted(v.id for v in found) == ids
    # First round asks for both; the next rounds only for flask, with its token.
    assert [len(b) for b in osv.batches] == [2, 1, 1]
    assert [b[0].get("page_token") for b in osv.batches[1:]] == ["2", "4"]


def test_each_record_is_fetched_once() -> None:
    other = Package(PYPI, "flask", "3.0.0")
    osv = FakeOsv({FLASK: ["GHSA-a"], other: ["GHSA-a"]}, {"GHSA-a": record("GHSA-a", FLASK, rating="LOW")})
    sca.find_vulnerabilities([FLASK, other], osv)
    assert osv.fetched == ["GHSA-a"]


def test_malformed_querybatch_answer_is_a_tool_error() -> None:
    with pytest.raises(sca.OsvUnavailable, match="unexpected shape"):
        sca.vulnerability_ids([FLASK], lambda url, body: {"results": []})


def test_listed_id_without_a_record_is_a_tool_error() -> None:
    osv = FakeOsv({FLASK: ["GHSA-gone"]})
    with pytest.raises(sca.OsvUnavailable, match="no record"):
        sca.find_vulnerabilities([FLASK], osv)


# --- The HTTP layer -------------------------------------------------------------------------


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.osv.dev", code, "status", {}, None)  # type: ignore[arg-type]


def opener_from(*outcomes: Any) -> tuple[Any, list[Any]]:
    """An opener that raises or answers each outcome in turn."""
    calls: list[Any] = []
    queue = list(outcomes)

    def open_(request: Any, timeout: float) -> FakeResponse:
        calls.append((request, timeout))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode())

    return open_, calls


def test_fetch_json_posts_json_with_a_timeout() -> None:
    opener, calls = opener_from({"results": []})
    fetch = sca.make_fetch_json(opener=opener, sleep=lambda s: None, timeout_s=7)
    assert fetch("https://api.osv.dev/v1/querybatch", {"queries": []}) == {"results": []}
    request, timeout = calls[0]
    assert (request.get_method(), timeout, json.loads(request.data)) == ("POST", 7, {"queries": []})


def test_fetch_json_gets_without_a_body() -> None:
    opener, calls = opener_from({"id": "X"})
    sca.make_fetch_json(opener=opener, sleep=lambda s: None)("https://api.osv.dev/v1/vulns/X", None)
    assert calls[0][0].get_method() == "GET"


def test_transient_failures_are_retried_with_growing_pauses() -> None:
    pauses: list[float] = []
    opener, calls = opener_from(urllib.error.URLError("down"), http_error(503), TimeoutError(), {"ok": True})
    fetch = sca.make_fetch_json(opener=opener, sleep=pauses.append, retries=3)
    assert fetch("https://api.osv.dev/v1/vulns/X", None) == {"ok": True}
    assert pauses == [1, 2, 4]


def test_network_failure_after_retries_is_osv_unavailable() -> None:
    opener, calls = opener_from(*[urllib.error.URLError("no route")] * 3)
    fetch = sca.make_fetch_json(opener=opener, sleep=lambda s: None, retries=2)
    with pytest.raises(sca.OsvUnavailable, match="unreachable after 3 attempts"):
        fetch("https://api.osv.dev/v1/querybatch", {"queries": []})
    assert len(calls) == 3


def test_rate_limit_is_retried() -> None:
    opener, _ = opener_from(http_error(429), {"ok": True})
    assert sca.make_fetch_json(opener=opener, sleep=lambda s: None)("https://api.osv.dev/v1/vulns/X", None) == {
        "ok": True
    }


def test_404_is_not_found() -> None:
    opener, _ = opener_from(http_error(404))
    with pytest.raises(sca.OsvNotFound):
        sca.make_fetch_json(opener=opener, sleep=lambda s: None)("https://api.osv.dev/v1/vulns/X", None)


def test_other_client_errors_are_not_retried() -> None:
    opener, calls = opener_from(http_error(400))
    with pytest.raises(sca.OsvUnavailable, match="HTTP 400"):
        sca.make_fetch_json(opener=opener, sleep=lambda s: None)("https://api.osv.dev/v1/vulns/X", None)
    assert len(calls) == 1


def test_non_json_answer_is_osv_unavailable() -> None:
    def opener(request: Any, timeout: float) -> FakeResponse:
        return FakeResponse(b"<html>")

    with pytest.raises(sca.OsvUnavailable, match="not JSON"):
        sca.make_fetch_json(opener=opener, sleep=lambda s: None)("https://api.osv.dev/v1/vulns/X", None)


# --- main() and exit codes ------------------------------------------------------------------


def test_main_npm_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "package-lock.json").write_text(lock(3, {"node_modules/react": {"version": "19.0.0"}}))
    assert sca.main(["npm", "--project", str(tmp_path)], fetch_json=FakeOsv()) == sca.EXIT_CLEAN
    assert "0 at HIGH or above" in capsys.readouterr().err


def test_main_python_with_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("flask>=3\n")
    assert sca.main(["python", "--requirements", str(requirements)], fetch_json=FakeOsv()) == sca.EXIT_FINDINGS
    assert "flask is not pinned" in capsys.readouterr().out


def test_main_network_failure_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "package-lock.json").write_text(lock(3, {"node_modules/react": {"version": "19.0.0"}}))

    def offline(url: str, body: dict[str, Any] | None) -> Any:
        raise sca.OsvUnavailable("OSV unreachable after 4 attempts (no route); nothing was checked")

    assert sca.main(["npm", "--project", str(tmp_path)], fetch_json=offline) == sca.EXIT_TOOL_ERROR
    assert "nothing was checked" in capsys.readouterr().err


def test_main_bad_arguments_exit_two() -> None:
    with pytest.raises(SystemExit) as raised:
        sca.main(["python"])
    assert raised.value.code == sca.EXIT_TOOL_ERROR


def test_main_builds_the_real_fetcher_when_none_is_given(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # No lock file, so the fetcher is built but never called: no network.
    built: list[bool] = []
    monkeypatch.setattr(sca, "make_fetch_json", lambda: built.append(True) or FakeOsv())
    assert sca.main(["npm", "--project", str(tmp_path)]) == sca.EXIT_FINDINGS
    assert built == [True]
