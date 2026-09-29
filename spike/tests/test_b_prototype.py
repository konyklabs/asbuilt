"""Stack B's Prototype on MemoryStore (konyklabs/asbuilt#4): the no-model
path on the mini fixture and on the real one, the model path with a fake
client, and the claude-code wiring with a fake `claude` on PATH. No real
model call is made anywhere in this file. Postgres runs in
tests/test_b_postgres.py."""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench.build import build
from bench.llm import BudgetExceeded
from bench.protocol import Citation, Tier
from bench.run import ENTITY_KINDS, assemble_ingest_root
from connectors.tests.extract_model import ClaudeCodeClient
from pipeline.embed import HashEmbedder
from pipeline.llm import make_client, structured_call
from pipeline.resolve import Resolver
from pipeline.sources import SourceDocument, read_text_sources
from pipeline.store import Document, MemoryStore, StoredClaim, StoredFact
from prototypes.b_postgres import Prototype
from prototypes.b_postgres.extract import (
    TOOL_NAME,
    apply_extraction,
    build_schema,
    dry_run,
)
from tests._support import MINI_ROOT, SPIKE_ROOT


@pytest.fixture
def mini_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    build(MINI_ROOT, tmp_path / "built")
    monkeypatch.setenv("ASBUILT_B_BUILT", str(tmp_path / "built"))
    monkeypatch.setenv("ASBUILT_EMBED", "fake")
    return assemble_ingest_root(MINI_ROOT, "c4", tmp_path / "ingest")


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=100, output_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=0
    )


