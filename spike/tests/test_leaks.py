"""Fails if any file under the assembled ingest root contains a truth fact id
(``F-\\d{3}``) or the first eight normalised words of any truth statement —
the leak the D-013 panel found (47 of 68 code/executed facts carried their
own answer key in a docstring).

``find_leaks`` is exercised directly with synthetic content (fast,
deterministic, no dependency on the real fixture's state) and, marked
``fixture`` like ``tests/test_fixture.py`` (skips if ``truth/facts.yaml`` is
absent), against the real fixture's own assembled ingest root — this one may
fail until the fixture authors finish scrubbing docstrings; the leak count is
always printed and put in the assertion message, so a red run here is
informative, not just a bare failure.

Statements shorter than eight words are excluded from the snippet check (an
interpretation call: a 3-4 word common phrase risks false positives that a
full eight-word snippet does not); the fact-id check applies to every file
regardless of statement length.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bench.build import Timeline
from bench.run import assemble_ingest_root
from bench.truth import load_truth
from tests._support import SPIKE_ROOT

pytestmark = pytest.mark.fixture

FACTS_PATH = SPIKE_ROOT / "truth" / "facts.yaml"
FACT_ID_RE = re.compile(r"F-\d{3}")
_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    text = text.lower()
    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def _first_n_words(text: str, n: int) -> list[str]:
    return [w for w in _normalize(text).split(" ") if w][:n]


def find_leaks(ingest_root: Path, statements: list[str]) -> list[str]:
    """Returns one "path: reason" string per leak found under `ingest_root`."""
    snippets = {}
    for stmt in statements:
        words = _first_n_words(stmt, 8)
        if len(words) >= 8:
            snippets[stmt] = " ".join(words)

    leaks: list[str] = []
    for path in sorted(ingest_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; nothing to scan as text

        rel = path.relative_to(ingest_root).as_posix()

        fact_id_match = FACT_ID_RE.search(text)
        if fact_id_match:
            leaks.append(f"{rel}: contains fact id {fact_id_match.group(0)!r}")

        normalized_text = _normalize(text)
        for stmt, snippet in snippets.items():
            if snippet in normalized_text:
                leaks.append(f"{rel}: contains the first 8 words of {stmt[:60]!r}")

    return leaks


def test_find_leaks_detects_fact_id_and_statement_snippet(tmp_path: Path):
    ingest_root = tmp_path / "ingest"
    ingest_root.mkdir()
    (ingest_root / "leaky_id.py").write_text("# proves F-042 holds\n")
    (ingest_root / "leaky_statement.py").write_text(
        "# A member's first 30 minutes of every ride are free, always.\n"
    )
    (ingest_root / "clean.py").write_text("# Nothing sensitive here at all.\n")

    statements = ["A member's first 30 minutes of every ride are free."]
    leaks = find_leaks(ingest_root, statements)
    leaked_files = {leak.split(":")[0] for leak in leaks}
    assert "leaky_id.py" in leaked_files
    assert "leaky_statement.py" in leaked_files
    assert "clean.py" not in leaked_files


def test_find_leaks_clean_root_has_no_leaks(tmp_path: Path):
    ingest_root = tmp_path / "ingest"
    ingest_root.mkdir()
    (ingest_root / "clean.py").write_text("def free_minutes(): return 30\n")
    assert find_leaks(ingest_root, ["A member's first 30 minutes of every ride are free."]) == []


def test_find_leaks_short_statement_not_checked_for_snippet(tmp_path: Path):
    ingest_root = tmp_path / "ingest"
    ingest_root.mkdir()
    (ingest_root / "coincidence.py").write_text("# the free ride\n")
    assert find_leaks(ingest_root, ["The free ride."]) == []


def test_real_fixture_ingest_root_has_no_leaks(tmp_path: Path):
    if not FACTS_PATH.is_file():
        pytest.skip(f"real fixture not present yet: no {FACTS_PATH}")

    truth = load_truth(SPIKE_ROOT / "truth")
    statements = [f.statement for f in truth.facts.values()]

    timeline = Timeline(SPIKE_ROOT)
    through_step = timeline.steps[-1].id
    ingest_root = assemble_ingest_root(SPIKE_ROOT, through_step, tmp_path / "ingest")

    leaks = find_leaks(ingest_root, statements)
    print(f"leak scan: {len(leaks)} hit(s) under {ingest_root}")
    for leak in leaks[:50]:
        print(f"  {leak}")

    assert leaks == [], f"{len(leaks)} leak(s) found (see captured output with -s for detail)"
