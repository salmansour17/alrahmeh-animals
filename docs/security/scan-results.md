# Security scan results and triage

What each scanner found when it was first run on the whole repository, and
what was done about every finding. Newer results are in each workflow run on
GitHub; this file records the decisions.

## 2026-11-25: first full run

### Hand-written SAST (`security/sast.py`)

| Scope | Findings | Outcome |
|---|---|---|
| `services` (application code) and `ui/src` | 0 | clean, no suppressions needed |
| `services/*/tests` | 36 | true positives, accepted: excluded in CI with `--exclude tests` |

The 36 in the tests are 15 `py-hardcoded-secret` (made-up passwords and
Stripe keys the tests need, such as the fake `sk_live_` key that proves a live
key is refused) and 21 `py-sql-from-strings` (fixtures that create and drop a
throwaway database per test run, `CREATE DATABASE [{name}]`, with names from
constants). None of it runs in a deployed service. The reason is written next
to the `--exclude` in `scanners.yml`.

Every rule was then proven able to fail: a copy of a real file
(`donations/service.py`, `ui/src/pages/home.jsx`) with one violation added per
rule was caught by all 11 rules, and the unmodified copies scanned clean.

### Hand-written SCA (`security/sca.py`)

| Target | Result | Outcome |
|---|---|---|
| `ui` | **vite 8.3.2: GHSA-587h-7wmj-h5pm, HIGH** (plus 4 MEDIUM, 1 LOW) | **fixed**: vite 8.3.3; all six gone, build checked |
| animals, donations, enquiries | flask 3.1.0: 3 LOW, 1 MEDIUM; pytest 8.3.4: 2 MEDIUM | below the gate; left to Dependabot's weekly update |
| all requirements files | every line pinned with `==` | clean |

Each service was checked in a fresh virtual environment holding only its own
requirements (24 packages for donations), so transitive dependencies such as
werkzeug, jinja2 and urllib3 were included. Proven to fail closed: an
unpinned `flask>=3.1` (exit 1), the old lock file with vite 8.3.2 (exit 1), a
missing lock file (exit 1), and OSV unreachable from a container with no
network (exit 2, "nothing was checked").

### Trivy image scan (`security.yml`)

| Image | Before | After |
|---|---|---|
| all three, on `python:3.13.9-slim-bookworm` | many fixable HIGH/CRITICAL in Debian packages | |
| all three, on `python:3.13.18-slim-bookworm`, pip removed, Pillow 13.0.0 | | **0 fixable** HIGH/CRITICAL; 46 unfixed (no Debian fix exists) |

Three changes, each removing something rather than hiding it:

1. **Base image 3.13.9 → 3.13.18** (same Debian release, newer patches),
   pinned by its multi-platform index digest.
2. **pip removed from the final image** after installing. The running service
   never installs anything, and pip carried its own outdated copies of
   urllib3, msgpack and setuptools.
3. **Pillow 12.3.0 → 13.0.0** in animals (a CRITICAL with a fix). All 255
   animals tests pass on it.

The 46 unfixed findings are not gated (`ignore-unfixed`, explained in
`security.yml`) but are uploaded to the Security tab, and the weekly run
fails as soon as Debian publishes a fix for any of them.

### Trivy config scan

0 HIGH or CRITICAL. Accepted below the gate: AZU-0022 (the SQL server allows
public network access, needed because the Container Apps reach it over the
internet; the firewall admits Azure services only) and AZU-0027 (auditing off;
it needs a Log Analytics workspace or storage account, a billed resource the
brief excludes). LOW DS-0026 ×3: no `HEALTHCHECK` in the Dockerfiles, because
Container Apps uses its own startup and readiness probes on `/health` and
ignores Docker's.

### gitleaks (full history)

4 findings in old commits, all checked by hand and none a secret: three
made-up Stripe keys in Assignment 1 tests and one `curl -u staff:$ADMIN_PASSWORD`
example that reads the password from a variable. History cannot be rewritten,
so each is listed by exact fingerprint in `.gitleaksignore` with its reason;
anything new still fails. The same test lines carry `gitleaks:allow` comments
so the pre-commit hook does not flag them again.

### Conftest (our own Rego policies)

All Dockerfiles and the Terraform pass. Each rule was proven able to fail on a
broken copy: root user, no USER, `latest`, a missing digest; `min_replicas`
1, `max_replicas` 3, insecure ingress, a missing readiness probe, a database
URL as a plain environment value, a firewall rule open to the internet, TLS
1.0; and the guards that fail if the input is not what the rules expect.