class FakeModel:
    """Answers each structured call by its tool name; records the calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        tool = kwargs["tools"][0]["name"]
        prompt = kwargs["messages"][-1]["content"]
        if tool == TOOL_NAME:
            doc_id = re.search(r"Document id: (\S+)", prompt).group(1)
            payload = {"entities": [], "facts": []}
            if doc_id == "wiki/pricing-rules-2025":
                payload = {
                    "entities": [
                        {"name": "FREE_MINUTES", "kind": "rule", "aliases": ["member free minutes"]}
                    ],
                    "facts": [
                        {
                            "statement": "A member's first 25 minutes are free.",
                            "category": "business-logic",
                            "entities": ["farebox", "member free minutes"],
                            "claim": {
                                "entity": "member free minutes",
                                "attribute": "free_minutes",
                                "value": 25,
                                "unit": "minute",
                            },
                            "citation": {"document": "wiki/other", "location": "#free-minutes"},
                        },
                        {
                            "statement": "Refunds need a reason.",
                            "category": "business-logic",
                            "entities": [],
                            "citation": {"document": doc_id, "location": "#nowhere"},
                        },
                    ],
                }
        elif tool == "record_verdict":
            payload = {"label": "unrelated", "reason": "fake"}
        else:
            payload = {"sentences": [{"text": "Composed from fact one.", "facts": [1, 99]}]}
        return SimpleNamespace(
            usage=_usage(), content=[SimpleNamespace(type="tool_use", input=payload)]
        )


def test_no_model_ingest_serves_every_surface_with_citations(mini_built, monkeypatch):
    monkeypatch.setenv("ASBUILT_B_NO_MODEL", "1")
    prototype = Prototype(store=MemoryStore())
    report = prototype.ingest(mini_built, ENTITY_KINDS)
    assert report.services == ("postgres",)
    assert (report.calls, report.input_tokens, report.model) == (0, 0, None)
    assert report.embedder.startswith("hash-384") and report.documents > 0
    facts = prototype.explain("FREE_MINUTES")
    assert facts and all(f.citations for f in facts)
    assert facts[0].tier == Tier.EXECUTED
    assert any(c.document.startswith("run/") for c in facts[0].citations)
    assert prototype.explain("nothing by this name") == []
    assert all(f.citations for f in prototype.search("free minutes"))
    answer = prototype.ask("How many free minutes does a member get?")
    assert answer.sentences and all(0 < len(s.citations) <= 3 for s in answer.sentences)
    assert prototype.stale(datetime.fromisoformat("2025-01-01T00:00:00+00:00")) == []
    assert prototype.last_ingest["contradiction_pass"].skipped_reason


def test_model_path_extracts_documents_through_the_counting_client(mini_built, monkeypatch):
    monkeypatch.delenv("ASBUILT_B_NO_MODEL", raising=False)
    monkeypatch.setenv("ASBUILT_NLI", "off")
    monkeypatch.chdir(mini_built.parent)  # a budget stop file would land here, never in spike/
    fake = FakeModel()
    prototype = Prototype(store=MemoryStore(), client_factory=lambda: fake)
    report = prototype.ingest(mini_built, ENTITY_KINDS)

    text_docs = [d for d in read_text_sources(mini_built)]
    document_calls = [c for c in fake.calls if c["tools"][0]["name"] == TOOL_NAME]
    assert len(document_calls) == len(text_docs)
    assert report.calls == len(fake.calls) and report.input_tokens == 100 * len(fake.calls)
    assert report.model == "claude-sonnet-5"

    documented = [f for f in prototype.explain("FREE_MINUTES") if f.tier == Tier.DOCUMENTED]
    assert [f.statement for f in documented] == ["A member's first 25 minutes are free."]
    (citation,) = documented[0].citations
    # The citation is forced to the document read, with an anchor it really has.
    assert (citation.document, citation.location) == ("wiki/pricing-rules-2025", "#free-minutes")
    assert "Refunds need a reason." not in {f.statement for f in prototype.search("refunds")}

    pairs = prototype.contradictions("member free minutes")
    assert any(
        c.winner is not None
        and c.winner.tier == Tier.EXECUTED
        and "25" in c.a.statement + c.b.statement
        for c in pairs
    )
    stale = prototype.stale(datetime.fromisoformat("2026-01-01T00:00:00-05:00"))
    assert [f.statement for f in stale] == ["A member's first 25 minutes are free."]

    answer = prototype.ask("How many free minutes?")
    assert [s.text for s in answer.sentences] == ["Composed from fact one."]
    assert answer.sentences[0].citations


def test_incremental_ingest_extracts_only_changed_documents(mini_built, monkeypatch, tmp_path):
    monkeypatch.delenv("ASBUILT_B_NO_MODEL", raising=False)
    monkeypatch.setenv("ASBUILT_NLI", "off")
    monkeypatch.chdir(mini_built.parent)
    fake = FakeModel()
    prototype = Prototype(store=MemoryStore(), client_factory=lambda: fake)
    first_root = assemble_ingest_root(MINI_ROOT, "c3", tmp_path / "phase-1")
    prototype.ingest(first_root, ENTITY_KINDS)
    calls_after_first = len(fake.calls)
    report = prototype.ingest(mini_built, ENTITY_KINDS, incremental=True)
    assert prototype.last_ingest["steps"] == ["c4"]
    document_calls = [
        c for c in fake.calls[calls_after_first:] if c["tools"][0]["name"] == TOOL_NAME
    ]
    assert document_calls == []  # no text document changed between the two roots
    assert report.documents > 0  # the code files and the new run did


def test_budget_stop_mid_extraction_leaves_the_rest_pending(mini_built, monkeypatch):
    """Review finding (asbuilt#4): a text document is registered at its new
    version only once its facts are stored, so a stop after the first
    document leaves every other one to the next incremental ingest."""
    monkeypatch.delenv("ASBUILT_B_NO_MODEL", raising=False)
    monkeypatch.setenv("ASBUILT_NLI", "off")
    monkeypatch.chdir(mini_built.parent)

    class StopsAfterOne(FakeModel):
        def create(self, **kwargs):
            if self.calls:
                raise BudgetExceeded("b_postgres", "fake: 80% of the cap")
            return super().create(**kwargs)

    store = MemoryStore()
    with pytest.raises(BudgetExceeded):
        Prototype(store=store, client_factory=StopsAfterOne).ingest(mini_built, ENTITY_KINDS)
    text_ids = [d.id for d in read_text_sources(mini_built)]
    registered = [i for i in text_ids if (d := store.document(i)) and d.content_hash]
    assert registered == ["wiki/pricing-rules-2025"]

    fake = FakeModel()
    resumed = Prototype(store=store, client_factory=lambda: fake)
    resumed.ingest(mini_built, ENTITY_KINDS, incremental=True)
    extracted = [
        re.search(r"Document id: (\S+)", c["messages"][-1]["content"]).group(1)
        for c in fake.calls
        if c["tools"][0]["name"] == TOOL_NAME
    ]
    assert extracted == text_ids[1:]
    assert resumed.last_ingest["steps"] == [] and resumed.last_ingest["documents_pending"] == 0


def test_a_page_edit_never_closes_a_code_row(tmp_path: Path):
    """Review finding (asbuilt#4): a page's new value supersedes only a
    documented fact the page alone stated; against a code row it becomes a
    contradiction, winner the code, and the page's citation is retracted."""
    jan, mar = (datetime.fromisoformat(f"2026-0{m}-01T00:00:00+00:00") for m in (1, 3))
    store, embedder = MemoryStore(), HashEmbedder()
    resolver = Resolver(store, embedder, ENTITY_KINDS)
    fee = resolver.resolve("late return fee", "rule")
    code = store.upsert_fact(
        StoredFact(
            statement="Late fee $6.00.",
            category="business-logic",
            tier="code",
            entity_ids=(fee,),
            citations=(Citation("code/ticketbox/fees.py", "LATE_FEE", "s1"),),
            claim=StoredClaim(fee, "late_fee", 6.0, "usd"),
            valid_at=jan,
            source_key="code:code/ticketbox/fees.py#LATE_FEE",
        )
    )

    def page(doc_id: str, version: str, when: datetime) -> SourceDocument:
        meta = Document(doc_id, "wiki", "wiki", version, when, content_hash=f"{doc_id}@{version}")
        return SourceDocument(meta, text="(invented)", anchors=("#fee",))

    def payload(doc_id: str, attribute: str, value: int, unit: str) -> dict:
        claim = {"entity": "late return fee", "attribute": attribute, "value": value, "unit": unit}
        fact = {
            "statement": f"The late return fee {attribute} is {value}.",
            "category": "business-logic",
            "entities": ["late return fee"],
            "claim": claim,
            "citation": {"document": doc_id, "location": "#fee"},
        }
        return {"entities": [], "facts": [fact]}

    script = [
        payload("wiki/fees", "late_fee", 6, "usd"),
        payload("wiki/fees", "late_fee", 4, "usd"),
        payload("wiki/waiver", "waiver_days", 2, "day"),
        payload("wiki/waiver", "waiver_days", 3, "day"),
    ]

    class Scripted:
        def __init__(self) -> None:
            self.messages = self

        def create(self, **kwargs):
            block = SimpleNamespace(type="tool_use", input=script.pop(0))
            return SimpleNamespace(usage=_usage(), content=[block])

    client = make_client("b_postgres", client_factory=Scripted, stop_dir=tmp_path)
    prototype = Prototype(store=store, embedder=embedder)
    for doc in (page("wiki/fees", "1", jan), page("wiki/fees", "2", mar)):
        prototype._extract(store, resolver, embedder, client, doc, ENTITY_KINDS)
    row = store.fact(code)
    assert (row.tier, row.invalid_at) == ("code", None)  # not closed by the page
    assert "wiki/fees" not in {c.document for c in row.citations}
    (pair,) = store.query_contradictions()
    (page_fact,) = store.facts_citing("wiki/fees")
    assert {pair.a, pair.b} == {code, page_fact.id} and pair.winner == code

    for doc in (page("wiki/waiver", "1", jan), page("wiki/waiver", "2", mar)):
        prototype._extract(store, resolver, embedder, client, doc, ENTITY_KINDS)
    old, new = sorted(
        (f for f in store.all_facts() if f.claim and f.claim.attribute == "waiver_days"),
        key=lambda f: f.claim.value,
    )
    assert (old.invalid_at, old.superseded_by) == (mar, new.id)  # the page's own value moved


def test_apply_extraction_skips_facts_it_cannot_attach(mini_built):
    store, embedder = MemoryStore(), HashEmbedder()
    doc = next(d for d in read_text_sources(mini_built) if d.id == "doc/DOC-1")
    payload = {
        "entities": [{"name": "refunds", "kind": "rule", "aliases": ["the refund rules"]}],
        "facts": [
            {
                "statement": "Refunds take 5 business days.",
                "category": "operations",
                "entities": ["the refund rules"],
                "claim": {
                    "entity": "refunds",
                    "attribute": "processing",
                    "value": 5,
                    "unit": "days",
                },
                "citation": {"document": doc.id, "location": "#refund-policy"},
            },
            {"statement": " ", "category": "history", "entities": ["x"], "citation": {}},
        ],
    }
    ids = apply_extraction(store, Resolver(store, embedder), embedder, doc, payload)
    (stored,) = [store.fact(i) for i in ids]
    assert stored.tier == "documented" and stored.category == "operations"
    assert stored.claim.unit == "day" and stored.claim.value == 5.0
    assert stored.citations[0].location == "#refund-policy"


def test_dry_run_prices_every_document_without_a_call(mini_built):
    docs = read_text_sources(mini_built)
    result = dry_run(docs, ENTITY_KINDS)
    assert result.documents == len(docs) and result.estimated_input_tokens > 0
    assert result.estimated_dollars > 0


_FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_ARGS"], "w") as f:
    json.dump(args, f)
schema = json.loads(args[args.index("--json-schema") + 1])
print(json.dumps({
    "type": "result", "subtype": "success", "is_error": False, "result": "done",
    "structured_output": {"entities": [], "facts": [], "_schema_required": schema["required"]},
    "modelUsage": {"claude-sonnet-5": {"inputTokens": 11, "outputTokens": 3}},
}))
"""


def test_claude_code_provider_receives_the_document_schema(tmp_path: Path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(_FAKE_CLAUDE)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    args_file = tmp_path / "args.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(args_file))

    client = make_client("b_postgres", client_factory=ClaudeCodeClient, stop_dir=tmp_path)
    payload = structured_call(
        client,
        prompt="Document id: wiki/x",
        schema=build_schema(ENTITY_KINDS),
        system="SYSTEM-UNDER-TEST",
        tool_name=TOOL_NAME,
    )
    args = json.loads(args_file.read_text())
    assert payload["_schema_required"] == ["entities", "facts"]
    assert args[args.index("--system-prompt") + 1] == "SYSTEM-UNDER-TEST"
    assert (client.calls, client.input_tokens, client.output_tokens) == (1, 11, 3)


@pytest.mark.fixture
def test_real_fixture_no_model_on_memory(tmp_path: Path, monkeypatch):
    """The same assertions the Postgres integration test makes, without
    Docker: c5, then c6 incrementally."""
    if not (SPIKE_ROOT / "truth" / "facts.yaml").is_file():
        pytest.skip("real fixture not present")
    monkeypatch.setenv("ASBUILT_B_NO_MODEL", "1")
    monkeypatch.setenv("ASBUILT_EMBED", "fake")
    monkeypatch.setenv("ASBUILT_B_BUILT", str(tmp_path / "built"))
    build(SPIKE_ROOT, tmp_path / "built")
    prototype = Prototype(store=MemoryStore())
    prototype.ingest(assemble_ingest_root(SPIKE_ROOT, "c5", tmp_path / "c5"), ENTITY_KINDS)
    at_c5 = prototype.contradictions("lost-bike-fee")
    prototype.ingest(assemble_ingest_root(SPIKE_ROOT, "c6", tmp_path / "c6"), ENTITY_KINDS, True)

    (pair,) = at_c5
    assert {pair.a.statement, pair.b.statement} == {
        "Lost bike fee $100.00.",
        "Lost bike fee is $150.00.",
    }
    assert pair.winner.statement == "Lost bike fee is $150.00."
    assert any(c.document == "run/pytest-c5-rerun" for c in pair.a.citations + pair.b.citations)
    top = prototype.explain("lost bike fee")[0]
    assert top.tier == Tier.EXECUTED and "150" in top.statement
    assert any(c.document == "run/pytest-c6" for c in top.citations)
    # One fact for the $150 claim, from the code constant's step (c5), not the test's (c6).
    assert top.valid_from == datetime.fromisoformat("2026-07-22T14:00:00-04:00")
    assert "code/farebox/pricing.py" in {c.document for c in top.citations}
    assert len(prototype.contradictions("lost-bike-fee")) == 1  # kept, resolved at c6
