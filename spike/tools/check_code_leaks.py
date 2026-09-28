"""Scan code (not prose) for the benchmark's own answer key.

Walks a directory tree (default spike/system, excluding node_modules,
.venv, __pycache__ and .git) over .py and .ts files, extracts every
docstring and comment, and flags three kinds of leak against
truth/facts.yaml:

  - a literal fact id (`F-123`) anywhere in the text;
  - a comment/docstring (or one of its sentences) whose first eight
    normalised words match a statement's first eight normalised words;
  - a comment/docstring (or one of its sentences) that scores >= 0.5 on
    difflib.SequenceMatcher against a statement, normalised (lower-case,
    punctuation stripped, whitespace collapsed).

Python extraction: module/class/function docstrings via ast.get_docstring,
plus `#` comments via tokenize (so a `#` inside a string literal is never
mistaken for one). TypeScript extraction: a small character scanner picks
out `//` line comments and `/* */` block comments while tracking whether
it is inside a '...', "..." or `...` string, so a `//` in a URL or a `/*`
in a template literal is never mistaken for a comment start -- good enough
for a leak scan, not a real TS parser (it does not walk `${...}`
interpolation inside template literals as a nested expression).

Run: cd spike && uv run --with pyyaml python tools/check_code_leaks.py
     [--root DIR] [--ext .py,.ts] [--facts PATH]

Exits non-zero if any hit is found.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent

FACT_ID_RE = re.compile(r"F-\d{3}")
PUNCT_RE = re.compile(r"[^a-z0-9\s]")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
PREFIX_WORDS = 8
SIMILARITY_THRESHOLD = 0.5


def normalize(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = PUNCT_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def sentences_of(text: str) -> list[str]:
    """The whole text as one unit, plus each `.`/`!`/`?`-delimited sentence
    within it -- a leak can be the entire comment or just one sentence of
    a longer docstring."""
    whole = text.strip()
    if not whole:
        return []
    parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(whole) if s.strip()]
    units = [whole]
    units.extend(p for p in parts if p != whole)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    out = []
    for u in units:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


@dataclass(frozen=True)
class TextBlock:
    path: Path
    line: int
    kind: str  # "docstring" | "comment"
    text: str


def python_blocks(path: Path) -> list[TextBlock]:
    source = path.read_text()
    blocks: list[TextBlock] = []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        tree = None

    if tree is not None:
        seen_doc_ids: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                doc = ast.get_docstring(node, clean=True)
                if doc:
                    line = getattr(node, "lineno", 1)
                    blocks.append(TextBlock(path, line, "docstring", doc))
                    body = getattr(node, "body", [])
                    if body and isinstance(body[0], ast.Expr):
                        seen_doc_ids.add(id(body[0]))
        # A bare string literal statement is also used, by convention, as a
        # trailing "docstring" for the assignment right above it (module- or
        # class-level constants); ast.get_docstring only catches the first
        # statement of a block, so pick up every other one directly.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and id(node) not in seen_doc_ids
            ):
                text = node.value.value.strip()
                if text:
                    blocks.append(TextBlock(path, node.lineno, "docstring", text))

    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                text = tok.string.lstrip("#").strip()
                if text:
                    blocks.append(TextBlock(path, tok.start[0], "comment", text))
    except tokenize.TokenizeError:
        pass

    return blocks


QUOTE_CHARS = ("'", '"', "`")


def _clean_block_comment(text: str) -> str:
    text = text.strip(" *\n\t")
    return re.sub(r"\n\s*\*\s?", " ", text).strip()


def typescript_blocks(path: Path) -> list[TextBlock]:  # noqa: C901
    """Scan `source` one character at a time, tracking whether the cursor
    sits inside a string/template literal, so `//` or `/*` appearing
    inside one (a URL, for instance) is never read as a comment start."""
    source = path.read_text()
    blocks: list[TextBlock] = []
    n = len(source)
    i = 0
    line = 1
    state = "normal"  # "normal" | one of QUOTE_CHARS | "line" | "block"
    start = 0
    start_line = 1

    while i < n:
        c = source[i]
        if state == "normal":
            if c in QUOTE_CHARS:
                state = c
                i += 1
            elif source[i : i + 2] == "//":
                state = "line"
                start, start_line = i + 2, line
                i += 2
            elif source[i : i + 2] == "/*":
                state = "block"
                start, start_line = i + 2, line
                i += 2
            else:
                i += 1
        elif state in QUOTE_CHARS:
            if c == "\\":
                i += 2
                continue
            if c == state:
                state = "normal"
            i += 1
        elif state == "line":
            if c == "\n":
                text = source[start:i].strip()
                if text:
                    blocks.append(TextBlock(path, start_line, "comment", text))
                state = "normal"
            i += 1
        elif state == "block":
            if source[i : i + 2] == "*/":
                text = _clean_block_comment(source[start:i])
                if text:
                    blocks.append(TextBlock(path, start_line, "comment", text))
                state = "normal"
                i += 2
                continue
            i += 1
        if c == "\n":
            line += 1

    if state == "line":
        text = source[start:].strip()
        if text:
            blocks.append(TextBlock(path, start_line, "comment", text))
    return blocks


def extract_blocks(path: Path) -> list[TextBlock]:
    if path.suffix == ".py":
        return python_blocks(path)
    if path.suffix == ".ts":
        return typescript_blocks(path)
    return []


EXCLUDED_DIRS = {"node_modules", ".venv", "__pycache__", ".git"}


def find_files(root: Path, exts: set[str]) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in exts:
            continue
        if EXCLUDED_DIRS & set(path.parts):
            continue
        files.append(path)
    return files


@dataclass(frozen=True)
class Hit:
    path: Path
    line: int
    kind: str
    reason: str
    fact_id: str
    snippet: str


def scan(
    files: list[Path], facts_norm: dict[str, str], facts_first8: dict[str, tuple[str, ...]]
) -> list[Hit]:
    hits: list[Hit] = []
    for path in files:
        for block in extract_blocks(path):
            if FACT_ID_RE.search(block.text):
                hits.append(Hit(path, block.line, block.kind, "fact id", "", block.text[:80]))
                continue
            for unit in sentences_of(block.text):
                norm = normalize(unit)
                if not norm:
                    continue
                words = tuple(norm.split())
                hit = None
                if len(words) >= PREFIX_WORDS:
                    prefix = words[:PREFIX_WORDS]
                    for fid, stmt_prefix in facts_first8.items():
                        if prefix == stmt_prefix:
                            hit = ("8-word prefix", fid)
                            break
                if hit is None:
                    for fid, stmt_norm in facts_norm.items():
                        ratio = difflib.SequenceMatcher(None, norm, stmt_norm).ratio()
                        if ratio >= SIMILARITY_THRESHOLD:
                            hit = (f"similarity {ratio:.2f}", fid)
                            break
                if hit is not None:
                    reason, fid = hit
                    hits.append(Hit(path, block.line, block.kind, reason, fid, unit[:80]))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(SPIKE / "system"), help="directory to scan")
    parser.add_argument("--ext", default=".py,.ts", help="comma-separated extensions")
    parser.add_argument("--facts", default=str(SPIKE / "truth/facts.yaml"), help="facts.yaml path")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    exts = {e if e.startswith(".") else f".{e}" for e in args.ext.split(",")}
    facts = yaml.safe_load(Path(args.facts).read_text())
    facts_norm = {f["id"]: normalize(f["statement"]) for f in facts}
    facts_first8 = {
        fid: tuple(norm.split()[:PREFIX_WORDS])
        for fid, norm in facts_norm.items()
        if len(norm.split()) >= PREFIX_WORDS
    }

    files = find_files(root, exts)
    hits = scan(files, facts_norm, facts_first8)

    for h in hits:
        rel = h.path.relative_to(SPIKE) if SPIKE in h.path.parents else h.path
        fid_part = f" ({h.fact_id})" if h.fact_id else ""
        print(f"  HIT {rel}:{h.line} [{h.kind}] {h.reason}{fid_part}: {h.snippet!r}")

    print(f"files scanned: {len(files)}")
    print(f"hits: {len(hits)}")
    if hits:
        return 1
    print("OK: zero leaks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
