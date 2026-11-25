# Hand-written security scanners

Two scanners written for this repository, using only Python's standard library.
They run in `.github/workflows/scanners.yml` on every push and pull request,
and before every deploy (`cd.yml` deploys only if they pass). The established
tools (Trivy, gitleaks, Conftest) run separately in `security.yml`.

Exit codes for both: **0** clean, **1** findings, **2** the scanner itself
could not run (missing path, bad arguments, OSV unreachable). CI fails on 1
and on 2, but the log tells you which.

## `sast.py`: static analysis of our source

Python is parsed with `ast` and walked once; the website's JavaScript is
checked with regular expressions on a copy in which comments and string
contents are blanked out. List the rules with `python sast.py --list-rules`.

| Rule | Catches |
|---|---|
| `py-sql-from-strings` | SQL passed to `execute()`/`executemany()` built with f-strings, `%`, `.format()` or `+`, also when built in a variable first |
| `py-eval-exec` | `eval()`, `exec()` |
| `py-shell-true` | `subprocess.*(..., shell=True)`, `os.system`, `os.popen`, `subprocess.getoutput` |
| `py-unsafe-deserialization` | `pickle.load(s)`, `yaml.load` without `SafeLoader` |
| `py-weak-hash` | `hashlib.md5`, `hashlib.sha1`, `hashlib.new("md5")`, even with `usedforsecurity=False` |
| `py-hardcoded-secret` | a string literal assigned to a name like `password`, `secret`, `token`, `api_key` |
| `py-debug-enabled` | `app.run(debug=True)`, `app.debug = True`, `DEBUG = True` |
| `py-request-without-timeout` | `requests.*`, `httpx.*`, `urllib.request.urlopen` without `timeout` |
| `js-dangerously-set-inner-html` | React's `dangerouslySetInnerHTML` |
| `js-inner-html` | assigning `innerHTML`/`outerHTML`, `insertAdjacentHTML(` |
| `js-eval` | `eval(` |

Import aliases are resolved, so `from hashlib import md5 as m; m()` is still
caught. Files that do not parse are reported, never skipped. Each rule's
limits are written in its docstring in `sast.py`.

```bash
python security/sast.py services ui/src --exclude tests   # what CI runs
python security/sast.py services/donations/donations/service.py
```

Always skipped when walking a directory: `node_modules`, `.venv`, `venv`,
`__pycache__`, `.git`, `dist`. Anything else only with `--exclude NAME`.

## `sca.py`: our dependencies

- every line of a service's `requirements.txt` pins one version with `==`;
- `ui/package-lock.json` exists (lockfile v2 or v3);
- every installed Python package (transitive ones included) and every package
  in the lock file is looked up in [OSV](https://osv.dev). HIGH and CRITICAL
  fail; so does a vulnerability whose severity is unknown (fail closed).

```bash
# Python: run it inside a fresh environment holding only that service.
python -m venv --without-pip /tmp/venv
python -m pip --python /tmp/venv/bin/python install -r services/animals/requirements.txt
/tmp/venv/bin/python security/sca.py python --requirements services/animals/requirements.txt

# The website: nothing to install.
python security/sca.py npm --project ui
```

How severity is decided, and what happens when OSV cannot be reached, is
explained at the top of `sca.py`.

## Suppressing a SAST finding

Only when the code is genuinely safe, on the line the finding points at:

```python
digest = hashlib.md5(body)  # sast: ignore[py-weak-hash] ETag for caching, not security
```

```js
el.innerHTML = TEMPLATE; // sast: ignore[js-inner-html] constant markup, no user input
```

The reason is required. An ignore with no reason, an unknown rule id, or one
that silences nothing is itself reported, and cannot be suppressed. SCA has
no suppressions: fix the version, or the run stays red.

## Adding a SAST rule

1. Add a rule id constant at the top of `sast.py`.
2. Python: write a `PythonRule` subclass with `id`, `description`,
   `node_types` (the `ast` node classes it wants) and `check()`, which yields
   `Hit(line, message)`. Use `ctx.qualified_name()` for call targets so
   aliases are handled. JavaScript: add a `JsRule` with a regular expression.
3. Add it to `PYTHON_RULES` or `JS_RULES`. The walker needs no change.
4. Add code it must catch to `BAD_PYTHON`/`BAD_JS` and code it must not flag
   to `SAFE_PYTHON`/`SAFE_JS` in `tests/test_sast.py`. A test fails if a rule
   has no examples on either side.

## Running the scanners' own tests

```bash
cd security
pip install -r requirements-test.txt
python -m pytest --cov        # fails below 95% coverage
```
