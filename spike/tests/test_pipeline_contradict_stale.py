"""pipeline/contradict.py and pipeline/stale.py (konyklabs/asbuilt#4), on
MemoryStore with fake NLI and a fake judge; no model is called. Invented."""

from __future__ import annotations

from datetime import UTC, datetime

from pipeline.contradict import lexical_candidate, run_pass
from pipeline.stale import stale_findings, stale_since
from pipeline.store import Document, Entity, MemoryStore, StoredClaim
from tests._support.store_contract import fact

JAN, MAR, MAY = (datetime(2026, m, 1, tzinfo=UTC) for m in (1, 3, 5))


def _store() -> MemoryStore:
    store = MemoryStore()
    store.upsert_entity(Entity(id="e-svc", name="ticketbox", kind="service"))
    store.upsert_entity(Entity(id="e-rule", name="late-return-fee", kind="rule"))
    store.upsert_entity(Entity(id="e-flag", name="late_fee_waiver", kind="flag"))
    return store


def _claim(value: float) -> StoredClaim:
    return StoredClaim("e-rule", "late_fee", value, "usd")


def test_claim_join_links_overlapping_values_and_picks_code():
    store = _store()
    page = store.upsert_fact(
        fact("The late fee is $4.", tier="documented", cite="wiki/fees", claim=_claim(4.0))
    )
    code = store.upsert_fact(fact("Late fee is $6.00.", claim=_claim(6.0), valid_at=MAR))
    report = run_pass(store)
    rows = store.query_contradictions()
    assert report.claim_pairs == 1 and len(rows) == 1
    assert {rows[0].a, rows[0].b} == {page, code} and rows[0].winner == code
    assert rows[0].kind == "claim" and rows[0].opened_at == MAR


def test_superseded_values_are_not_contradictions_and_stale_ones_resolve():
    store = _store()
    old = store.upsert_fact(fact("Late fee is $4.00.", claim=_claim(4.0), valid_at=JAN))
    new = store.upsert_fact(fact("Late fee is $6.00.", claim=_claim(6.0), valid_at=MAR))
    store.link_contradiction(old, new, "refutes", new, MAR, kind="claim")
    store.supersede(old, new, MAR)
    report = run_pass(store)
    assert report.claim_pairs == 0 and report.resolved == 1
    assert store.query_contradictions()[0].resolved_at is not None


def test_prose_pairs_need_a_judge_and_go_through_the_prefilter():
    store = _store()
    page = store.upsert_fact(
        fact(
            "The waiver applies to members.",
            tier="documented",
            entities=("e-flag",),
            cite="wiki/waiver",
        )
    )
    store.upsert_fact(fact("The waiver never applies to members.", entities=("e-flag",)))
    store.upsert_fact(
        fact("Waiver requests are logged.", tier="documented", entities=("e-flag",), cite="doc/log")
    )

    assert run_pass(store).skipped_reason == "no model: prose pairs are not decided"
    assert store.query_contradictions() == []

    class NLI:
        name = "fake-nli"

        def contradiction_probs(self, pairs):
            return [
                0.9
                if ("never" in a) != ("never" in b) and "applies" in a and "applies" in b
                else 0.1
                for a, b in pairs
            ]

    class Judge:
        calls = 0

        def verdict(self, a, b):
            Judge.calls += 1
            return "refutes", "one says never"

    report = run_pass(store, nli=NLI(), judge=Judge())
    assert report.prefilter == "fake-nli" and report.prefiltered == 1 and Judge.calls == 1
    (row,) = store.query_contradictions()
    assert row.kind == "prose" and page in (row.a, row.b) and row.winner != page


def test_lexical_stand_in_wants_overlap_and_a_negation_or_number_change():
    assert lexical_candidate("The waiver applies to members.", "The waiver never applies.")
    assert lexical_candidate("Late fee is 4 dollars.", "Late fee is 6 dollars.")
    assert not lexical_candidate("Late fee is 4 dollars.", "Dock sensors report hourly.")


def test_stale_by_claim_and_by_lastmodified():
    store = _store()
    store.register_document(Document("wiki/fees", "wiki", "wiki", "3", lastmodified=JAN))
    store.register_document(Document("code/ticketbox/fees.py", "repo", "code", "s", MAR))
    by_claim = store.upsert_fact(
        fact(
            "The late fee is $4.",
            tier="documented",
            cite="wiki/fees",
            claim=_claim(4.0),
            valid_at=JAN,
        )
    )
    store.upsert_fact(fact("Late fee is $6.00.", claim=_claim(6.0), valid_at=MAR))
    by_date = store.upsert_fact(
        fact(
            "Late returns are charged after 2 hours.",
            tier="documented",
            cite="wiki/fees",
            valid_at=JAN,
        )
    )
    store.upsert_fact(fact("Late returns are charged after 3 hours.", valid_at=MAR))
    history = store.upsert_fact(
        fact(
            "The late fee was $2 during the trial.",
            tier="documented",
            cite="wiki/fees",
            claim=_claim(2.0),
            valid_at=JAN,
        )
    )
    store.fact(history).invalid_at = MAR  # a closed interval states history

    findings = {f.fact_id: f.rule for f in stale_findings(store)}
    assert findings == {by_claim: "claim", by_date: "lastmodified"}
    assert {f.id for f in stale_since(store, datetime(2026, 2, 1, tzinfo=UTC))} == {
        by_claim,
        by_date,
    }
    assert stale_since(store, MAY) == []


def test_page_newer_than_the_code_is_not_stale():
    store = _store()
    store.register_document(Document("wiki/fees", "wiki", "wiki", "4", lastmodified=MAY))
    store.register_document(Document("code/ticketbox/fees.py", "repo", "code", "s", MAR))
    store.upsert_fact(
        fact(
            "Late returns are charged after 2 hours.",
            tier="documented",
            cite="wiki/fees",
            valid_at=MAY,
        )
    )
    store.upsert_fact(fact("Late returns are charged after 3 hours.", valid_at=MAR))
    assert stale_findings(store) == []
