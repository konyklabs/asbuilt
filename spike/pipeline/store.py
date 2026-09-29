"""The write-side store interface (D-013): what every arm's engine implements,
and what ``lift.py``, ``contradict.py`` and ``stale.py`` are written against.

Fact identity. A fact's id is stable across re-ingest: ``base_fact_id`` hashes
its claim key (the resolved claim entity and the attribute, when the fact
carries a claim) plus its normalised statement. The same statement arriving
again from another source merges into the same row (``merge_into``): its
citations and entities are unioned, ``valid_at`` keeps the earliest value,
and the tier follows the rule below. A statement that stopped holding
(``invalid_at`` set by ``supersede``) and later holds again (the member's
free minutes were 30, then 45, then 30) gets a new *episode* of the same base
id (``<base>.<n>``) rather than reopening the closed interval: one row, one
world-time interval.

Tier on merge. The test connector owns the ``executed``/``code`` tiers,
including demotion, so an incoming ``executed`` or ``code`` tier replaces the
stored one; an incoming ``documented`` fact never lowers a stored one (a page
agreeing with a passing test adds a citation, not a weaker tier).

Two clocks (Graphiti's shape, D-013). ``valid_at``/``invalid_at`` are world
time: when the statement held. ``created_at``/``expired_at`` are stored time,
set by the store's own clock: ``snapshot(name)`` records a point in stored
time and every read takes ``as_of`` — a snapshot is never a copy.
``supersede`` closes the old fact in world time only; the record that it held
until then stays true, so ``explain`` still returns it with its ``valid_to``.
``expire`` retracts a record in stored time (a re-extracted document no longer
states it).

``MemoryStore`` implements the interface in pure Python for the unit tests;
``prototypes/b_postgres/store.py`` implements it over Postgres + pgvector.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from bench.protocol import Citation

TIERS = ("executed", "code", "documented")
TIER_RANK = {"executed": 3, "code": 2, "documented": 1}
CONNECTOR_TIERS = frozenset({"executed", "code"})
HUB_KINDS = ("service", "team")  # never expanded through in a traversal


# ------------------------------------------------------------------ records


@dataclass(frozen=True)
class StoredClaim:
    """A structured claim with its entity already resolved to a row id."""

    entity_id: str
    attribute: str
    value: float | str
    unit: str | None = None


@dataclass
class StoredFact:
    statement: str
    category: str
    tier: str
    entity_ids: tuple[str, ...]
    citations: tuple[Citation, ...]
    detail: str = ""
    claim: StoredClaim | None = None
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    source_key: str | None = None  # the extractor's origin, e.g. "test:<node id>"
    confidence: float | None = None
    embedding: list[float] | None = None
    # Set by the store:
    id: str | None = None
    base_id: str | None = None
    episode: int = 0
    created_at: datetime | None = None
    expired_at: datetime | None = None
    superseded_by: str | None = None


@dataclass
class Entity:
    id: str
    name: str
    kind: str
    aliases: tuple[str, ...] = ()
    embedding: list[float] | None = None


@dataclass(frozen=True)
class Document:
    id: str  # wiki/<slug>, doc/<id>, ticket/<KEY>, pull/<n>, code/<path>, run/<id>
    source: str  # wiki | docs | tickets | pulls | repo | runs
    kind: str  # the id's prefix
    version: str | None = None
    lastmodified: datetime | None = None
    title: str | None = None
    content_hash: str | None = None


@dataclass
class StoredContradiction:
    id: str
    a: str
    b: str
    label: str  # supports | refutes
    winner: str | None
    kind: str  # claim | prose | run
    opened_at: datetime | None
    resolved_at: datetime | None = None
    reason: str | None = None
    created_at: datetime | None = None


# ------------------------------------------------------------ pure helpers


def aware(dt: datetime | None) -> datetime | None:
    """A naive datetime is read as UTC; every stored datetime is aware."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def later(a: datetime | None, b: datetime | None) -> bool:
    """a > b, with None as the beginning of time on either side."""
    if a is None:
        return False
    if b is None:
        return True
    return aware(a) > aware(b)


def _min_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if aware(a) <= aware(b) else b


