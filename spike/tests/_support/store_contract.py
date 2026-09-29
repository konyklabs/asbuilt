"""The write-side store contract (``pipeline.store.StoreInterface``), written
once and run against every implementation: ``tests/test_pipeline_store.py``
runs it on ``MemoryStore``, ``tests/test_b_postgres.py`` on ``PostgresStore``
in a throwaway pgvector container. Each check takes a freshly reset store.
Everything named here is invented."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from bench.protocol import Citation
from pipeline.embed import HashEmbedder
from pipeline.store import Document, Entity, StoredClaim, StoredFact

T1 = datetime(2026, 1, 10, tzinfo=UTC)
T2 = datetime(2026, 2, 10, tzinfo=UTC)
T3 = datetime(2026, 3, 10, tzinfo=UTC)
EMBED = HashEmbedder()


def _entities(store) -> dict[str, str]:
    store.upsert_entity(Entity(id="e-svc", name="ticketbox", kind="service"))
    store.upsert_entity(
        Entity(id="e-rule", name="late-return-fee", kind="rule", aliases=("the late fee",))
    )
    store.upsert_entity(Entity(id="e-flag", name="late_fee_waiver", kind="flag"))
    store.upsert_entity(Entity(id="e-team", name="Fares team", kind="team"))
    return {"svc": "e-svc", "rule": "e-rule", "flag": "e-flag", "team": "e-team"}


def fact(
    statement: str,
    *,
    tier: str = "code",
    entities: tuple[str, ...] = ("e-svc", "e-rule"),
    cite: str = "code/ticketbox/fees.py",
    location: str | None = "LATE_FEE",
    version: str | None = "sha1",
    claim: StoredClaim | None = None,
    valid_at: datetime | None = T1,
    category: str = "business-logic",
    source_key: str | None = None,
    detail: str = "",
) -> StoredFact:
    return StoredFact(
        statement=statement,
        category=category,
        tier=tier,
        entity_ids=entities,
        citations=(Citation(document=cite, location=location, version=version),),
        detail=detail,
        claim=claim,
        valid_at=valid_at,
        source_key=source_key,
        embedding=EMBED.embed([statement])[0],
    )


def check_identity_and_merge(store) -> None:
    _entities(store)
    first = store.upsert_fact(fact("Late return fee is $4.00.", tier="executed"))
    again = store.upsert_fact(
        fact("late return fee is $4.00", tier="documented", cite="wiki/fees", location="#late")
    )
    assert again == first
    merged = store.fact(first)
    assert merged.tier == "executed"  # a page agreeing never lowers the tier
    assert {c.document for c in merged.citations} == {"code/ticketbox/fees.py", "wiki/fees"}
    store.upsert_fact(
        fact("Late return fee is $4.00.", tier="code", valid_at=T2, source_key="test:t1")
    )
    demoted = store.fact(first)
    assert demoted.tier == "code"  # the connector's demotion replaces executed
    assert demoted.valid_at == T1  # the earliest valid_at is kept


def check_claim_is_part_of_identity(store) -> None:
    _entities(store)
    claim = StoredClaim("e-rule", "late_fee", 4.0, "usd")
    with_claim = store.upsert_fact(fact("Late return fee is $4.00.", claim=claim))
    without = store.upsert_fact(fact("Late return fee is $4.00.", cite="wiki/fees"))
    assert with_claim != without
    assert store.fact(with_claim).claim == claim


def check_claim_facts_merge_across_statements(store) -> None:
    """D-013's identity rule: the claim is the fact. The code constant and
    the test asserting it are one row from the earliest step, with every
    citation, the higher-tier sentence as the statement and the other kept
    in detail; a code constant re-read or a page never lowers the tier."""
    _entities(store)
    claim = StoredClaim("e-rule", "late_fee", 6.0, "usd")
    constant = store.upsert_fact(
        fact("Late fee is $6.00.", claim=claim, valid_at=T1, source_key="code:fees.py#LATE_FEE")
    )
    test = store.upsert_fact(
        fact(
            "Late fee $6.00.",
            tier="executed",
            claim=claim,
            valid_at=T2,
            cite="run/pytest-s2",
            location="tests/test_fees.py::test_fee_6",
            version=None,
            source_key="test:tests/test_fees.py::test_fee_6",
            detail="fee equals $6.00",
        )
    )
    assert test == constant
    merged = store.fact(constant)
    assert (merged.statement, merged.tier, merged.valid_at) == ("Late fee $6.00.", "executed", T1)
    assert merged.detail == "fee equals $6.00; Also stated as: Late fee is $6.00."
    assert {c.document for c in merged.citations} == {"code/ticketbox/fees.py", "run/pytest-s2"}
    store.upsert_fact(
        fact("Late fee is $6.00.", claim=claim, valid_at=T3, source_key="code:fees.py#LATE_FEE")
    )
    store.upsert_fact(
        fact("The late fee is six dollars.", tier="documented", claim=claim, cite="wiki/fees")
    )
    again = store.fact(constant)
    assert (again.statement, again.tier) == ("Late fee $6.00.", "executed")
    assert again.detail.endswith("; Also stated as: The late fee is six dollars.")
    assert [f.id for f, _ in store.query_text("six dollars")] == [constant]


def check_superseded_claim_and_pages(store) -> None:
    """A page still stating a superseded claim as current is its own
    documented row; a page stating it as history joins the old episode."""
    _entities(store)
    four = StoredClaim("e-rule", "late_fee", 4.0, "usd")
    old = store.upsert_fact(fact("Late fee $4.00.", claim=four, valid_at=T1))
    new = store.upsert_fact(
        fact("Late fee $6.00.", claim=StoredClaim("e-rule", "late_fee", 6.0, "usd"), valid_at=T2)
    )
    store.supersede(old, new, T2)
    history = fact("The fee was $4 until February.", tier="documented", claim=four, cite="doc/h")
    history.invalid_at = T2
    assert store.upsert_fact(history) == old
    current = store.upsert_fact(
        fact("The late fee is $4.", tier="documented", claim=four, cite="wiki/fees", valid_at=T1)
    )
    assert current == f"{old}.1"
    page = store.fact(current)
    assert (page.tier, page.invalid_at, page.statement) == (
        "documented",
        None,
        "The late fee is $4.",
    )


def check_rejects_uncited_fact(store) -> None:
    _entities(store)
    uncited = fact("A fact with no citation.")
    uncited.citations = ()
    with pytest.raises(ValueError, match="citation"):
        store.upsert_fact(uncited)


def check_supersede_and_episodes(store) -> None:
    _entities(store)
    old = store.upsert_fact(fact("Late return fee is $4.00.", valid_at=T1))
    new = store.upsert_fact(fact("Late return fee is $6.00.", valid_at=T2))
    store.supersede(old, new, T2)
    closed = store.fact(old)
    assert closed.invalid_at == T2 and closed.superseded_by == new
    assert old in {f.id for f in store.query_by_entity("e-rule")}  # history stays explainable
    back = store.upsert_fact(fact("Late return fee is $4.00.", valid_at=T3))
    assert back == f"{old}.1"  # held again later: a new episode, not a reopened interval
    assert store.fact(back).invalid_at is None
    assert store.fact(old).invalid_at == T2


def check_stored_time(store) -> None:
    _entities(store)
    kept = store.upsert_fact(fact("Late return fee is $4.00."))
    before = store.snapshot("before")
    added = store.upsert_fact(fact("Waiver skips the late fee.", entities=("e-flag",)))
    assert added not in {f.id for f in store.all_facts(as_of=before)}
    assert added in {f.id for f in store.all_facts()}
    store.expire(kept)
    assert kept not in {f.id for f in store.all_facts()}
    assert kept in {f.id for f in store.all_facts(as_of=before)}
    assert store.snapshot_at("before") == before


def check_retract_citation(store) -> None:
    _entities(store)
    fid = store.upsert_fact(fact("Late return fee is $4.00.", cite="wiki/fees", location=None))
    store.upsert_fact(fact("Late return fee is $4.00.", cite="ticket/TB-1", location=None))
    store.retract_citation(fid, "wiki/fees")
    assert [c.document for c in store.fact(fid).citations] == ["ticket/TB-1"]
    store.retract_citation(fid, "ticket/TB-1")
    assert store.fact(fid).expired_at is not None


def check_lookups(store) -> None:
    _entities(store)
    claim = StoredClaim("e-rule", "late_fee", 4.0, "usd")
    a = store.upsert_fact(fact("Late return fee is $4.00.", claim=claim, source_key="test:t1"))
    b = store.upsert_fact(
        fact("Waiver skips the late fee.", entities=("e-flag",), valid_at=T3, cite="wiki/fees")
    )
    assert [f.id for f in store.facts_by_claim_key("e-rule", "late_fee")] == [a]
    assert [f.id for f in store.facts_by_source("test:t1")] == [a]
    assert [f.id for f in store.facts_citing("wiki/fees")] == [b]
    assert [f.id for f in store.facts_since(T2)] == [b]


def check_text_and_vector_search(store) -> None:
    _entities(store)
    fee = store.upsert_fact(fact("Late return fee is charged after two hours."))
    store.upsert_fact(
        fact("Waiver flag is off by default.", entities=("e-flag",), category="operations")
    )
    text = store.query_text("late return fee")
    assert text and text[0][0].id == fee
    vector = store.query_vector(EMBED.embed(["late return fee"])[0])
    assert vector[0][0].id == fee
    only_ops = store.query_text("waiver flag fee", category="operations")
    assert [f.category for f, _ in only_ops] == ["operations"]
    store.supersede(fee, fee, T2)  # a no-op: a fact never supersedes itself
    assert store.fact(fee).invalid_at is None


def check_since_filter(store) -> None:
    _entities(store)
    old = store.upsert_fact(fact("Late return fee is $4.00."))
    new = store.upsert_fact(fact("Late return fee is $6.00.", valid_at=T2))
    store.supersede(old, new, T2)
    hits = {f.id for f, _ in store.query_text("late return fee", since=T3)}
    assert hits == {new}


def check_entities(store) -> None:
    ids = _entities(store)
    assert store.entity_by_name("LATE-RETURN-FEE").id == ids["rule"]
    assert store.entity_by_alias("The Late Fee").id == ids["rule"]
    assert [e.id for e in store.entities_by_folded("latereturnfee")] == [ids["rule"]]
    store.add_alias(ids["rule"], "LATE_RETURN_FEE")
    store.add_alias(ids["rule"], "LATE_RETURN_FEE")  # idempotent
    assert store.entity(ids["rule"]).aliases == ("the late fee", "LATE_RETURN_FEE")
    store.upsert_entity(
        Entity(id="e-vec", name="overdue charge", kind="rule", embedding=[1.0] + [0.0] * 383)
    )
    near = store.nearest_entity([0.9, 0.1] + [0.0] * 382, "rule")
    assert near is not None and near[0].id == "e-vec" and near[1] > 0.9
    assert store.nearest_entity([0.9, 0.1] + [0.0] * 382, "flag") is None


def check_traversal(store) -> None:
    ids = _entities(store)
    store.upsert_entity(Entity(id="e-table", name="fee_ledger", kind="table"))
    store.add_relation(ids["rule"], ids["svc"], "part_of")
    store.add_relation(ids["flag"], ids["svc"], "part_of")
    store.add_relation(ids["rule"], "e-table", "related")
    store.add_relation(ids["rule"], ids["team"], "part_of")
    # From the rule: its related table; never through the service or team hubs.
    assert store.related_entities(ids["rule"], depth=2) == [ids["rule"], "e-table"]
    # From a hub itself: its direct members, not their neighbours.
    assert store.related_entities(ids["svc"], depth=1) == [ids["svc"], ids["flag"], ids["rule"]]
    store.upsert_fact(fact("Ledger row per late fee.", entities=("e-table",), cite="doc/ledger"))
    assert {f.statement for f in store.query_by_entity(ids["rule"], depth=1)} == {
        "Ledger row per late fee."
    }


def check_contradictions(store) -> None:
    _entities(store)
    a = store.upsert_fact(fact("Late return fee is $4.00.", tier="documented", cite="wiki/fees"))
    b = store.upsert_fact(fact("Late return fee is $6.00."))
    cid = store.link_contradiction(a, b, "refutes", winner=b, opened_at=T2, kind="claim")
    assert store.link_contradiction(b, a, "refutes", winner=b, opened_at=T1) == cid
    rows = store.query_contradictions("e-rule")
    assert [(r.id, r.winner, r.opened_at) for r in rows] == [(cid, b, T1)]
    assert store.query_contradictions("e-team") == []
    store.resolve_contradiction(cid, T3)
    assert store.query_contradictions()[0].resolved_at == T3


def check_documents_and_steps(store) -> None:
    doc = Document(id="wiki/fees", source="wiki", kind="wiki", version="3", lastmodified=T1)
    assert store.register_document(doc) is True
    assert store.register_document(doc) is False
    assert store.register_document(replace(doc, version="4")) is True
    assert store.document("wiki/fees").version == "4"
    assert store.last_step() is None
    store.snapshot("step:s1", step="s1")
    store.snapshot("step:s2", step="s2")
    assert store.last_step() == "s2"


CHECKS = [
    check_identity_and_merge,
    check_claim_is_part_of_identity,
    check_claim_facts_merge_across_statements,
    check_superseded_claim_and_pages,
    check_rejects_uncited_fact,
    check_supersede_and_episodes,
    check_stored_time,
    check_retract_citation,
    check_lookups,
    check_text_and_vector_search,
    check_since_filter,
    check_entities,
    check_traversal,
    check_contradictions,
    check_documents_and_steps,
]
