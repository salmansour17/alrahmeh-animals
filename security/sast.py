"""Our own static analysis (SAST): rules for the mistakes this project could
plausibly make, checked on the Python services and the website's JavaScript.

    python security/sast.py services ui/src --exclude tests

Prints one line per finding, `file:line rule message`, sorted. Exit codes:
0 nothing found, 1 findings, 2 the scanner itself could not run (a missing
path, bad arguments), so CI can tell "found issues" from "scanner broke".

How it works
  Python files are parsed with the `ast` module and walked ONCE. Each rule
  says which node types it wants; the walker hands every node to the rules
  that asked for its type (a registry: adding a rule is adding a class to
  PYTHON_RULES, never editing the walker). While walking, the walker also
  records imports, so `import hashlib as h; h.md5()` is still hashlib.md5,
  and which variables hold strings built from pieces, so
  `sql = f"... {x}"; cursor.execute(sql)` is still caught.

  JavaScript has no parser in the standard library, so its rules are regular
  expressions run on a copy of the code in which comments and the contents of
  strings are blanked out (line numbers kept). `// eval(x)` or "innerHTML ="
  inside a string therefore never match. Known limit, acknowledged: a quote in
  JSX text (<p>We're open</p>) is read as the start of a string. Quotes in
  JavaScript cannot span lines, so the blanking stops at the end of that line
  and the next line is scanned normally; at worst the rest of that one line
  is not checked.

Suppressing a finding
  Put `# sast: ignore[rule-id] why this is safe` (Python) or
  `// sast: ignore[rule-id] why this is safe` (JavaScript) on the line the
  finding is reported on. The reason is mandatory. An ignore with no reason, an
  unknown rule id, or one that silences nothing is itself a finding, and those
  cannot be suppressed. An ignore names its rules, so it never hides another.

Standard library only: the scanner must run before anything is installed.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

# --- Rule ids. Stable: they appear in ignore comments and in CI history. -----

SQL_FROM_STRINGS = "py-sql-from-strings"
EVAL_EXEC = "py-eval-exec"
SHELL_TRUE = "py-shell-true"
UNSAFE_DESERIALIZATION = "py-unsafe-deserialization"
WEAK_HASH = "py-weak-hash"
HARDCODED_SECRET = "py-hardcoded-secret"
DEBUG_ENABLED = "py-debug-enabled"
REQUEST_WITHOUT_TIMEOUT = "py-request-without-timeout"
JS_DANGEROUSLY_SET_INNER_HTML = "js-dangerously-set-inner-html"
JS_INNER_HTML = "js-inner-html"
JS_EVAL = "js-eval"

# Findings about the scan itself. These can never be suppressed.
PARSE_ERROR = "sast-parse-error"
IGNORE_WITHOUT_REASON = "sast-ignore-without-reason"
IGNORE_UNKNOWN_RULE = "sast-ignore-unknown-rule"
IGNORE_UNUSED = "sast-ignore-unused"
META_RULES = frozenset({PARSE_ERROR, IGNORE_WITHOUT_REASON, IGNORE_UNKNOWN_RULE, IGNORE_UNUSED})

# Directories never scanned when a directory is walked: installed packages,
# caches, build output and Git's own files. Named files are always scanned.
BUILTIN_EXCLUDES = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", "dist"})
PYTHON_SUFFIXES = frozenset({".py"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_TOOL_ERROR = 2


@dataclass(frozen=True, order=True)
class Finding:
    """One problem at one place. Ordered by path, line, rule: the output order."""

    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} {self.rule} {self.message}"


@dataclass(frozen=True)
class Hit:
    """What a rule reports: the line and why. The scanner adds the path."""

    line: int
    message: str


class ScanError(Exception):
    """The scanner cannot do its job (missing path, unreadable file): exit 2."""


# --- What the walker knows while it walks a Python file -----------------------


@dataclass
class _Scope:
    # Variables that hold a string built from pieces (f-string with values,
    # %, .format(), + with a non-constant). Once built, always suspect.
    built: set[str] = field(default_factory=set)
    # Variables that have only ever held constant strings.
    constant: set[str] = field(default_factory=set)


class PythonContext:
    """Facts gathered during the single walk: imports and string variables.

    Order matters and is the order of the source: an import or assignment is
    known from the line it appears on. That is how Python itself runs the
    module, and it keeps the scan to one pass.
    """

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}
        self._scopes: list[_Scope] = [_Scope()]

    # Imports ------------------------------------------------------------

    def record_import(self, node: ast.Import | ast.ImportFrom) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    self._aliases[alias.asname] = alias.name
                else:
                    # `import urllib.request` binds `urllib`.
                    top = alias.name.split(".")[0]
                    self._aliases[top] = top
        elif node.module and node.level == 0:
            for alias in node.names:
                self._aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def qualified_name(self, node: ast.expr) -> str | None:
        """The dotted name a call target refers to, with imports resolved:
        `h.md5` after `import hashlib as h` is "hashlib.md5"; a bare `md5`
        after `from hashlib import md5` is too. None if it is not a plain
        dotted name (a call result, a subscript...)."""
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(self._aliases.get(node.id, node.id))
        return ".".join(reversed(parts))

    # String variables ---------------------------------------------------

    def push_scope(self) -> None:
        self._scopes.append(_Scope())

    def pop_scope(self) -> None:
        self._scopes.pop()

    def record_assignment(self, name: str, value: ast.expr, augmented: bool = False) -> None:
        scope = self._scopes[-1]
        if self.is_built_string(value) or (augmented and not self.is_constant_string(value)):
            scope.built.add(name)
            scope.constant.discard(name)
        elif self.is_constant_string(value) and name not in scope.built:
            scope.constant.add(name)
        elif not augmented:
            # Reassigned to something we cannot judge: forget what we knew,
            # unless it was ever built (suspicion is never forgotten).
            scope.constant.discard(name)

    def _lookup(self, name: str) -> str | None:
        for scope in reversed(self._scopes):
            if name in scope.built:
                return "built"
            if name in scope.constant:
                return "constant"
        return None

    def is_constant_string(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str)
        if isinstance(node, ast.JoinedStr):
            return not any(isinstance(v, ast.FormattedValue) for v in node.values)
        if isinstance(node, ast.Name):
            return self._lookup(node.id) == "constant"
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.is_constant_string(node.left) and self.is_constant_string(node.right)
        return False

    def _is_stringy(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return self._lookup(node.id) is not None
        return self.is_constant_string(node) or self.is_built_string(node)

    def is_built_string(self, node: ast.expr) -> bool:
        """True for a string assembled at run time from pieces."""
        if isinstance(node, ast.JoinedStr):
            return any(isinstance(v, ast.FormattedValue) for v in node.values)
        if isinstance(node, ast.Name):
            return self._lookup(node.id) == "built"
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Mod):
                return self._is_stringy(node.left)
            if isinstance(node.op, ast.Add):
                either_is_string = self._is_stringy(node.left) or self._is_stringy(node.right)
                return either_is_string and not self.is_constant_string(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            return self._is_stringy(node.func.value)
        return False


# --- Python rules ----------------------------------------------------------


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    return next((k for k in call.keywords if k.arg == name), None)


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


class PythonRule:
    """A rule: an id, what it checks, the node types it wants, and a check.
    Subclasses only override `check`; the walker does the walking."""

    id: ClassVar[str]
    description: ClassVar[str]
    node_types: ClassVar[tuple[type[ast.AST], ...]]

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:  # pragma: no cover - every rule overrides it
        raise NotImplementedError


class SqlFromStrings(PythonRule):
    id = SQL_FROM_STRINGS
    description = "SQL passed to execute()/executemany() is built with f-strings, %, .format() or +"
    node_types = (ast.Call,)
    _methods = frozenset({"execute", "executemany"})
    _sql_keywords = ("sql", "query", "operation", "statement")

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        assert isinstance(node, ast.Call)
        if not (isinstance(node.func, ast.Attribute) and node.func.attr in self._methods):
            return
        sql = node.args[0] if node.args else None
        if sql is None:
            sql = next((k.value for k in node.keywords if k.arg in self._sql_keywords), None)
        if sql is not None and ctx.is_built_string(sql):
            yield Hit(
                node.lineno,
                f"SQL built from strings passed to {node.func.attr}(); "
                "use %s placeholders and pass the values separately",
            )


class EvalExec(PythonRule):
    id = EVAL_EXEC
    description = "eval() or exec() runs a string as code"
    node_types = (ast.Call,)
    _names = frozenset({"eval", "exec", "builtins.eval", "builtins.exec"})

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        assert isinstance(node, ast.Call)
        name = ctx.qualified_name(node.func)
        if name in self._names:
            yield Hit(node.lineno, f"{name.split('.')[-1]}() runs a string as code")


class ShellTrue(PythonRule):
    id = SHELL_TRUE
    description = "a command run through the shell (subprocess shell=True, os.system, os.popen)"
    node_types = (ast.Call,)
    _subprocess = frozenset(
        {
            "subprocess.run",
            "subprocess.call",
            "subprocess.check_call",
            "subprocess.check_output",
            "subprocess.Popen",
        }
    )
    # These always go through the shell; there is no shell=False version.
    _always_shell = frozenset({"os.system", "os.popen", "subprocess.getoutput", "subprocess.getstatusoutput"})

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        assert isinstance(node, ast.Call)
        name = ctx.qualified_name(node.func)
        if name in self._always_shell:
            yield Hit(
                node.lineno,
                f"{name}() runs its command through the shell; use subprocess.run([...]) with a list",
            )
        elif name in self._subprocess:
            shell = _keyword(node, "shell")
            # Anything but a literal False is treated as True: shell=flag
            # might be True at run time.
            if shell is not None and not (isinstance(shell.value, ast.Constant) and shell.value.value is False):
                yield Hit(
                    node.lineno,
                    f"{name}() with shell=True; pass the command as a list instead",
                )


class UnsafeDeserialization(PythonRule):
    id = UNSAFE_DESERIALIZATION
    description = "pickle loading, or yaml.load without SafeLoader: both can run code from the data"
    node_types = (ast.Call,)
    _pickle = frozenset({"pickle.load", "pickle.loads", "pickle.Unpickler"})
    _yaml_unsafe = frozenset({"yaml.unsafe_load", "yaml.unsafe_load_all"})
    _yaml_load = frozenset({"yaml.load", "yaml.load_all"})
    _safe_loaders = frozenset({"yaml.SafeLoader", "yaml.CSafeLoader"})

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        assert isinstance(node, ast.Call)
        name = ctx.qualified_name(node.func)
        if name in self._pickle:
            yield Hit(
                node.lineno,
                f"{name}() can run code hidden in the data; use JSON for anything not ours",
            )
        elif name in self._yaml_unsafe:
            yield Hit(
                node.lineno,
                f"{name}() can run code hidden in the data; use yaml.safe_load",
            )
        elif name in self._yaml_load:
            loader = _keyword(node, "Loader")
            loader_node = loader.value if loader else (node.args[1] if len(node.args) > 1 else None)
            if loader_node is None or ctx.qualified_name(loader_node) not in self._safe_loaders:
                yield Hit(
                    node.lineno,
                    f"{name}() without SafeLoader can run code; use yaml.safe_load",
                )


class WeakHash(PythonRule):
    id = WEAK_HASH
    description = "MD5 or SHA-1, which are broken for security uses"
    node_types = (ast.Call,)
    _weak = frozenset({"md5", "sha1"})

    # usedforsecurity=False is deliberately NOT accepted as an excuse: the
    # rule flags it too, and a genuine non-security use (a checksum) is
    # suppressed with an ignore comment that says so. Decided 2026-11-25.
    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        assert isinstance(node, ast.Call)
        name = ctx.qualified_name(node.func)
        algorithm = None
        if name in {f"hashlib.{a}" for a in self._weak}:
            algorithm = name.split(".")[1]
        elif name == "hashlib.new":
            arg = node.args[0] if node.args else getattr(_keyword(node, "name"), "value", None)
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.lower() in self._weak:
                algorithm = arg.value.lower()
        if algorithm:
            yield Hit(
                node.lineno,
                f"{algorithm.upper()} is broken for security uses; use hashlib.sha256 or stronger",
            )


class HardcodedSecret(PythonRule):
    """A secret written into the source.

    The heuristic, kept simple on purpose:
      - the target's name (variable, attribute, dict key or keyword argument)
        contains password, passwd, secret, token, api_key, apikey,
        private_key or signing_key, ignoring case;
      - the value is a non-empty string literal.
    Not flagged: lookups (os.environ[...], os.getenv(...), anything not a
    literal), empty strings, placeholders (changeme, example, <...>, ${...},
    only x/*/./-/_ characters), and values that are themselves the NAME of a
    setting in capitals, like TOKEN_ENV = "TOKEN_SIGNING_KEY".
    """

    id = HARDCODED_SECRET
    description = "a password, secret, token or API key written into the source"
    node_types = (ast.Assign, ast.AnnAssign, ast.keyword, ast.Dict)
    _name = re.compile(
        r"password|passwd|secret|token|api_?key|private_?key|signing_?key",
        re.IGNORECASE,
    )
    _placeholders = frozenset(
        {
            "changeme",
            "change-me",
            "change_me",
            "placeholder",
            "example",
            "dummy",
            "todo",
            "none",
            "null",
            "secret",
        }
    )
    _placeholder_shape = re.compile(r"^(<[^>]*>|\$\{[^}]*\}|[x*._\-]+)$", re.IGNORECASE)
    _setting_name = re.compile(r"^[A-Z][A-Z0-9_]*$")

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        for name, value, line in self._pairs(node):
            if self._name.search(name) and self._is_secret_literal(value):
                yield Hit(
                    line,
                    f"'{name}' is set to a string literal; read it from the environment instead",
                )

    @staticmethod
    def _pairs(node: ast.AST) -> Iterator[tuple[str, ast.expr, int]]:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if name := _target_name(target):
                    yield name, node.value, node.lineno
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if name := _target_name(node.target):
                yield name, node.value, node.lineno
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.arg, node.value, node.value.lineno
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    yield key.value, value, key.lineno

    def _is_secret_literal(self, value: ast.expr) -> bool:
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            return False
        text = value.value.strip()
        return bool(
            text
            and text.lower() not in self._placeholders
            and not self._placeholder_shape.match(text)
            and not self._setting_name.match(text)
        )


def _target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
        key = target.slice.value
        return key if isinstance(key, str) else None
    return None


class DebugEnabled(PythonRule):
    id = DEBUG_ENABLED
    description = "debug mode switched on (Flask run(debug=True), app.debug = True, DEBUG = True)"
    node_types = (ast.Call, ast.Assign)

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        message = "debug mode shows stack traces and an interactive console to anyone who triggers an error"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # app.run(debug=True), app.config.update(DEBUG=True)
            if node.func.attr in {"run", "update"}:
                for kw in node.keywords:
                    if kw.arg in {"debug", "DEBUG"} and _is_true(kw.value):
                        yield Hit(node.lineno, message)
        elif isinstance(node, ast.Assign) and _is_true(node.value):
            # app.debug = True, app.config["DEBUG"] = True, DEBUG = True
            for target in node.targets:
                if _target_name(target) in {"debug", "DEBUG"}:
                    yield Hit(node.lineno, message)


_HTTP_VERBS = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "request",
    "stream",
)
_HTTP_CALLS = frozenset(
    {f"{lib}.{verb}" for lib in ("requests", "httpx") for verb in _HTTP_VERBS} | {"urllib.request.urlopen"}
)


class RequestWithoutTimeout(PythonRule):
    """Module-level calls only: requests.get(...), httpx.post(...),
    urlopen(...). A call on a session or client object (session.get(...)) is
    not resolved to its library, so it is not checked; set the timeout on the
    client when it is built."""

    id = REQUEST_WITHOUT_TIMEOUT
    description = "an HTTP call without a timeout, which can hang a worker forever"
    node_types = (ast.Call,)
    _calls = _HTTP_CALLS

    def check(self, node: ast.AST, ctx: PythonContext) -> Iterator[Hit]:
        assert isinstance(node, ast.Call)
        name = ctx.qualified_name(node.func)
        if name not in self._calls or _keyword(node, "timeout") is not None:
            return
        # urlopen(url, data, timeout): the timeout may be the third argument.
        if name == "urllib.request.urlopen" and len(node.args) >= 3:
            return
        yield Hit(node.lineno, f"{name}() without a timeout can wait forever; pass timeout=")


PYTHON_RULES: tuple[PythonRule, ...] = (
    SqlFromStrings(),
    EvalExec(),
    ShellTrue(),
    UnsafeDeserialization(),
    WeakHash(),
    HardcodedSecret(),
    DebugEnabled(),
    RequestWithoutTimeout(),
)


class _Walker:
    """Walks a tree once and hands each node to the rules that want its type."""

    _scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def __init__(self, rules: Sequence[PythonRule]) -> None:
        self._by_type: dict[type[ast.AST], list[PythonRule]] = {}
        for rule in rules:
            for node_type in rule.node_types:
                self._by_type.setdefault(node_type, []).append(rule)

    def run(self, tree: ast.AST) -> list[tuple[str, Hit]]:
        ctx = PythonContext()
        hits: list[tuple[str, Hit]] = []
        self._visit(tree, ctx, hits)
        return hits

    def _visit(self, node: ast.AST, ctx: PythonContext, hits: list[tuple[str, Hit]]) -> None:
        new_scope = isinstance(node, self._scopes)
        if new_scope:
            ctx.push_scope()
        for rule in self._by_type.get(type(node), ()):
            hits.extend((rule.id, hit) for hit in rule.check(node, ctx))
        for child in ast.iter_child_nodes(node):
            self._visit(child, ctx, hits)
        # Recorded after the children, so `sql = sql + x` is judged on the
        # old value of sql, as Python evaluates it.
        self._record(node, ctx)
        if new_scope:
            ctx.pop_scope()

    @staticmethod
    def _record(node: ast.AST, ctx: PythonContext) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            ctx.record_import(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    ctx.record_assignment(target.id, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            ctx.record_assignment(node.target.id, node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.op, ast.Add):
                ctx.record_assignment(node.target.id, node.value, augmented=True)
            elif isinstance(node.op, ast.Mod):
                ctx.record_assignment(node.target.id, ast.BinOp(node.target, ast.Mod(), node.value))


# --- JavaScript rules ---------------------------------------------------------


@dataclass(frozen=True)
class JsRule:
    """A JavaScript rule: a regular expression run on the blanked code."""

    id: str
    description: str
    pattern: re.Pattern[str]
    message: str

    def check(self, code_lines: Sequence[str]) -> Iterator[Hit]:
        for number, line in enumerate(code_lines, start=1):
            if self.pattern.search(line):
                yield Hit(number, self.message)


JS_RULES: tuple[JsRule, ...] = (
    JsRule(
        JS_DANGEROUSLY_SET_INNER_HTML,
        "React's dangerouslySetInnerHTML inserts raw HTML",
        re.compile(r"\bdangerouslySetInnerHTML\b"),
        "dangerouslySetInnerHTML inserts raw HTML; render text or sanitise first",
    ),
    JsRule(
        JS_INNER_HTML,
        "assigning innerHTML/outerHTML or calling insertAdjacentHTML inserts raw HTML",
        # `=` or `+=` but not `==`/`===`: reading or comparing is harmless.
        re.compile(r"\.(?:innerHTML|outerHTML)\s*\+?=(?!=)|\.insertAdjacentHTML\s*\("),
        "raw HTML written into the page; use textContent or build elements",
    ),
    JsRule(
        JS_EVAL,
        "eval() runs a string as code",
        # Not preceded by a word character, $ or ".": so `medieval(` and
        # `obj.eval(` do not match.
        re.compile(r"(?<![\w$.])eval\s*\("),
        "eval() runs a string as code",
    ),
)


def blank_js(source: str) -> tuple[list[str], dict[int, str]]:
    """Split JavaScript into code and comments.

    Returns the code lines with every comment and the inside of every string
    replaced by spaces (so line and column numbers stay put), and the text of
    the comments by line number, where ignore comments are looked for.
    Template literals keep their ${...} parts as code, since that is code.
    """
    out: list[str] = []
    comments: dict[int, str] = {}
    line = 1
    i = 0
    n = len(source)
    # A stack of what we are inside: "code", "tpl" (template literal text).
    # Each "${" inside a template pushes "code"; its "}" pops back.
    stack: list[str] = ["code"]
    brace_depth: list[int] = [0]

    def emit(ch: str) -> None:
        out.append(ch)

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        state = stack[-1]
        if ch == "\n":
            emit("\n")
            line += 1
            i += 1
            continue
        if state == "tpl":
            if ch == "\\":
                emit(" ")
                if nxt and nxt != "\n":
                    emit(" ")
                i += 2 if nxt and nxt != "\n" else 1
            elif ch == "`":
                emit("`")
                stack.pop()
                i += 1
            elif ch == "$" and nxt == "{":
                emit("${")
                stack.append("code")
                brace_depth.append(0)
                i += 2
            else:
                emit(" ")
                i += 1
            continue
        # state == "code"
        if ch == "/" and nxt == "/":
            end = source.find("\n", i)
            end = n if end == -1 else end
            comments[line] = comments.get(line, "") + source[i + 2 : end]
            out.append(" " * (end - i))
            i = end
        elif ch == "/" and nxt == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for c in source[i:end]:
                if c == "\n":
                    emit("\n")
                    line += 1
                else:
                    emit(" ")
            i = end
        elif ch in "'\"":
            emit(ch)
            i += 1
            # A quoted string ends at its closing quote or, unclosed, at the
            # end of the line (JavaScript strings cannot span lines; this is
            # also what contains the damage of an apostrophe in JSX text).
            while i < n and source[i] not in (ch, "\n"):
                if source[i] == "\\" and i + 1 < n and source[i + 1] != "\n":
                    emit("  ")
                    i += 2
                else:
                    emit(" ")
                    i += 1
            if i < n and source[i] == ch:
                emit(ch)
                i += 1
        elif ch == "`":
            emit("`")
            stack.append("tpl")
            i += 1
        elif ch == "{" and len(stack) > 1:
            brace_depth[-1] += 1
            emit(ch)
            i += 1
        elif ch == "}" and len(stack) > 1:
            if brace_depth[-1] == 0:
                stack.pop()
                brace_depth.pop()
            else:
                brace_depth[-1] -= 1
            emit(ch)
            i += 1
        else:
            emit(ch)
            i += 1
    return "".join(out).split("\n"), comments


# --- Ignore comments ---------------------------------------------------------

_IGNORE = re.compile(r"sast:\s*ignore\[([^\]]*)\](.*)")
KNOWN_RULES = frozenset({r.id for r in PYTHON_RULES} | {r.id for r in JS_RULES})


@dataclass(frozen=True)
class Ignore:
    line: int
    rules: frozenset[str]
    reason: str


def parse_ignores(
    comments: dict[int, str],
) -> tuple[list[Ignore], list[tuple[str, Hit]]]:
    """The ignore comments, and findings for the malformed ones."""
    ignores: list[Ignore] = []
    problems: list[tuple[str, Hit]] = []
    for line, text in sorted(comments.items()):
        match = _IGNORE.search(text)
        if not match:
            continue
        rules = frozenset(r.strip() for r in match.group(1).split(",") if r.strip())
        reason = match.group(2).strip()
        unknown = sorted(r for r in rules if r not in KNOWN_RULES) or ([] if rules else ["(none)"])
        for rule in unknown:
            problems.append((IGNORE_UNKNOWN_RULE, Hit(line, f"ignore names unknown rule {rule!r}")))
        if not re.search(r"\w", reason):
            problems.append(
                (
                    IGNORE_WITHOUT_REASON,
                    Hit(line, "ignore has no reason; say why this is safe"),
                )
            )
        elif not unknown:
            ignores.append(Ignore(line, rules, reason))
    return ignores, problems


def python_comments(source: str) -> dict[int, str]:
    """Comment text by line, from the tokenizer, so a '#' inside a string is
    never mistaken for a comment."""
    comments: dict[int, str] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = token.string[1:]
    return comments


def _apply_ignores(path: str, hits: Iterable[tuple[str, Hit]], comments: dict[int, str]) -> list[Finding]:
    ignores, problems = parse_ignores(comments)
    by_line = {ignore.line: ignore for ignore in ignores}
    used: set[tuple[int, str]] = set()
    findings: list[Finding] = []
    for rule, hit in hits:
        ignore = by_line.get(hit.line)
        if ignore and rule in ignore.rules and rule not in META_RULES:
            used.add((hit.line, rule))
            continue
        findings.append(Finding(path, hit.line, rule, hit.message))
    for ignore in ignores:
        for rule in sorted(ignore.rules):
            if (ignore.line, rule) not in used:
                findings.append(
                    Finding(
                        path,
                        ignore.line,
                        IGNORE_UNUSED,
                        f"ignore[{rule}] silences nothing; remove it",
                    )
                )
    findings.extend(Finding(path, hit.line, rule, hit.message) for rule, hit in problems)
    return findings


# --- Scanning ---------------------------------------------------------------


def scan_python(path: str, source: str, rules: Sequence[PythonRule] = PYTHON_RULES) -> list[Finding]:
    """All findings in one Python file. Never raises for bad source: a file
    that does not parse is a finding, not a silent skip."""
    try:
        tree = ast.parse(source, filename=path)
        comments = python_comments(source)
    except (SyntaxError, tokenize.TokenError, ValueError) as error:
        line = getattr(error, "lineno", None) or 1
        return [
            Finding(
                path,
                line,
                PARSE_ERROR,
                f"could not parse, so nothing in it was checked: {error}",
            )
        ]
    return sorted(_apply_ignores(path, _Walker(rules).run(tree), comments))


def scan_js(path: str, source: str, rules: Sequence[JsRule] = JS_RULES) -> list[Finding]:
    code_lines, comments = blank_js(source)
    hits = [(rule.id, hit) for rule in rules for hit in rule.check(code_lines)]
    return sorted(_apply_ignores(path, hits, comments))


def collect_files(paths: Sequence[Path], excludes: frozenset[str]) -> list[Path]:
    """The files to scan. A named file is always scanned; directories are
    walked, skipping excluded directory names. A missing path is an error."""
    found: set[Path] = set()
    suffixes = PYTHON_SUFFIXES | JS_SUFFIXES
    for path in paths:
        if path.is_file():
            found.add(path)
        elif path.is_dir():
            for candidate in path.rglob("*"):
                relative_parts = candidate.relative_to(path).parts[:-1]
                if candidate.suffix in suffixes and candidate.is_file() and not excludes.intersection(relative_parts):
                    found.add(candidate)
        else:
            raise ScanError(f"no such file or directory: {path}")
    return sorted(found)


def scan_paths(
    paths: Sequence[Path],
    excludes: frozenset[str] = BUILTIN_EXCLUDES,
    read_text: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8"),
) -> list[Finding]:
    findings: list[Finding] = []
    for file in collect_files(paths, excludes):
        display = file.as_posix()
        try:
            source = read_text(file)
        except UnicodeDecodeError as error:
            findings.append(
                Finding(
                    display,
                    1,
                    PARSE_ERROR,
                    f"not valid UTF-8, so nothing in it was checked: {error}",
                )
            )
            continue
        except OSError as error:
            raise ScanError(f"cannot read {display}: {error}") from error
        scan = scan_python if file.suffix in PYTHON_SUFFIXES else scan_js
        findings.extend(scan(display, source))
    return sorted(findings)


def describe_rules() -> str:
    lines = [f"{rule.id:32} {rule.description}" for rule in (*PYTHON_RULES, *JS_RULES)]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hand-written SAST for this repository.",
        epilog=f"Always skipped when walking directories: {', '.join(sorted(BUILTIN_EXCLUDES))}.",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="files or directories to scan")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="DIR",
        help="also skip directories with this name (repeatable)",
    )
    parser.add_argument("--list-rules", action="store_true", help="print the rules and exit")
    args = parser.parse_args(argv)
    if args.list_rules:
        print(describe_rules())
        return EXIT_CLEAN
    if not args.paths:
        parser.error("give at least one file or directory")
    try:
        findings = scan_paths(args.paths, BUILTIN_EXCLUDES | frozenset(args.exclude))
    except ScanError as error:
        print(f"sast: error: {error}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    for finding in findings:
        print(finding)
    print(f"sast: {len(findings)} finding(s)", file=sys.stderr)
    return EXIT_FINDINGS if findings else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