def normalize_statement(statement: str) -> str:
    text = re.sub(r"\s+", " ", statement.strip().lower())
    return text.rstrip(" .")


def normalize_attribute(attribute: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(attribute).lower()).strip("_")


_UNIT_ALIASES = {
    "usd": "usd",
    "$": "usd",
    "dollar": "usd",
    "dollars": "usd",
    "minute": "minute",
    "minutes": "minute",
    "min": "minute",
    "day": "day",
    "days": "day",
    "hour": "hour",
    "hours": "hour",
    "second": "second",
    "seconds": "second",
    "percent": "percent",
    "%": "percent",
    "count": "count",
    "times": "count",
    "clock": "clock",
}


def normalize_unit(unit: object) -> str | None:
    if unit is None:
        return None
    text = str(unit).strip().lower()
    if not text or text in ("none", "null"):
        return None
    return _UNIT_ALIASES.get(text, text)


_NUMERIC_VALUE = re.compile(r"\$?\s*(-?\d+(?:\.\d+)?)\s*(?:%|usd)?")


def normalize_claim_value(value: object) -> float | str:
    """Numbers (and money strings like "$150.00") become floats, so 150,
    150.0 and "$150.00" are one value; anything else is lowercased text."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().lower().replace(",", "")
    match = _NUMERIC_VALUE.fullmatch(text)
    if match:
        return float(match.group(1))
    return text


def claims_comparable(a: StoredClaim, b: StoredClaim) -> bool:
    """The join key (D-013): same resolved entity, same attribute, same unit
    (a missing unit compares with any)."""
    if a.entity_id != b.entity_id or a.attribute != b.attribute:
        return False
    return a.unit is None or b.unit is None or a.unit == b.unit


def claims_conflict(a: StoredClaim, b: StoredClaim) -> bool:
    if not claims_comparable(a, b):
        return False
    if isinstance(a.value, float) and isinstance(b.value, float):
        return not math.isclose(a.value, b.value, rel_tol=1e-9, abs_tol=1e-9)
    return str(a.value) != str(b.value)


def display_value(value: float | str) -> float | int | str:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def base_fact_id(statement: str, claim: StoredClaim | None) -> str:
    key = f"{claim.entity_id}|{claim.attribute}|" if claim is not None else "||"
    digest = hashlib.sha1((key + normalize_statement(statement)).encode()).hexdigest()
    return "f-" + digest[:16]


def episode_fact_id(base: str, episode: int) -> str:
    return base if episode == 0 else f"{base}.{episode}"


def contradiction_id(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return "x-" + hashlib.sha1(f"{x}|{y}".encode()).hexdigest()[:16]


def document_kind(document_id: str) -> str:
    return document_id.split("/", 1)[0]


_SOURCE_OF_KIND = {
    "wiki": "wiki",
    "doc": "docs",
    "ticket": "tickets",
    "pull": "pulls",
    "code": "repo",
    "run": "runs",
}


def source_of(document_id: str) -> str:
    return _SOURCE_OF_KIND.get(document_kind(document_id), "other")


def _union(a: Iterable, b: Iterable) -> tuple:
    out: list = []
    for item in (*a, *b):
        if item not in out:
            out.append(item)
    return tuple(out)


def merge_into(existing: StoredFact, incoming: StoredFact) -> StoredFact:
    tier = incoming.tier if incoming.tier in CONNECTOR_TIERS else existing.tier
    confidences = [c for c in (existing.confidence, incoming.confidence) if c is not None]
    return replace(
        existing,
        tier=tier,
        citations=_union(existing.citations, incoming.citations),
        entity_ids=_union(existing.entity_ids, incoming.entity_ids),
        valid_at=_min_dt(existing.valid_at, incoming.valid_at),
        detail=incoming.detail or existing.detail,
        confidence=max(confidences) if confidences else None,
        embedding=existing.embedding or incoming.embedding,
        source_key=existing.source_key or incoming.source_key,
    )


def plan_upsert(
    episodes: Sequence[StoredFact], incoming: StoredFact
) -> tuple[str, str, int, StoredFact | None]:
    """(id, base id, episode, the row to merge into or None for a new row)."""
    base = base_fact_id(incoming.statement, incoming.claim)
    if not episodes:
        return base, base, 0, None
    latest = max(episodes, key=lambda f: f.episode)
    closed = latest.expired_at is not None or (
        latest.invalid_at is not None
        and incoming.valid_at is not None
        and not later(latest.invalid_at, incoming.valid_at)
    )
    if closed:
        episode = latest.episode + 1
        return episode_fact_id(base, episode), base, episode, None
    return latest.id or base, base, latest.episode, latest


def winner_of(a: StoredFact, b: StoredFact) -> StoredFact:
    """D-013's policy: executed > code > documented, then recency (the later
    valid_at, then the later stored record)."""
    ra, rb = TIER_RANK.get(a.tier, 0), TIER_RANK.get(b.tier, 0)
    if ra != rb:
        return a if ra > rb else b
    if later(a.valid_at, b.valid_at):
        return a
    if later(b.valid_at, a.valid_at):
        return b
    return a if later(a.created_at, b.created_at) else b


def overlaps(a: StoredFact, b: StoredFact) -> bool:
    """Do the two world-time intervals [valid_at, invalid_at) intersect?"""
    a_starts_before_b_ends = b.invalid_at is None or later(b.invalid_at, a.valid_at)
    b_starts_before_a_ends = a.invalid_at is None or later(a.invalid_at, b.valid_at)
    return a_starts_before_b_ends and b_starts_before_a_ends


def live(fact: StoredFact, as_of: datetime | None) -> bool:
    """Is the record present in stored time at `as_of` (None: now)?"""
    if as_of is None:
        return fact.expired_at is None
    as_of = aware(as_of)
    if fact.created_at is not None and aware(fact.created_at) > as_of:
        return False
    return fact.expired_at is None or aware(fact.expired_at) > as_of


def held_after(fact: StoredFact, since: datetime | None) -> bool:
    """Did the statement hold at some point after `since` (world time)?"""
    if since is None:
        return True
    return fact.invalid_at is None or later(fact.invalid_at, since)


_WORD = re.compile(r"[a-z0-9$%.]+")
STOPWORDS = frozenset(
    "a an and are as at be by does do for from how in is it its of on or that the this to "
    "what when where which who whom why with without within than then there their"
    " any not can".split()
)


def terms(text: str) -> list[str]:
    out = []
    for raw in _WORD.findall(text.lower()):
        word = raw.strip(".")
        if not word or word in STOPWORDS:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------- interface


@runtime_checkable
class StoreInterface(Protocol):
    """The write side (D-013: upsert fact, supersede, link contradiction,
    query by entity, time, text and vector) plus the entity and document
    registry the pipeline needs to use it."""

    def reset(self) -> None: ...

    # documents
    def register_document(self, doc: Document) -> bool: ...
    def document(self, document_id: str) -> Document | None: ...
    def documents(self) -> list[Document]: ...

    # entities
    def upsert_entity(self, entity: Entity) -> str: ...
    def add_alias(self, entity_id: str, alias: str) -> None: ...
    def add_relation(self, src: str, dst: str, kind: str) -> None: ...
    def entity(self, entity_id: str) -> Entity | None: ...
    def entities(self) -> list[Entity]: ...
    def entity_by_name(self, name: str) -> Entity | None: ...
    def entity_by_alias(self, alias: str) -> Entity | None: ...
    def entities_by_folded(self, folded: str) -> list[Entity]: ...
    def nearest_entity(
        self, vector: Sequence[float], kind: str | None = None
    ) -> tuple[Entity, float] | None: ...
    def related_entities(
        self, entity_id: str, depth: int = 1, exclude_kinds: Sequence[str] = HUB_KINDS
    ) -> list[str]: ...

    # facts
    def upsert_fact(self, fact: StoredFact) -> str: ...
    def fact(self, fact_id: str) -> StoredFact | None: ...
    def supersede(self, old_id: str, new_id: str, at: datetime | None) -> None: ...
    def expire(self, fact_id: str) -> None: ...
    def retract_citation(self, fact_id: str, document_id: str) -> None: ...
    def facts_by_source(self, source_key: str, current_only: bool = True) -> list[StoredFact]: ...
    def facts_by_claim_key(self, entity_id: str, attribute: str) -> list[StoredFact]: ...
    def facts_citing(self, document_id: str) -> list[StoredFact]: ...
    def all_facts(self, as_of: datetime | None = None) -> list[StoredFact]: ...
    def query_by_entity(
        self, entity_id: str, as_of: datetime | None = None, depth: int = 0
    ) -> list[StoredFact]: ...
    def query_text(
        self,
        query: str,
        as_of: datetime | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[StoredFact, float]]: ...
    def query_vector(
        self,
        vector: Sequence[float],
        as_of: datetime | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[StoredFact, float]]: ...
    def facts_since(self, ts: datetime, as_of: datetime | None = None) -> list[StoredFact]: ...

    # contradictions
    def link_contradiction(
        self,
        a: str,
        b: str,
        label: str,
        winner: str | None,
        opened_at: datetime | None,
        kind: str = "claim",
        reason: str | None = None,
    ) -> str: ...
    def resolve_contradiction(self, contradiction_id: str, at: datetime | None) -> None: ...
    def query_contradictions(
        self, entity_id: str | None = None, as_of: datetime | None = None
    ) -> list[StoredContradiction]: ...

    # stored time
    def snapshot(self, name: str, step: str | None = None) -> datetime: ...
    def snapshot_at(self, name: str) -> datetime | None: ...
    def last_step(self) -> str | None: ...


class BaseStore:
    """The identity rules, shared: a concrete store supplies `_episodes`,
    `_insert_fact` and `_update_fact`, and gets `upsert_fact` from here."""

    def _episodes(self, base_id: str) -> list[StoredFact]:
        raise NotImplementedError

    def _insert_fact(self, fact: StoredFact) -> None:
        raise NotImplementedError

    def _update_fact(self, fact: StoredFact) -> None:
        raise NotImplementedError

    def upsert_fact(self, fact: StoredFact) -> str:
        if not fact.citations:
            raise ValueError("a fact without a citation is a bug (AGENTS.md)")
        fact = replace(fact, valid_at=aware(fact.valid_at), invalid_at=aware(fact.invalid_at))
        base = base_fact_id(fact.statement, fact.claim)
        fact_id, base, episode, target = plan_upsert(self._episodes(base), fact)
        if target is None:
            self._insert_fact(replace(fact, id=fact_id, base_id=base, episode=episode))
        else:
            self._update_fact(merge_into(target, fact))
        return fact_id


# ------------------------------------------------------------ memory store


@dataclass
class MemoryStore(BaseStore):
    """The interface over dicts, for unit tests; same rules as Postgres."""

    _facts: dict[str, StoredFact] = field(default_factory=dict)
    _entities: dict[str, Entity] = field(default_factory=dict)
    _relations: set[tuple[str, str, str]] = field(default_factory=set)
    _documents: dict[str, Document] = field(default_factory=dict)
    _contradictions: dict[str, StoredContradiction] = field(default_factory=dict)
    _snapshots: dict[str, tuple[datetime, str | None]] = field(default_factory=dict)
    _clock: datetime | None = None

    def _now(self) -> datetime:
        now = datetime.now(UTC)
        if self._clock is not None and now <= self._clock:
            now = self._clock + timedelta(microseconds=1)
        self._clock = now
        return now

    def reset(self) -> None:
        self._facts.clear()
        self._entities.clear()
        self._relations.clear()
        self._documents.clear()
        self._contradictions.clear()
        self._snapshots.clear()

    # documents
    def register_document(self, doc: Document) -> bool:
        old = self._documents.get(doc.id)
        self._documents[doc.id] = doc
        return old is None or old.version != doc.version or old.content_hash != doc.content_hash

    def document(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    def documents(self) -> list[Document]:
        return sorted(self._documents.values(), key=lambda d: d.id)

    def _ensure_documents(self, citations: Iterable[Citation]) -> None:
        for citation in citations:
            if citation.document not in self._documents:
                self._documents[citation.document] = Document(
                    id=citation.document,
                    source=source_of(citation.document),
                    kind=document_kind(citation.document),
                    version=citation.version,
                )

    # entities
    def upsert_entity(self, entity: Entity) -> str:
        existing = self._entities.get(entity.id)
        if existing is None:
            self._entities[entity.id] = replace(entity)
        else:
            existing.aliases = _union(existing.aliases, entity.aliases)
        return entity.id

    def add_alias(self, entity_id: str, alias: str) -> None:
        entity = self._entities[entity_id]
        if alias != entity.name and alias not in entity.aliases:
            entity.aliases = (*entity.aliases, alias)

    def add_relation(self, src: str, dst: str, kind: str) -> None:
        if src != dst:
            self._relations.add((src, dst, kind))

    def entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    def entity_by_name(self, name: str) -> Entity | None:
        key = name.strip().lower()
        return next((e for e in self._entities.values() if e.name.lower() == key), None)

    def entity_by_alias(self, alias: str) -> Entity | None:
        key = alias.strip().lower()
        return next(
            (e for e in self._entities.values() if key in (a.lower() for a in e.aliases)), None
        )

    def entities_by_folded(self, folded: str) -> list[Entity]:
        from pipeline.resolve import fold

        return [
            e
            for e in self._entities.values()
            if fold(e.name) == folded or any(fold(a) == folded for a in e.aliases)
        ]

    def nearest_entity(
        self, vector: Sequence[float], kind: str | None = None
    ) -> tuple[Entity, float] | None:
        best: tuple[Entity, float] | None = None
        for entity in self._entities.values():
            if entity.embedding is None or (kind is not None and entity.kind != kind):
                continue
            sim = cosine(vector, entity.embedding)
            if best is None or sim > best[1]:
                best = (entity, sim)
        return best

    def related_entities(
        self, entity_id: str, depth: int = 1, exclude_kinds: Sequence[str] = HUB_KINDS
    ) -> list[str]:
        seen = {entity_id}
        frontier = [entity_id]
        for _ in range(depth):
            nxt = []
            for node in frontier:
                entity = self._entities.get(node)
                if node != entity_id and entity is not None and entity.kind in exclude_kinds:
                    continue
                for src, dst, _kind in self._relations:
                    other = dst if src == node else src if dst == node else None
                    if other is not None and other not in seen:
                        other_entity = self._entities.get(other)
                        if other_entity is not None and other_entity.kind in exclude_kinds:
                            continue
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
        return [entity_id, *sorted(seen - {entity_id})]

    # facts
    def _episodes(self, base_id: str) -> list[StoredFact]:
        return [f for f in self._facts.values() if f.base_id == base_id]

    def _insert_fact(self, fact: StoredFact) -> None:
        self._ensure_documents(fact.citations)
        self._facts[fact.id] = replace(fact, created_at=self._now())

    def _update_fact(self, fact: StoredFact) -> None:
        self._ensure_documents(fact.citations)
        self._facts[fact.id] = fact

    def fact(self, fact_id: str) -> StoredFact | None:
        return self._facts.get(fact_id)

    def supersede(self, old_id: str, new_id: str, at: datetime | None) -> None:
        old = self._facts[old_id]
        if old_id == new_id:
            return
        at = aware(at)
        if old.invalid_at is None or (at is not None and later(old.invalid_at, at)):
            old.invalid_at = at
        if old.superseded_by is None:
            old.superseded_by = new_id

    def expire(self, fact_id: str) -> None:
        fact = self._facts[fact_id]
        if fact.expired_at is None:
            fact.expired_at = self._now()

    def retract_citation(self, fact_id: str, document_id: str) -> None:
        fact = self._facts[fact_id]
        fact.citations = tuple(c for c in fact.citations if c.document != document_id)
        if not fact.citations:
            self.expire(fact_id)

    def facts_by_source(self, source_key: str, current_only: bool = True) -> list[StoredFact]:
        return [
            f
            for f in self._facts.values()
            if f.source_key == source_key
            and f.expired_at is None
            and (not current_only or f.invalid_at is None)
        ]

    def facts_by_claim_key(self, entity_id: str, attribute: str) -> list[StoredFact]:
        return [
            f
            for f in self._facts.values()
            if f.expired_at is None
            and f.claim is not None
            and f.claim.entity_id == entity_id
            and f.claim.attribute == attribute
        ]

    def facts_citing(self, document_id: str) -> list[StoredFact]:
        return [
            f
            for f in self._facts.values()
            if f.expired_at is None and any(c.document == document_id for c in f.citations)
        ]

    def all_facts(self, as_of: datetime | None = None) -> list[StoredFact]:
        return [f for f in self._facts.values() if live(f, as_of)]

    def query_by_entity(
        self, entity_id: str, as_of: datetime | None = None, depth: int = 0
    ) -> list[StoredFact]:
        wanted = set(self.related_entities(entity_id, depth)) if depth else {entity_id}
        return [
            f
            for f in self._facts.values()
            if live(f, as_of)
            and (
                wanted & set(f.entity_ids) or (f.claim is not None and f.claim.entity_id in wanted)
            )
        ]

    def _filtered(
        self, as_of: datetime | None, category: str | None, since: datetime | None
    ) -> list[StoredFact]:
        return [
            f
            for f in self._facts.values()
            if live(f, as_of)
            and (category is None or f.category == category)
            and held_after(f, since)
        ]

    def query_text(
        self,
        query: str,
        as_of: datetime | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[StoredFact, float]]:
        wanted = set(terms(query))
        if not wanted:
            return []
        scored = []
        for fact in self._filtered(as_of, category, since):
            have = set(terms(f"{fact.statement} {fact.detail}"))
            score = len(wanted & have) / len(wanted)
            if score > 0:
                scored.append((fact, score))
        scored.sort(key=lambda pair: (-pair[1], pair[0].id or ""))
        return scored[:limit]

    def query_vector(
        self,
        vector: Sequence[float],
        as_of: datetime | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[StoredFact, float]]:
        scored = [
            (fact, cosine(vector, fact.embedding))
            for fact in self._filtered(as_of, category, since)
            if fact.embedding is not None
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0].id or ""))
        return scored[:limit]

    def facts_since(self, ts: datetime, as_of: datetime | None = None) -> list[StoredFact]:
        return [
            f
            for f in self._facts.values()
            if live(f, as_of) and f.valid_at is not None and not later(ts, f.valid_at)
        ]

    # contradictions
    def link_contradiction(
        self,
        a: str,
        b: str,
        label: str,
        winner: str | None,
        opened_at: datetime | None,
        kind: str = "claim",
        reason: str | None = None,
    ) -> str:
        cid = contradiction_id(a, b)
        existing = self._contradictions.get(cid)
        if existing is None:
            self._contradictions[cid] = StoredContradiction(
                id=cid,
                a=a,
                b=b,
                label=label,
                winner=winner,
                kind=kind,
                opened_at=aware(opened_at),
                reason=reason,
                created_at=self._now(),
            )
        else:
            existing.label, existing.winner, existing.reason = label, winner, reason
            existing.opened_at = _min_dt(existing.opened_at, aware(opened_at))
            existing.resolved_at = None
        return cid

    def resolve_contradiction(self, contradiction_id: str, at: datetime | None) -> None:
        contradiction = self._contradictions[contradiction_id]
        if contradiction.resolved_at is None:
            contradiction.resolved_at = aware(at) or self._now()

    def query_contradictions(
        self, entity_id: str | None = None, as_of: datetime | None = None
    ) -> list[StoredContradiction]:
        out = []
        for contradiction in self._contradictions.values():
            if as_of is not None and contradiction.created_at is not None:
                if aware(contradiction.created_at) > aware(as_of):
                    continue
            if entity_id is not None:
                involved: set[str] = set()
                for fid in (contradiction.a, contradiction.b):
                    fact = self._facts.get(fid)
                    if fact is not None:
                        involved |= set(fact.entity_ids)
                        if fact.claim is not None:
                            involved.add(fact.claim.entity_id)
                if entity_id not in involved:
                    continue
            out.append(contradiction)
        out.sort(key=lambda c: (c.resolved_at is not None, c.id))
        return out

    # stored time
    def snapshot(self, name: str, step: str | None = None) -> datetime:
        at = self._now()
        self._snapshots[name] = (at, step)
        return at

    def snapshot_at(self, name: str) -> datetime | None:
        entry = self._snapshots.get(name)
        return entry[0] if entry else None

    def last_step(self) -> str | None:
        stepped = [(at, step) for at, step in self._snapshots.values() if step is not None]
        return max(stepped)[1] if stepped else None
