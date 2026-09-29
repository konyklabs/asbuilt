"""pipeline/lift.py over synthetic connector output, and pipeline/history.py
and pipeline/sources.py over the mini fixture and invented files
(konyklabs/asbuilt#4). No model; the hash embedder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bench.build import Timeline, build
from bench.run import assemble_ingest_root
from pipeline.embed import HashEmbedder
from pipeline.history import GitHistory
from pipeline.lift import apply_step
from pipeline.resolve import Resolver
from pipeline.sources import code_documents, read_run_documents, read_text_sources
from pipeline.store import MemoryStore
from tests._support import MINI_ROOT

S1, S2, S3 = (datetime(2026, m, 1, tzinfo=UTC) for m in (1, 2, 3))


class FakeHistory:
    step_ids = ["s1", "s2", "s3"]

    def date(self, step: str) -> datetime:
        return {"s1": S1, "s2": S2, "s3": S3}[step]


def _raw(node: str, statement: str, step: str, tier: str = "executed", claim=None, valid=None):
    file, name = node.split("::")
    citations = [{"document": f"code/{file}", "location": name, "version": f"sha-{step}"}]
    if tier == "executed":
        citations.append({"document": f"run/pytest-{step}", "location": node})
    return {
        "statement": statement,
        "detail": "",
        "category": "business-logic",
        "entities": ["ticketbox", "late fee"],
        "tier": tier,
        "citations": citations,
        "valid_from": valid or step,
        "claim": claim,
    }


def _fee(value: str) -> dict:
    return {"entity": "LATE_FEE", "attribute": "late_fee", "value": value, "unit": "usd"}


FEE4, FEE6 = "tests/test_fees.py::test_fee_4", "tests/test_fees.py::test_fee_6"
FREE10, FREE20 = "tests/test_fees.py::test_free_ten", "tests/test_fees.py::test_free_twenty"
WAIVER = "tests/test_flags.py::test_waiver_default"


def _outputs() -> list[dict]:
    s1 = [
        _raw(FEE4, "Late fee $4.00.", "s1", claim=_fee("$4.00")),
        _raw(FREE10, "Member 1st 10 minutes free.", "s1"),
        _raw(WAIVER, "Waiver on by default.", "s1"),
    ]
    demoted = _raw(FEE4, "Late fee $4.00.", "s2", tier="code", claim=_fee("$4.00"))
    candidate = {
        "node_id": FEE4,
        "opened_step": "s2",
        "a": {**demoted, "citations": demoted["citations"] + [{"document": "run/pytest-s2"}]},
        "b": {
            "statement": "Late fee is $6.00.",
            "category": "business-logic",
            "entities": ["ticketbox", "LATE_FEE"],
            "tier": "code",
            "citations": [{"document": "code/ticketbox/fees.py", "location": "LATE_FEE"}],
            "claim": _fee("$6.00"),
        },
        "reason": "failing run pytest-s2",
    }
    s2 = [
        demoted,
        _raw(FREE20, "Member 1st 20 minutes free.", "s2"),
        _raw(WAIVER, "Waiver off by default.", "s2"),
    ]
    s3 = [
        _raw(FEE6, "Late fee $6.00.", "s3", claim=_fee("$6.00")),
        _raw(FREE20, "Member 1st 20 minutes free.", "s3"),
        _raw(WAIVER, "Waiver off by default.", "s3"),
    ]
    return [
        {"step": "s1", "facts": s1, "contradiction_candidates": []},
        {"step": "s2", "facts": s2, "contradiction_candidates": [candidate]},
        {"step": "s3", "facts": s3, "contradiction_candidates": []},
    ]


def _by_statement(store: MemoryStore) -> dict[str, object]:
    return {f.statement: f for f in store.all_facts()}


def test_lift_tiers_supersessions_and_run_contradictions():
    store, embedder = MemoryStore(), HashEmbedder()
    resolver = Resolver(store, embedder, ("service", "rule"), services=["ticketbox"])
    history = FakeHistory()
    s1, s2, s3 = _outputs()

    first = apply_step(store, resolver, embedder, s1, history)
    facts = _by_statement(store)
    assert first.facts == 3 and first.superseded == 0
    assert facts["Late fee $4.00."].tier == "executed"
    # The claim's entity name and the fact's own entity fold to one entity.
    assert facts["Late fee $4.00."].claim.entity_id in facts["Late fee $4.00."].entity_ids
    assert len({e.id for e in store.entities()}) == 2

    second = apply_step(store, resolver, embedder, s2, history)
    facts = _by_statement(store)
    fee4, fee6_code = facts["Late fee $4.00."], facts["Late fee is $6.00."]
    assert fee4.tier == "code"  # demoted by the failing run
    assert fee4.valid_at == S1 and fee4.invalid_at == S2  # rule 2: same claim key, new value
    assert fee4.superseded_by == fee6_code.id
    assert facts["Member 1st 10 minutes free."].invalid_at == S2  # rule 3: replaced test
    assert facts["Waiver on by default."].invalid_at == S2  # rule 1: same test, new statement
    assert second.superseded == 3 and second.contradictions_opened == 1
    (row,) = store.query_contradictions()
    assert (row.kind, row.winner, row.opened_at, row.resolved_at) == ("run", fee6_code.id, S2, None)

    third = apply_step(store, resolver, embedder, s3, history)
    facts = _by_statement(store)
    fee6 = facts["Late fee $6.00."]
    # One claim, one fact: the test merges into the code constant's row,
    # which keeps the earlier step and every citation.
    assert (fee6.id, fee6.tier, fee6.valid_at) == (fee6_code.id, "executed", S2)
    assert "Also stated as: Late fee is $6.00." in fee6.detail
    assert {"code/ticketbox/fees.py", "run/pytest-s3"} <= {c.document for c in fee6.citations}
    assert store.fact(fee4.id).superseded_by == fee6_code.id  # the first supersession stands
    assert third.contradictions_resolved == 1
    assert store.query_contradictions()[0].resolved_at == S3
    assert {f.statement for f in store.all_facts() if f.invalid_at is None} == {
        "Late fee $6.00.",
        "Member 1st 20 minutes free.",
        "Waiver off by default.",
    }


def test_git_history_matches_the_timeline_and_finds_a_checkout(tmp_path: Path):
    commits = build(MINI_ROOT, tmp_path / "built")
    history = GitHistory(tmp_path / "built" / "repo", commits)
    timeline = Timeline(MINI_ROOT)
    for step in history.step_ids:
        assert history.active_paths_at(step) == timeline.active_paths_at(step)
        for path in history.active_paths_at(step):
            assert history.content_at(path, step) == timeline.content_at(path, step)
    root = assemble_ingest_root(MINI_ROOT, "c3", tmp_path / "ingest")
    assert history.step_of_checkout(root / "repo") == "c3"
    # pricing.py: the c1 overlay, the c3 overlay from c2, the final content at c4.
    assert history.last_change("farebox/pricing.py", "c3").id == "c2"
    assert history.last_change("farebox/pricing.py", "c4").id == "c4"
    assert history.last_change("farebox/refunds.py", "c4").id == "c3"
    assert history.services("c4") == ["dispatch", "farebox"]
    docs = {d.id: d.document for d in code_documents(history, "c4")}
    assert docs["code/farebox/pricing.py"].version == commits["c4"]["sha"]
    runs = {d.id: d.document for d in read_run_documents(root, history)}
    assert runs["run/pytest-c3"].version == commits["c3"]["sha"]
    assert "run/pytest-c4" not in runs  # the root holds only runs through its step


def test_sources_carry_versions_lastmodified_and_anchors(tmp_path: Path):
    wiki, docs = tmp_path / "sources" / "wiki", tmp_path / "sources" / "docs"
    tickets, pulls = tmp_path / "sources" / "tickets", tmp_path / "sources" / "pulls"
    for d in (wiki, docs, tickets, pulls):
        d.mkdir(parents=True)
    (wiki / "late-fees.md").write_text(
        "---\nid: wiki/late-fees\ntitle: Late fees\nversion: 3\n"
        "lastmodified: '2026-02-01T10:00:00-05:00'\n---\n\n# Late fees\n\n## The fee\n\nFour.\n"
    )
    (docs / "fee-policy.md").write_text(
        "---\nid: doc/fee-policy\ntitle: Fee policy\nheadRevisionId: 'r9'\n"
        "modifiedTime: '2026-03-01T10:00:00-05:00'\n---\n\n# Fee policy\n\n## Who pays?\n"
    )
    (tickets / "TB-7.json").write_text(
        json.dumps(
            {
                "id": "ticket/TB-7",
                "key": "TB-7",
                "summary": "Fee too high",
                "updated": "2026-03-02T10:00:00-05:00",
                "description": "Riders complain.",
                "comments": [{"id": "comment-1", "author": "a", "created": "x", "body": "Ok."}],
            }
        )
    )
    (pulls / "3.json").write_text(
        json.dumps(
            {
                "id": "pull/3",
                "number": 3,
                "title": "Lower the fee",
                "opened": "2026-03-03T10:00:00-05:00",
                "closed": "2026-03-04T10:00:00-05:00",
                "body": "Lowers it.",
                "comments": [
                    {"id": "comment-1", "created": "2026-03-05T10:00:00-05:00", "body": "Why?"}
                ],
            }
        )
    )
    found = {d.id: d for d in read_text_sources(tmp_path)}
    page = found["wiki/late-fees"]
    assert (page.document.version, page.anchors) == ("3", ("#late-fees", "#the-fee"))
    assert page.document.lastmodified == datetime.fromisoformat("2026-02-01T10:00:00-05:00")
    assert found["doc/fee-policy"].document.version == "r9"
    assert "#who-pays" in found["doc/fee-policy"].anchors
    assert found["ticket/TB-7"].anchors == ("description", "comment-1")
    assert "[comment-1]" in found["ticket/TB-7"].text
    pull = found["pull/3"].document
    assert pull.lastmodified == datetime.fromisoformat("2026-03-05T10:00:00-05:00")
    assert found["pull/3"].anchors == ("body", "comment-1")
