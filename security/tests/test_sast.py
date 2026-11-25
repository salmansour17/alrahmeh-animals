"""Tests for sast.py. Every rule has code it must catch and code it must not
flag; then aliases, ignore comments, parse errors, file walking, exit codes."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import sast


def rules_in(source: str) -> list[str]:
    return [f.rule for f in sast.scan_python("x.py", textwrap.dedent(source))]


def js_rules_in(source: str) -> list[str]:
    return [f.rule for f in sast.scan_js("x.jsx", textwrap.dedent(source))]


# --- Each Python rule: must catch / must not flag -------------------------------

BAD_PYTHON = {
    sast.SQL_FROM_STRINGS: [
        'cursor.execute(f"SELECT * FROM t WHERE id = {animal_id}")',
        'cursor.execute("SELECT * FROM t WHERE id = %s" % animal_id)',
        'cursor.execute("SELECT * FROM t WHERE id = {}".format(animal_id))',
        'cursor.execute("SELECT * FROM t WHERE id = " + animal_id)',
        'cursor.executemany(f"INSERT INTO {table} VALUES (%s)", rows)',
        'cursor.execute(sql=f"SELECT {x}")',
        # Built first, passed in later.
        'sql = f"SELECT * FROM t WHERE id = {animal_id}"\ncursor.execute(sql)',
        "sql = \"SELECT * FROM t WHERE name = '%s'\" % name\ncursor.execute(sql, ())",
        'sql = "SELECT * FROM t"\nsql += " WHERE id = " + str(i)\ncursor.execute(sql)',
        'sql = "SELECT * FROM t"\nsql = sql + where\ncursor.execute(sql)',
        'def f(x):\n    sql = "SELECT %s" % x\n    return db.execute(sql)',
        'sql = "SELECT * FROM t WHERE id = %s"\nsql %= animal_id\ncursor.execute(sql)',
    ],
    sast.EVAL_EXEC: [
        "eval(text)",
        "exec(code)",
        "import builtins\nbuiltins.eval(text)",
    ],
    sast.SHELL_TRUE: [
        "import subprocess\nsubprocess.run(cmd, shell=True)",
        "import subprocess\nsubprocess.Popen(cmd, shell=True)",
        "import subprocess\nsubprocess.check_output(cmd, shell=use_shell)",
        "import subprocess\nsubprocess.call(cmd, shell=True)",
        "import subprocess\nsubprocess.check_call(cmd, shell=True)",
        "import subprocess\nsubprocess.getoutput(cmd)",
        "import os\nos.system(cmd)",
        "import os\nos.popen(cmd)",
    ],
    sast.UNSAFE_DESERIALIZATION: [
        "import pickle\npickle.loads(data)",
        "import pickle\npickle.load(f)",
        "import yaml\nyaml.load(text)",
        "import yaml\nyaml.load(text, Loader=yaml.FullLoader)",
        "import yaml\nyaml.load(text, yaml.Loader)",
        "import yaml\nyaml.unsafe_load(text)",
    ],
    sast.WEAK_HASH: [
        "import hashlib\nhashlib.md5(data)",
        "import hashlib\nhashlib.sha1(data)",
        'import hashlib\nhashlib.new("md5", data)',
        'import hashlib\nhashlib.new("SHA1")',
        'import hashlib\nhashlib.new(name="md5")',
        # Flagged on purpose: usedforsecurity=False is not an automatic excuse.
        "import hashlib\nhashlib.md5(data, usedforsecurity=False)",
    ],
    sast.HARDCODED_SECRET: [
        'password = "hunter2-correct-horse"',
        'DB_PASSWORD = "S3cret!value"',
        'api_key = "sk_test_51abc"',
        'self.token = "abc123def"',
        'settings["secret"] = "abc123def"',
        'connect(host="db", password="hunter2-correct-horse")',
        'config = {"signing_key": "abc123def"}',
        'admin_password: str = "hunter2"',
    ],
    sast.DEBUG_ENABLED: [
        "app.run(debug=True)",
        "app.debug = True",
        'app.config["DEBUG"] = True',
        "app.config.update(DEBUG=True)",
        "DEBUG = True",
    ],
    sast.REQUEST_WITHOUT_TIMEOUT: [
        "import requests\nrequests.get(url)",
        "import httpx\nhttpx.post(url, json=body)",
        "import urllib.request\nurllib.request.urlopen(url)",
        "from urllib.request import urlopen\nurlopen(request)",
        "import requests\nrequests.request('GET', url)",
    ],
}

SAFE_PYTHON = {
    sast.SQL_FROM_STRINGS: [
        'cursor.execute("SELECT * FROM t WHERE id = %s", (animal_id,))',
        'cursor.execute("SELECT * FROM t " "WHERE id = %s", (animal_id,))',
        'sql = "SELECT * FROM t WHERE id = %s"\ncursor.execute(sql, (animal_id,))',
        'BASE = "SELECT * FROM t"\nsql = BASE + " WHERE id = %s"\ncursor.execute(sql, (i,))',
        'sql = "SELECT * FROM t"\nsql += " WHERE id = %s"\ncursor.execute(sql, (i,))',
        # A parameter of unknown origin is not judged (the db.py wrapper).
        "def execute(self, sql, params):\n    self.cursor.execute(sql, params)",
        'cursor.execute(f"SELECT 1")',
        'log(f"{x}")\ncursor.execute("SELECT 1")',
        'sql = f"SELECT *" + " FROM t WHERE id = %s"\ncursor.execute(sql, (i,))',
    ],
    sast.EVAL_EXEC: ["model.eval()", "ast.literal_eval(text)", "evaluate(x)"],
    sast.SHELL_TRUE: [
        'import subprocess\nsubprocess.run(["ls", "-l"])',
        'import subprocess\nsubprocess.run(["ls"], shell=False)',
        "import os\nos.path.join(a, b)",
    ],
    sast.UNSAFE_DESERIALIZATION: [
        "import yaml\nyaml.safe_load(text)",
        "import yaml\nyaml.load(text, Loader=yaml.SafeLoader)",
        "import yaml\nyaml.load(text, yaml.CSafeLoader)",
        "import json\njson.loads(data)",
    ],
    sast.WEAK_HASH: [
        "import hashlib\nhashlib.sha256(data)",
        'import hashlib\nhashlib.new("sha256")',
        "import hashlib\nhashlib.new(algorithm)",
    ],
    sast.HARDCODED_SECRET: [
        'password = os.environ["ADMIN_PASSWORD"]',
        'password = os.getenv("ADMIN_PASSWORD", "")',
        'password = ""',
        'password = "changeme"',
        'api_key = "<your key here>"',
        'token = "${TOKEN}"',
        'secret = "xxxxxxxx"',
        'TOKEN_ENV = "TOKEN_SIGNING_KEY"',
        'username = "admin"',
        "password = None",
        'request.headers.get("Authorization")',
        "password, user = read_credentials()",
    ],
    sast.DEBUG_ENABLED: [
        "app.run(debug=False)",
        "app.run()",
        'app.debug = os.environ.get("X") == "1"',
        "debug = 1",
    ],
    sast.REQUEST_WITHOUT_TIMEOUT: [
        "import requests\nrequests.get(url, timeout=5)",
        "import httpx\nhttpx.get(url, timeout=2.0)",
        "from urllib.request import urlopen\nurlopen(request, timeout=3)",
        "import urllib.request\nurllib.request.urlopen(url, None, 3)",
        "data.get(key)",
    ],
}


@pytest.mark.parametrize(("rule", "source"), [(r, s) for r, ss in BAD_PYTHON.items() for s in ss])
def test_python_rule_catches(rule: str, source: str) -> None:
    assert rule in rules_in(source)


@pytest.mark.parametrize(("rule", "source"), [(r, s) for r, ss in SAFE_PYTHON.items() for s in ss])
def test_python_rule_does_not_flag(rule: str, source: str) -> None:
    assert rules_in(source) == []


def test_every_rule_has_bad_and_safe_examples() -> None:
    python_ids = {rule.id for rule in sast.PYTHON_RULES}
    assert set(BAD_PYTHON) == python_ids
    assert set(SAFE_PYTHON) == python_ids
    assert set(BAD_JS) == {rule.id for rule in sast.JS_RULES}
    assert set(SAFE_JS) == {rule.id for rule in sast.JS_RULES}


# --- Aliases: renaming must not get around a rule --------------------------------


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("import hashlib as h\nh.md5(b'x')", sast.WEAK_HASH),
        ("from hashlib import md5\nmd5(b'x')", sast.WEAK_HASH),
        ("from hashlib import sha1 as fast\nfast(b'x')", sast.WEAK_HASH),
        ("import requests as r\nr.get(url)", sast.REQUEST_WITHOUT_TIMEOUT),
        ("from requests import get\nget(url)", sast.REQUEST_WITHOUT_TIMEOUT),
        ("import urllib.request as u\nu.urlopen(url)", sast.REQUEST_WITHOUT_TIMEOUT),
        ("import subprocess as sp\nsp.run(c, shell=True)", sast.SHELL_TRUE),
        ("from os import system as run\nrun(cmd)", sast.SHELL_TRUE),
        ("import pickle as p\np.loads(d)", sast.UNSAFE_DESERIALIZATION),
        ("from yaml import load\nload(text)", sast.UNSAFE_DESERIALIZATION),
    ],
)
def test_import_aliases_are_resolved(source: str, rule: str) -> None:
    assert rules_in(source) == [rule]


def test_safe_loader_imported_by_name_is_recognised() -> None:
    assert rules_in("from yaml import load, SafeLoader\nload(text, Loader=SafeLoader)") == []


def test_local_function_with_a_flagged_name_is_not_resolved_as_the_library() -> None:
    # md5 here is ours, not hashlib's: nothing imported it.
    assert rules_in("def md5(x):\n    return x\nmd5(b'x')") == []


# --- Ignore comments ---------------------------------------------------------------


def test_ignore_with_reason_silences_its_rule() -> None:
    source = "import hashlib\nhashlib.md5(b'x')  # sast: ignore[py-weak-hash] cache key, not security\n"
    assert rules_in(source) == []


def test_ignore_without_reason_is_a_finding_and_silences_nothing() -> None:
    source = "import hashlib\nhashlib.md5(b'x')  # sast: ignore[py-weak-hash]\n"
    assert sorted(rules_in(source)) == [sast.WEAK_HASH, sast.IGNORE_WITHOUT_REASON]


def test_ignore_with_unknown_rule_is_a_finding() -> None:
    source = "import hashlib\nhashlib.md5(b'x')  # sast: ignore[py-weak-hsah] typo in the id\n"
    assert sorted(rules_in(source)) == [sast.WEAK_HASH, sast.IGNORE_UNKNOWN_RULE]


def test_ignore_with_no_rule_is_a_finding() -> None:
    assert rules_in("x = 1  # sast: ignore[] because\n") == [sast.IGNORE_UNKNOWN_RULE]


def test_ignore_for_one_rule_does_not_silence_another() -> None:
    source = "eval(text)  # sast: ignore[py-weak-hash] wrong rule\n"
    assert sorted(rules_in(source)) == [sast.EVAL_EXEC, sast.IGNORE_UNUSED]


def test_ignore_can_name_several_rules() -> None:
    source = 'eval(f"{x}")  # sast: ignore[py-eval-exec, py-weak-hash] demo of two\n'
    assert rules_in(source) == [sast.IGNORE_UNUSED]  # py-weak-hash silenced nothing


def test_ignore_on_another_line_does_not_apply() -> None:
    source = "# sast: ignore[py-eval-exec] on the wrong line\neval(text)\n"
    assert sorted(rules_in(source)) == [sast.EVAL_EXEC, sast.IGNORE_UNUSED]


def test_ignore_text_inside_a_string_is_not_a_comment() -> None:
    source = 'eval("# sast: ignore[py-eval-exec] not a comment")\n'
    assert rules_in(source) == [sast.EVAL_EXEC]


def test_js_ignore_with_reason_silences_its_rule() -> None:
    assert js_rules_in("eval(x) // sast: ignore[js-eval] trusted constant\n") == []


def test_js_ignore_without_reason_is_a_finding() -> None:
    assert sorted(js_rules_in("eval(x) // sast: ignore[js-eval]\n")) == [
        sast.JS_EVAL,
        sast.IGNORE_WITHOUT_REASON,
    ]


# --- JavaScript rules ---------------------------------------------------------------

BAD_JS = {
    sast.JS_DANGEROUSLY_SET_INNER_HTML: ["<div dangerouslySetInnerHTML={{ __html: html }} />"],
    sast.JS_INNER_HTML: [
        "el.innerHTML = html;",
        "el.innerHTML += more;",
        "el.outerHTML = html;",
        "el.insertAdjacentHTML('beforeend', html);",
        "const s = `${(el.innerHTML = x)}`;",
    ],
    sast.JS_EVAL: ["eval(code);", "const f = eval (code);", "window.x = 1; eval(code)"],
}

SAFE_JS = {
    sast.JS_DANGEROUSLY_SET_INNER_HTML: [
        "// dangerouslySetInnerHTML is never used here",
        "const note = 'dangerouslySetInnerHTML';",
        "<p>{text}</p>",
    ],
    sast.JS_INNER_HTML: [
        "el.textContent = text;",
        "if (el.innerHTML === '') {}",
        "const s = 'el.innerHTML = x';",
        "/* el.innerHTML = x */",
        "const t = `el.innerHTML = ${safe}`;",
    ],
    sast.JS_EVAL: [
        "medieval(x);",
        "obj.eval(x);",
        'const s = "eval(x)";',
        "// eval(x)",
        "/* eval(\n x) */",
    ],
}


@pytest.mark.parametrize(("rule", "source"), [(r, s) for r, ss in BAD_JS.items() for s in ss])
def test_js_rule_catches(rule: str, source: str) -> None:
    assert rule in js_rules_in(source)


@pytest.mark.parametrize(("rule", "source"), [(r, s) for r, ss in SAFE_JS.items() for s in ss])
def test_js_rule_does_not_flag(rule: str, source: str) -> None:
    assert js_rules_in(source) == []


def test_js_reports_the_right_line() -> None:
    findings = sast.scan_js("a.js", "const a = 1;\n/* two\nthree */\neval(x);\n")
    assert [(f.line, f.rule) for f in findings] == [(4, sast.JS_EVAL)]


def test_apostrophe_in_jsx_text_only_affects_its_own_line() -> None:
    source = "<p>We're open</p>\neval(x);\n"
    assert js_rules_in(source) == [sast.JS_EVAL]


def test_blank_js_keeps_template_expressions_as_code() -> None:
    code, _ = sast.blank_js("`a ${ {b: 1}.b } c`")
    assert code == ["`  ${ {b: 1}.b }  `"]


def test_blank_js_handles_escapes() -> None:
    code, _ = sast.blank_js("'it\\'s' + `x\\`y`")
    assert code == ["'     ' + `    `"]


# --- Unparsable and unreadable files ------------------------------------------------


def test_unparsable_python_is_a_finding_not_a_skip() -> None:
    findings = sast.scan_python("bad.py", "def broken(:\n    pass\n")
    assert [(f.rule, f.line) for f in findings] == [(sast.PARSE_ERROR, 1)]


def test_non_utf8_file_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / "latin.py").write_bytes(b"x = '\xe9'\n")
    assert [f.rule for f in sast.scan_paths([tmp_path])] == [sast.PARSE_ERROR]


def test_unreadable_file_is_a_tool_error(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")

    def refuse(path: Path) -> str:
        raise PermissionError("denied")

    with pytest.raises(sast.ScanError, match="cannot read"):
        sast.scan_paths([tmp_path], read_text=refuse)


# --- Walking directories ----------------------------------------------------------------


def make_tree(root: Path) -> None:
    for relative in [
        "app/a.py",
        "app/tests/t.py",
        "node_modules/m.js",
        ".venv/v.py",
        "ui/x.jsx",
        "notes.txt",
    ]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("eval(x)\n")


def test_builtin_exclusions_are_skipped(tmp_path: Path) -> None:
    make_tree(tmp_path)
    files = {p.relative_to(tmp_path).as_posix() for p in sast.collect_files([tmp_path], sast.BUILTIN_EXCLUDES)}
    assert files == {"app/a.py", "app/tests/t.py", "ui/x.jsx"}


def test_tests_are_skipped_only_when_configured(tmp_path: Path) -> None:
    make_tree(tmp_path)
    files = sast.collect_files([tmp_path], sast.BUILTIN_EXCLUDES | {"tests"})
    assert {p.relative_to(tmp_path).as_posix() for p in files} == {
        "app/a.py",
        "ui/x.jsx",
    }


def test_a_named_file_is_scanned_even_inside_an_excluded_directory(
    tmp_path: Path,
) -> None:
    make_tree(tmp_path)
    assert sast.collect_files([tmp_path / ".venv" / "v.py"], sast.BUILTIN_EXCLUDES) == [tmp_path / ".venv" / "v.py"]


def test_missing_path_is_a_tool_error(tmp_path: Path) -> None:
    with pytest.raises(sast.ScanError, match="no such file"):
        sast.collect_files([tmp_path / "missing"], sast.BUILTIN_EXCLUDES)


# --- Output and exit codes --------------------------------------------------------------


def test_output_is_sorted_and_one_line_per_finding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "b.py").write_text("eval(x)\n")
    (tmp_path / "a.py").write_text("import os\n\nos.system(c)\neval(x)\n")
    assert sast.main([str(tmp_path)]) == sast.EXIT_FINDINGS
    lines = capsys.readouterr().out.splitlines()
    prefix = tmp_path.as_posix()
    assert lines == [
        f"{prefix}/a.py:3 py-shell-true os.system() runs its command through the shell; "
        "use subprocess.run([...]) with a list",
        f"{prefix}/a.py:4 py-eval-exec eval() runs a string as code",
        f"{prefix}/b.py:1 py-eval-exec eval() runs a string as code",
    ]


def test_exit_zero_when_clean(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("x = 1\n")
    assert sast.main([str(tmp_path)]) == sast.EXIT_CLEAN


def test_exit_two_for_a_missing_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert sast.main([str(tmp_path / "nope")]) == sast.EXIT_TOOL_ERROR
    assert "no such file" in capsys.readouterr().err


def test_exit_two_for_bad_arguments() -> None:
    with pytest.raises(SystemExit) as raised:
        sast.main([])
    assert raised.value.code == sast.EXIT_TOOL_ERROR


def test_exclude_option(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("eval(x)\n")
    assert sast.main([str(tmp_path), "--exclude", "tests"]) == sast.EXIT_CLEAN


def test_list_rules(capsys: pytest.CaptureFixture[str]) -> None:
    assert sast.main(["--list-rules"]) == sast.EXIT_CLEAN
    out = capsys.readouterr().out
    assert all(rule.id in out for rule in (*sast.PYTHON_RULES, *sast.JS_RULES))
