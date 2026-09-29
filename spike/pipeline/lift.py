"""Applies the test connector's output at one step to a store: its tiers,
its contradiction candidates, and the supersessions they imply (D-013's
provenance rule; the tier itself is the connector's, ``connectors/tests/
lift.py``, never recomputed here).

Called once per history step, in commit order. For every connector fact:
resolve its entities and claim entity, upsert it (``store.upsert_fact``:
the same statement at a later step merges, adding that step's run and code
citations; a demotion to ``code`` replaces ``executed``). Then three
supersession rules, each closing the older fact in world time at the newer
one's ``valid_at``:

1. **Same test, new statement.** A test node that carried fact X at the
   previous step and carries Y now.
2. **Same claim key, new value.** A current ``code``/``executed`` fact whose
   claim (resolved entity, attribute, unit) has a different value from a
   fact that became valid later — e.g. a constant changed at a commit.
3. **Replaced test.** A test node gone at this step whose file gained a new
   node at this step with a statement of the same shape (word overlap of at
   least ``REPLACEMENT_OVERLAP``) — ``test_x_30`` replaced by ``test_x_45``.

A connector contradiction candidate (a failing run at this step against what
the code now says) links its two facts as a ``run`` contradiction, winner
the code, opened at the candidate's ``opened_step``; a ``run`` contradiction
whose test is no longer a candidate at a later step is resolved there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bench.protocol import Citation
from pipeline.embed import Embedder
from pipeline.history import GitHistory
from pipeline.resolve import Resolver
from pipeline.store import (
    CONNECTOR_TIERS,
    HUB_KINDS,
    StoredClaim,
    StoredFact,
    StoreInterface,
    claims_conflict,
    later,
    normalize_attribute,
    normalize_claim_value,
    normalize_unit,
    terms,
)

REPLACEMENT_OVERLAP = 0.6


@dataclass
class LiftReport:
    facts: int = 0
    superseded: int = 0
    contradictions_opened: int = 0
    contradictions_resolved: int = 0


def node_of(raw: dict[str, Any]) -> str | None:
    """The test node id from a connector fact's own code citation."""
    for citation in raw.get("citations") or []:
        document = citation.get("document", "")
        if document.startswith("code/") and citation.get("location"):
            return f"{document[len('code/') :]}::{citation['location']}"
    return None


def to_citations(raw: list[dict[str, Any]] | None) -> tuple[Citation, ...]:
    return tuple(
        Citation(document=c["document"], location=c.get("location"), version=c.get("version"))
        for c in raw or []
        if c.get("document")
    )


def to_claim(raw: dict[str, Any] | None, resolver: Resolver) -> StoredClaim | None:
    if not raw or not raw.get("entity") or raw.get("value") is None:
        return None
    entity_id = resolver.resolve(str(raw["entity"]))
    if entity_id is None:
        return None
    return StoredClaim(
        entity_id=entity_id,
        attribute=normalize_attribute(raw.get("attribute") or "value"),
        value=normalize_claim_value(raw["value"]),
        unit=normalize_unit(raw.get("unit")),
    )


