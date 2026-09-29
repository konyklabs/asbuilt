"""Tests for `prototypes.baseline.Prototype` (asbuilt#9): the no-store
baseline arm. No real `claude -p` call is made anywhere here — a fake
`claude` executable on `PATH` proves the subprocess wiring, exactly as
`tests/test_connector_model.py` does for the test connector's own model
extractor. The fake script inspects the `--json-schema` it was given (its
`required` list) to decide which canned `structured_output` shape to
return, since the baseline sends a different schema per surface, and
records its own invocation (prompt, `--tools`, cwd) to a side file so a test
can tell the `full` and `grep` call paths apart without reading any secret."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from bench.build import build as build_repo
from bench.run import ENTITY_KINDS, assemble_ingest_root
from prototypes.baseline import Prototype
from tests._support import MINI_ROOT

_FAKE_CLAUDE_SCRIPT = r"""#!/usr/bin/env python3
import json
import os
import sys

schema = None
tools = None
# The prompt travels over stdin, never as an argv element (asbuilt#9 review:
# a single argv element is capped well under a corpus-sized prompt on Linux).
prompt = sys.stdin.read()
for i, arg in enumerate(sys.argv):
    if arg == "--json-schema" and i + 1 < len(sys.argv):
        schema = json.loads(sys.argv[i + 1])
    if arg == "--tools" and i + 1 < len(sys.argv):
        tools = sys.argv[i + 1]

record_path = os.environ.get("FAKE_CLAUDE_RECORD_PATH")
if record_path:
    required = (schema.get("required") or [None])[0] if schema else None
    with open(record_path, "a") as f:
        f.write(
            json.dumps(
                {
                    "prompt": prompt,
                    "tools": tools,
                    "cwd": os.getcwd(),
                    "required": required,
                }
            )
            + "\n"
        )

required = (schema.get("required") or [None])[0] if schema else None

fact = {
    "statement": "A member's free minutes are 25.",
    "category": "business-logic",
    "entities": ["member-free-minutes"],
    "tier": "code",
    "claim": None,
    "citations": [{"document": "code/farebox/pricing.py", "location": "FREE_MINUTES"}],
}
other_fact = dict(fact)
other_fact["statement"] = "A member's free minutes are 15."
other_fact["citations"] = [{"document": "wiki/pricing-rules", "location": None}]

if required == "facts":
    structured = {"facts": [fact]}
elif required == "sentences":
    structured = {
        "sentences": [
            {
                "text": "A member gets 25 free minutes.",
                "citations": fact["citations"],
            }
        ]
    }
elif required == "contradictions":
    structured = {
        "contradictions": [{"a": fact, "b": other_fact, "label": "refutes", "winner": "a"}]
    }
else:
    structured = {}

result = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "ok",
    "structured_output": structured,
    "modelUsage": {"claude-sonnet-5": {"inputTokens": 10, "outputTokens": 5}},
    "total_cost_usd": 0.001,
}
sys.stdout.write(json.dumps(result))
"""


def _install_fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "claude"
    script.write_text(_FAKE_CLAUDE_SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return script


def _build_and_assemble(tmp_path: Path, step: str = "c2") -> tuple[Path, dict]:
    """Builds the mini fixture's repo/commits.json and assembles an ingest
    root at `<build>/ingest` — the sibling layout `_find_commits_sha`
    (prototypes/baseline) expects."""
    build_out = tmp_path / "build"
    commits = build_repo(MINI_ROOT, build_out)
    ingest_root = assemble_ingest_root(MINI_ROOT, step, build_out / "ingest")
    return ingest_root, commits


def _records(record_path: Path) -> list[dict]:
    if not record_path.is_file():
        return []
    return [json.loads(line) for line in record_path.read_text().splitlines() if line.strip()]


def test_ingest_makes_no_model_call_and_counts_documents(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ASBUILT_BASELINE_VARIANT", raising=False)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    report = prototype.ingest(ingest_root, ENTITY_KINDS)

    assert report.calls == 0
    assert report.input_tokens == 0
    assert report.output_tokens == 0
    assert report.dollars == 0.0
    assert report.documents > 0
    assert (ingest_root / "repo" / "farebox" / "pricing.py").is_file()


def test_full_variant_explain_cites_code_with_commits_sha(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "full")
    record_path = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD_PATH", str(record_path))
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, commits = _build_and_assemble(tmp_path, step="c2")

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    facts = prototype.explain("member-free-minutes")

    assert len(facts) == 1
    fact = facts[0]
    assert fact.statement == "A member's free minutes are 25."
    assert fact.citations[0].document == "code/farebox/pricing.py"
    assert fact.citations[0].version == commits["c2"]["sha"]  # last step through c2

    calls = _records(record_path)
    assert len(calls) == 1
    assert calls[0]["tools"] == ""  # full variant: no tools, corpus is in the prompt
    assert "Corpus:" in calls[0]["prompt"]
    assert "code/farebox/pricing.py" in calls[0]["prompt"]  # a document header


def test_grep_variant_uses_tools_and_ingest_root_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "grep")
    record_path = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD_PATH", str(record_path))
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    facts = prototype.search("free minutes")

    assert len(facts) == 1
    calls = _records(record_path)
    assert len(calls) == 1
    assert calls[0]["tools"] == "Read,Grep,Glob"
    assert calls[0]["cwd"] == str(ingest_root.resolve())
    assert "Corpus:" not in calls[0]["prompt"]  # grep never pastes the corpus in


def test_full_variant_falls_back_to_grep_over_the_token_estimate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "full")
    monkeypatch.setenv("ASBUILT_BASELINE_MAX_TOKENS", "1")  # any real corpus exceeds this
    record_path = tmp_path / "record.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD_PATH", str(record_path))
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    prototype.explain("member-free-minutes")

    calls = _records(record_path)
    assert calls[0]["tools"] == "Read,Grep,Glob"  # fell back to grep for this query


def test_ask_returns_cited_sentences(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "full")
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    answer = prototype.ask("How many free minutes does a member get?")

    assert len(answer.sentences) == 1
    assert answer.sentences[0].text == "A member gets 25 free minutes."
    assert answer.sentences[0].citations[0].document == "code/farebox/pricing.py"


def test_contradictions_resolves_winner_to_the_named_fact(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "full")
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    contradictions = prototype.contradictions("member-free-minutes")

    assert len(contradictions) == 1
    contradiction = contradictions[0]
    assert contradiction.winner is contradiction.a
    assert contradiction.a.statement == "A member's free minutes are 25."
    assert contradiction.b.statement == "A member's free minutes are 15."


def test_stale_uses_facts_schema(tmp_path: Path, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "full")
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    facts = prototype.stale(datetime(2026, 1, 15, tzinfo=UTC))

    assert len(facts) == 1


def test_unknown_variant_raises(monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "not-a-real-variant")
    with pytest.raises(ValueError, match="not-a-real-variant"):
        Prototype()


def test_stats_reports_cumulative_call_and_token_counts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ASBUILT_BASELINE_VARIANT", "full")
    _install_fake_claude(tmp_path, monkeypatch)
    ingest_root, _commits = _build_and_assemble(tmp_path)

    prototype = Prototype()
    prototype.ingest(ingest_root, ENTITY_KINDS)
    prototype.explain("member-free-minutes")
    prototype.explain("member-free-minutes")

    stats = prototype.stats()
    assert stats["calls"] == 2
    assert stats["input_tokens"] == 20
    assert stats["output_tokens"] == 10
