"""Tests for `asbuilt_mcp.create_app` (asbuilt#9): FastMCP's in-process
`Client` against the null prototype (proves the whole tool surface returns
empty pages cleanly) and a stub prototype returning known facts (proves
citations round-trip into both `structuredContent` and the text block, and
that pagination and validation work). No network, no subprocess — the
`Client(app)` transport is in-memory (fastmcp's own documented pattern)."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from asbuilt_mcp import _ServerState, create_app
from bench.null import NullPrototype
from bench.protocol import (
    Answer,
    Category,
    Citation,
    Contradiction,
    Fact,
    IngestReport,
    Sentence,
    Tier,
)
from tests._support import MINI_ROOT


def _fact(statement: str, entity: str = "farebox") -> Fact:
    return Fact(
        statement=statement,
        category=Category.BUSINESS_LOGIC,
        entities=(entity,),
        tier=Tier.CODE,
        citations=(Citation(document="code/farebox/pricing.py", location="FREE_MINUTES"),),
    )


class _StubPrototype:
    """A double returning known facts — never ingests anything real."""

    name = "stub"

    def __init__(self) -> None:
        self.facts = [_fact(f"Fact number {i}.") for i in range(3)]
        self.ingested = False

    def ingest(self, fixture_root, entity_kinds=(), incremental=False) -> IngestReport:
        self.ingested = True
        return IngestReport(
            seconds=0.0,
            input_tokens=0,
            output_tokens=0,
            dollars=0.0,
            services=(),
            documents=0,
        )

    def explain(self, entity: str) -> list[Fact]:
        return self.facts

    def search(self, query: str, category=None, since=None) -> list[Fact]:
        return self.facts

    def ask(self, question: str) -> Answer:
        return Answer(
            sentences=[
                Sentence(
                    text="The answer is cited.",
                    citations=(Citation(document="wiki/pricing-rules", location=None),),
                )
            ]
        )

    def contradictions(self, entity: str | None = None) -> list[Contradiction]:
        a, b = self.facts[0], self.facts[1]
        return [Contradiction(a=a, b=b, label="refutes", winner=a)]

    def stale(self, since) -> list[Fact]:
        return self.facts


def _call(app, tool_name: str, arguments: dict | None = None):
    async def _run():
        async with Client(app) as client:
            return await client.call_tool(tool_name, arguments or {})

    return asyncio.run(_run())


def _call_raises(app, tool_name: str, arguments: dict | None = None) -> Exception:
    async def _run():
        async with Client(app) as client:
            await client.call_tool(tool_name, arguments or {})

    with pytest.raises(ToolError) as exc_info:
        asyncio.run(_run())
    return exc_info.value


# ------------------------------------------------------------- null prototype


def test_null_prototype_explain_returns_empty_page():
    app = create_app(NullPrototype(), fixture_root=None)
    result = _call(app, "explain", {"name": "farebox"})

    assert result.is_error is False
    assert result.structured_content == {
        "facts": [],
        "page": {"total": 0, "limit": 20, "offset": 0, "returned": 0},
    }
    assert result.content[0].text == "(no facts)"


def test_null_prototype_ask_returns_no_answer_text():
    app = create_app(NullPrototype(), fixture_root=None)
    result = _call(app, "ask", {"question": "anything?"})

    assert result.structured_content == {"sentences": []}
    assert result.content[0].text == "(no answer)"


def test_null_prototype_contradictions_and_stale_are_empty():
    app = create_app(NullPrototype(), fixture_root=None)
    contradictions = _call(app, "contradictions", {})
    stale = _call(app, "stale", {"since": "2026-01-15T00:00:00-05:00"})

    assert contradictions.structured_content["contradictions"] == []
    assert stale.structured_content["facts"] == []


# ------------------------------------------------------------- stub prototype


def test_stub_explain_carries_citations_in_structured_and_text():
    app = create_app(_StubPrototype(), fixture_root=None)
    result = _call(app, "explain", {"name": "farebox"})

    assert result.structured_content["page"]["total"] == 3
    facts = result.structured_content["facts"]
    assert facts[0]["citations"][0]["document"] == "code/farebox/pricing.py"
    assert "code/farebox/pricing.py" in result.content[0].text
    assert "Fact number 0." in result.content[0].text


def test_stub_pagination_limit_and_offset():
    app = create_app(_StubPrototype(), fixture_root=None)
    result = _call(app, "search", {"query": "fact", "limit": 1, "offset": 1})

    assert result.structured_content["page"] == {
        "total": 3,
        "limit": 1,
        "offset": 1,
        "returned": 1,
    }
    assert result.structured_content["facts"][0]["statement"] == "Fact number 1."


def test_stub_ask_returns_cited_sentence():
    app = create_app(_StubPrototype(), fixture_root=None)
    result = _call(app, "ask", {"question": "How many free minutes?"})

    assert result.structured_content["sentences"][0]["text"] == "The answer is cited."
    assert "wiki/pricing-rules" in result.content[0].text


def test_stub_contradictions_resolves_winner_label():
    app = create_app(_StubPrototype(), fixture_root=None)
    result = _call(app, "contradictions", {})

    contradiction = result.structured_content["contradictions"][0]
    assert contradiction["winner"] == "a"
    assert contradiction["label"] == "refutes"
    assert "winner=a" in result.content[0].text


def test_stub_entities_derives_names_from_search_results():
    app = create_app(_StubPrototype(), fixture_root=None)
    result = _call(app, "entities", {"name": "farebox"})

    assert result.structured_content["entities"] == ["farebox"]
    assert "farebox" in result.content[0].text


def test_ingest_runs_lazily_on_first_call_when_a_fixture_root_is_given():
    """`fixture_root=None` (every other test here) means "already primed,
    nothing to assemble" (module docstring) — this test covers the real
    path: a fixture root triggers exactly one `assemble_ingest_root` +
    `ingest()`, on the first tool call, not at `create_app` time."""
    stub = _StubPrototype()
    app = create_app(stub, fixture_root=MINI_ROOT)
    assert stub.ingested is False

    _call(app, "explain", {"name": "farebox"})
    assert stub.ingested is True

    # A second call must not re-ingest.
    stub.ingested = False
    _call(app, "explain", {"name": "farebox"})
    assert stub.ingested is False


def test_ensure_ingested_is_thread_safe_under_two_concurrent_first_calls():
    """Review fix: fastmcp 4.0.10 runs sync tools in a threadpool, so two
    parallel first calls could both find `_ingested` False and both ingest.
    A short sleep inside the stub's own `ingest()` widens the race window
    that a lock-free version would fall into; with the lock, exactly one
    call does the work."""

    class _SlowIngestPrototype(_StubPrototype):
        def __init__(self) -> None:
            super().__init__()
            self.ingest_calls = 0

        def ingest(self, fixture_root, entity_kinds=(), incremental=False) -> IngestReport:
            self.ingest_calls += 1
            time.sleep(0.05)
            return super().ingest(fixture_root, entity_kinds, incremental)

    prototype = _SlowIngestPrototype()
    state = _ServerState(prototype=prototype, fixture_root=MINI_ROOT)

    threads = [threading.Thread(target=state.ensure_ingested) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert prototype.ingest_calls == 1


# ------------------------------------------------------------- validation


def test_explain_rejects_empty_name():
    app = create_app(NullPrototype(), fixture_root=None)
    error = _call_raises(app, "explain", {"name": ""})
    assert "name" in str(error)


def test_search_rejects_bad_pagination():
    app = create_app(_StubPrototype(), fixture_root=None)
    error = _call_raises(app, "search", {"query": "x", "limit": 0})
    assert "limit" in str(error)

    error = _call_raises(app, "search", {"query": "x", "offset": -1})
    assert "offset" in str(error)

    error = _call_raises(app, "search", {"query": "x", "limit": 1000})
    assert "limit" in str(error)


def test_stale_parses_iso_datetime():
    app = create_app(_StubPrototype(), fixture_root=None)
    result = _call(app, "stale", {"since": datetime(2026, 1, 15, tzinfo=UTC).isoformat()})
    assert result.structured_content["page"]["total"] == 3