def overlap(a: str, b: str) -> float:
    ta, tb = set(terms(a)), set(terms(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def link_entities(store: StoreInterface, entity_ids: tuple[str, ...]) -> None:
    """Non-hub entities are ``part_of`` every hub (service, team) the same
    fact names, and ``related`` to each other."""
    entities = [store.entity(e) for e in entity_ids]
    hubs = [e.id for e in entities if e is not None and e.kind in HUB_KINDS]
    others = [e.id for e in entities if e is not None and e.kind not in HUB_KINDS]
    for other in others:
        for hub in hubs:
            store.add_relation(other, hub, "part_of")
    for i, a in enumerate(others):
        for b in others[i + 1 :]:
            store.add_relation(a, b, "related")


def fact_from_connector(
    raw: dict[str, Any],
    resolver: Resolver,
    embedder: Embedder,
    history: GitHistory,
    default_valid: datetime,
    source_key: str | None,
) -> StoredFact:
    entity_ids: list[str] = []
    for name in raw.get("entities") or []:
        entity_id = resolver.resolve(str(name))
        if entity_id is not None and entity_id not in entity_ids:
            entity_ids.append(entity_id)
    claim = to_claim(raw.get("claim"), resolver)
    if claim is not None and claim.entity_id not in entity_ids:
        entity_ids.append(claim.entity_id)
    valid_step = raw.get("valid_from")
    valid_at = history.date(valid_step) if valid_step in history.step_ids else default_valid
    statement = raw["statement"]
    detail = raw.get("detail") or ""
    return StoredFact(
        statement=statement,
        category=raw.get("category") or "business-logic",
        tier=raw.get("tier") or "code",
        entity_ids=tuple(entity_ids),
        citations=to_citations(raw.get("citations")),
        detail=detail,
        claim=claim,
        valid_at=valid_at,
        source_key=source_key,
        embedding=embedder.embed([f"{statement} {detail}".strip()])[0],
    )


def _supersede_by_claim(store: StoreInterface, fact_id: str, report: LiftReport) -> None:
    fact = store.fact(fact_id)
    if fact is None or fact.claim is None or fact.tier not in CONNECTOR_TIERS:
        return
    for other in store.facts_by_claim_key(fact.claim.entity_id, fact.claim.attribute):
        if (
            other.id != fact.id
            and other.tier in CONNECTOR_TIERS
            and other.invalid_at is None
            and other.claim is not None
            and claims_conflict(other.claim, fact.claim)
            and later(fact.valid_at, other.valid_at)
        ):
            store.supersede(other.id, fact.id, fact.valid_at)
            report.superseded += 1


def apply_step(
    store: StoreInterface,
    resolver: Resolver,
    embedder: Embedder,
    output: dict[str, Any],
    history: GitHistory,
) -> LiftReport:
    report = LiftReport()
    step = output["step"]
    at = history.date(step)
    previous = {
        f.source_key: f
        for f in store.all_facts()
        if f.source_key and f.source_key.startswith("test:") and f.invalid_at is None
    }

    current: dict[str, str] = {}  # node -> fact id at this step
    touched: list[str] = []
    for raw in output.get("facts") or []:
        node = node_of(raw)
        key = f"test:{node}" if node else None
        fact = fact_from_connector(raw, resolver, embedder, history, at, key)
        fact_id = store.upsert_fact(fact)
        link_entities(store, fact.entity_ids)
        report.facts += 1
        touched.append(fact_id)
        if node is None:
            continue
        current[node] = fact_id
        prior = previous.get(key)
        if prior is not None and prior.id != fact_id:  # rule 1
            store.supersede(prior.id, fact_id, at)
            report.superseded += 1

    open_nodes: set[str] = set()
    for candidate in output.get("contradiction_candidates") or []:
        node = candidate["node_id"]
        open_nodes.add(node)
        opened = history.date(candidate.get("opened_step") or step)
        a = fact_from_connector(candidate["a"], resolver, embedder, history, at, f"test:{node}")
        b_raw = candidate["b"]
        b_cite = next(iter(b_raw.get("citations") or []), {})
        b = fact_from_connector(
            b_raw,
            resolver,
            embedder,
            history,
            opened,
            f"code:{b_cite.get('document', '')}#{b_cite.get('location', '')}",
        )
        a_id, b_id = store.upsert_fact(a), store.upsert_fact(b)
        link_entities(store, a.entity_ids)
        link_entities(store, b.entity_ids)
        touched.append(b_id)
        store.link_contradiction(
            a_id,
            b_id,
            "refutes",
            winner=b_id,
            opened_at=opened,
            kind="run",
            reason=candidate.get("reason"),
        )
        report.contradictions_opened += 1

    for fact_id in touched:  # rule 2
        _supersede_by_claim(store, fact_id, report)

    added = {n: fid for n, fid in current.items() if f"test:{n}" not in previous}
    for key, gone in previous.items():  # rule 3
        node = key[len("test:") :]
        refreshed = store.fact(gone.id)
        if node in current or refreshed is None or refreshed.invalid_at is not None:
            continue
        test_file = node.split("::", 1)[0]
        best: tuple[float, str] | None = None
        for new_node, new_id in added.items():
            if new_node.split("::", 1)[0] != test_file:
                continue
            new_fact = store.fact(new_id)
            score = overlap(gone.statement, new_fact.statement) if new_fact else 0.0
            if score >= REPLACEMENT_OVERLAP and (best is None or score > best[0]):
                best = (score, new_id)
        if best is not None:
            store.supersede(gone.id, best[1], at)
            report.superseded += 1

    for contradiction in store.query_contradictions():
        if contradiction.kind != "run" or contradiction.resolved_at is not None:
            continue
        a_fact = store.fact(contradiction.a)
        node = (a_fact.source_key or "")[len("test:") :] if a_fact else ""
        if node not in open_nodes:
            store.resolve_contradiction(contradiction.id, at)
            report.contradictions_resolved += 1
    return report
