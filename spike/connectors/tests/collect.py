"""Static test collection: one skeleton per test, no pytest/Vitest process.

Python: walks ``tests/**/test_*.py`` with ``ast`` (never imports or runs the
test files) and produces a ``Skeleton`` per ``test_*`` function — node id,
file, line, docstring, markers (``skip``/``xfail``/``parametrize``, with a
reason or the parametrize ids), the function's own parameters (a proxy for
fixtures used — pytest fixtures and test parameters share the same syntax
position, and telling them apart needs the fixture *definitions*, out of
scope for a per-file AST walk), the module-level imports, every function/
method name called in the body, every ``UPPER_CASE``-looking name referenced,
and every ``assert`` statement (its source text, and — when it's a single
comparison — the left/right operand source and, when either operand is a
literal constant, its parsed value). A ``@pytest.mark.parametrize`` function
yields one ``Skeleton`` per case, ``node_id`` suffixed ``[id]``; the id comes
from ``ids=[...]`` when given, else an approximation of pytest's own
auto-generated id (joining each argument's own repr with ``-``) — this is
NOT guaranteed to match pytest's exact algorithm for every value type;
``cross_check`` reconciles against real ``pytest --collect-only -q`` output
when given.

TypeScript (Vitest): a small, deliberately tolerant line-based scanner over
``dispatch/test/*.test.ts`` — no tree-sitter, per the driving issue. Tracks
brace depth to know which ``it``/``test`` block is currently open and which
``describe`` blocks enclose it (``ancestorTitles``), collecting every line
that contains ``expect(`` inside the current ``it`` (only that line, not a
multi-line call's continuation — a real limitation of a line-based scanner,
accepted for a first cut) plus every other line in the block, from which
calls and constants are approximated the same way. It does not track string
or template-literal contents, so a brace inside one can misdirect the depth
counter on unusual files; the fixture's own test files do not hit this.

Both ``collect_from_path`` (a real, already-materialised directory) and
``collect_from_timeline`` (materialises one step of a
``bench.build.Timeline`` into a temp directory first, so nothing needs a
git checkout to be collected) return the same ``list[Skeleton]`` shape.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- data model


@dataclass(frozen=True)
class AssertExpr:
    source: str
    op: str | None = None
    left: str | None = None
    right: str | None = None
    left_literal: Any = None
    right_literal: Any = None


@dataclass(frozen=True)
class Skeleton:
    node_id: str
    file: str
    line: int
    name: str
    language: str  # "python" | "typescript"
    docstring: str | None = None
    markers: tuple[str, ...] = ()
    parametrize_id: str | None = None
    fixtures: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    constants: tuple[str, ...] = ()
    asserts: tuple[AssertExpr, ...] = field(default_factory=tuple)


# -------------------------------------------------------------- Python: ast

_OP_MAP = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.In: "in",
    ast.NotIn: "not in",
}


def _literal(node: ast.expr) -> tuple[bool, Any]:
    """(True, value) if `node` is a literal — a Constant, a negated
    Constant, or a simple wrapper call like Decimal("0.15")/Decimal(3) —
    else (False, None)."""
    if isinstance(node, ast.Constant):
        return True, node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        is_lit, val = _literal(node.operand)
        return (True, -val) if is_lit else (False, None)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.args:
        if isinstance(node.args[0], ast.Constant):
            return True, node.args[0].value
    return False, None


def _assert_expr(node: ast.Assert) -> AssertExpr:
    source = ast.unparse(node.test)
    test = node.test
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        op = _OP_MAP.get(type(test.ops[0]))
        left_is_lit, left_val = _literal(test.left)
        right_is_lit, right_val = _literal(test.comparators[0])
        return AssertExpr(
            source=source,
            op=op,
            left=ast.unparse(test.left),
            right=ast.unparse(test.comparators[0]),
            left_literal=left_val if left_is_lit else None,
            right_literal=right_val if right_is_lit else None,
        )
    return AssertExpr(source=source)


def _names_used(body: list[ast.stmt]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    calls: set[str] = set()
    constants: set[str] = set()
    wrapper = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(wrapper):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.add(func.id)
            elif isinstance(func, ast.Attribute):
                calls.add(func.attr)
        elif isinstance(node, ast.Name) and len(node.id) > 1 and node.id.upper() == node.id:
            constants.add(node.id)
    return tuple(sorted(calls)), tuple(sorted(constants))


def _decorator_name_and_call(dec: ast.expr) -> tuple[str, ast.Call | None]:
    call = None
    node = dec
    if isinstance(node, ast.Call):
        call, node = node, node.func
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts)), call


def _kw_value(call: ast.Call, name: str) -> Any:
    for kw in call.keywords:
        if kw.arg == name:
            try:
                return ast.literal_eval(kw.value)
            except (ValueError, TypeError):
                return None
    return None


def _approximate_param_id(node: ast.expr) -> str:
    """Best-effort approximation of pytest's own auto-generated parametrize
    id (see the module docstring's caveat)."""
    if isinstance(node, ast.Tuple):
        return "-".join(_approximate_param_id(e) for e in node.elts)
    literal, value = _literal(node)
    if literal:
        if isinstance(value, bool):
            return str(value)
        return str(value)
    return ast.unparse(node)


def _parametrize_cases(call: ast.Call) -> list[ast.expr] | None:
    if len(call.args) < 2:
        return None
    values_node = call.args[1]
    if isinstance(values_node, (ast.List, ast.Tuple)):
        return list(values_node.elts)
    return None


def _function_skeletons(
    func: ast.FunctionDef, rel: str, imports: tuple[str, ...]
) -> list[Skeleton]:
    docstring = ast.get_docstring(func)
    markers: list[str] = []
    parametrize_cases: list[ast.expr] | None = None
    explicit_ids: list[Any] | None = None

    for dec in func.decorator_list:
        name, call = _decorator_name_and_call(dec)
        # `pytest.mark.unit` is 3 dotted segments (pytest, mark, unit): the
        # mark's own name is whatever follows the LAST "mark." — not
        # `name.startswith("mark.")`, which never matches the "pytest."
        # prefix real decorators carry.
        if ".mark." not in f".{name}":
            continue
        mark_name = name.rsplit("mark.", 1)[1]
        if mark_name == "parametrize" and call is not None:
            parametrize_cases = _parametrize_cases(call)
            ids = _kw_value(call, "ids")
            explicit_ids = list(ids) if isinstance(ids, (list, tuple)) else None
            markers.append("parametrize")
            continue
        reason = _kw_value(call, "reason") if call is not None else None
        markers.append(f"{mark_name}:{reason}" if reason else mark_name)

    fixtures = tuple(a.arg for a in func.args.args if a.arg != "self")
    calls, constants = _names_used(func.body)
    asserts = tuple(_assert_expr(n) for n in ast.walk(func) if isinstance(n, ast.Assert))
    base_id = f"{rel}::{func.name}"

    common = dict(
        file=rel,
        line=func.lineno,
        name=func.name,
        language="python",
        docstring=docstring,
        markers=tuple(markers),
        fixtures=fixtures,
        imports=imports,
        calls=calls,
        constants=constants,
        asserts=asserts,
    )

    if parametrize_cases is None:
        return [Skeleton(node_id=base_id, **common)]

    skeletons = []
    for i, case in enumerate(parametrize_cases):
        param_id = (
            str(explicit_ids[i])
            if explicit_ids is not None and i < len(explicit_ids)
            else _approximate_param_id(case)
        )
        skeletons.append(
            Skeleton(node_id=f"{base_id}[{param_id}]", parametrize_id=param_id, **common)
        )
    return skeletons


def _module_imports(tree: ast.Module) -> tuple[str, ...]:
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    return tuple(imports)


def _python_file_skeletons(path: Path, rel: str) -> list[Skeleton]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports = _module_imports(tree)
    skeletons: list[Skeleton] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            skeletons.extend(_function_skeletons(node, rel, imports))
    return skeletons


def collect_python(root: Path) -> list[Skeleton]:
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return []
    skeletons: list[Skeleton] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        skeletons.extend(_python_file_skeletons(path, path.relative_to(root).as_posix()))
    return skeletons


# ---------------------------------------------------- TypeScript: line scan

_BLOCK_START_RE = re.compile(r"\b(describe|it|test)(?:\.\w+)?\(\s*(['\"`])((?:\\.|(?!\2).)*)\2")
_CALL_NAME_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CONST_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_TS_IMPORT_RE = re.compile(r"""^\s*import\s+.*?\s+from\s+["'](.+?)["']""")


def _typescript_file_skeletons(path: Path, rel: str) -> list[Skeleton]:
    lines = path.read_text().splitlines()
    imports = tuple(m.group(1) for m in (_TS_IMPORT_RE.match(line) for line in lines) if m)

    stack: list[dict[str, Any]] = []
    finished: list[dict[str, Any]] = []
    depth = 0

    for lineno, line in enumerate(lines, start=1):
        match = _BLOCK_START_RE.search(line)
        if match:
            kind = "describe" if match.group(1) == "describe" else "it"
            stack.append(
                {"kind": kind, "name": match.group(3), "depth": depth, "line": lineno, "body": []}
            )
        elif stack and stack[-1]["kind"] == "it":
            stack[-1]["body"].append(line)

        depth += line.count("{") - line.count("}")
        while stack and depth <= stack[-1]["depth"]:
            block = stack.pop()
            if block["kind"] == "it":
                ancestors = [b["name"] for b in stack if b["kind"] == "describe"]
                finished.append({**block, "ancestors": ancestors})

    skeletons = []
    for block in finished:
        body_text = "\n".join(block["body"])
        expects = tuple(s.strip() for s in block["body"] if "expect(" in s)
        calls = tuple(sorted(set(_CALL_NAME_RE.findall(body_text)) - {"expect"}))
        constants = tuple(sorted(set(_CONST_NAME_RE.findall(body_text))))
        full_name = " > ".join([*block["ancestors"], block["name"]])
        asserts = tuple(AssertExpr(source=e) for e in expects)
        skeletons.append(
            Skeleton(
                node_id=full_name,
                file=rel,
                line=block["line"],
                name=block["name"],
                language="typescript",
                markers=(),
                imports=imports,
                calls=calls,
                constants=constants,
                asserts=asserts,
            )
        )
    return skeletons


def collect_typescript(root: Path) -> list[Skeleton]:
    test_dir = root / "dispatch" / "test"
    if not test_dir.is_dir():
        return []
    skeletons: list[Skeleton] = []
    for path in sorted(test_dir.glob("*.test.ts")):
        skeletons.extend(_typescript_file_skeletons(path, path.relative_to(root).as_posix()))
    return skeletons


# --------------------------------------------------------------- top level


def collect_from_path(root: Path) -> list[Skeleton]:
    """Collects from a real, already-materialised directory (a checkout, an
    ingest root's `repo/`, or any plain copy of the built system)."""
    return collect_python(root) + collect_typescript(root)


def collect_from_timeline(timeline: Any, step_id: str) -> list[Skeleton]:
    """Materialises `step_id`'s content (via `bench.build.Timeline`, never a
    git checkout) into a temp directory, then collects from it."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for path in timeline.active_paths_at(step_id):
            content = timeline.content_at(path, step_id)
            if content is None:
                continue
            dest = tmp_root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        return collect_from_path(tmp_root)


def cross_check(skeletons: list[Skeleton], collect_only_output: str) -> list[str]:
    """Compares `skeletons`' node ids against real `pytest --collect-only -q`
    output (one node id per line, blank lines and a trailing summary line
    ignored). Returns a list of differences: node ids this collector found
    that pytest didn't, and vice versa — empty means they agree."""
    pytest_ids = {
        line.strip()
        for line in collect_only_output.splitlines()
        if "::" in line and not line.strip().startswith("=")
    }
    ours = {s.node_id for s in skeletons if s.language == "python"}
    diffs = []
    for missing in sorted(ours - pytest_ids):
        diffs.append(f"collected but not in pytest --collect-only: {missing}")
    for missing in sorted(pytest_ids - ours):
        diffs.append(f"in pytest --collect-only but not collected: {missing}")
    return diffs


def run_pytest_collect_only(repo: Path) -> str:
    """Runs `pytest --collect-only -q` for real, for `cross_check`. Not
    called by default anywhere in this package — evidence.py and lift.py
    never run a test process; this exists only as a manual/CI cross-check."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.stdout
