"""``StoreInterface`` over Postgres + pgvector, with psycopg 3 (the
``pipeline`` dependency group). The only module in stack B that imports a
driver (AGENTS.md: the engine sits behind one interface).

Connection: ``ASBUILT_PG_DSN`` when set, else
``postgresql://asbuilt@localhost:$ASBUILT_PG_PORT/asbuilt`` (port default
55432, the compose file's). Tables live in the schema ``ASBUILT_PG_SCHEMA``
(default ``asbuilt``); ``reset()`` drops and re-applies ``schema.sql``.
Vectors travel as pgvector's text literal (``'[x,y,...]'::vector``), so no
adapter package is needed. Traversal is a recursive CTE
(``related_entities``); text search is the ``tsv`` column's GIN index with the
query's lexemes OR-ed together; vector search is cosine distance on an HNSW
index. The identity, episode and merge rules are ``pipeline.store``'s, shared
with ``MemoryStore``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from bench.protocol import Citation
from pipeline.resolve import fold
from pipeline.store import (
    HUB_KINDS,
    BaseStore,
    Document,
    Entity,
    StoredClaim,
    StoredContradiction,
    StoredFact,
    aware,
    contradiction_id,
    document_kind,
    source_of,
)

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
DEFAULT_PORT = 55432


def dsn_from_env() -> str:
    dsn = os.environ.get("ASBUILT_PG_DSN")
    if dsn:
        return dsn
    port = os.environ.get("ASBUILT_PG_PORT", str(DEFAULT_PORT))
    return f"postgresql://asbuilt@localhost:{port}/asbuilt"


def vector_literal(vector: Sequence[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


_FACT_COLUMNS = """
    f.id, f.base_id, f.episode, f.statement, f.detail, f.category, f.tier, f.confidence,
    f.claim_entity, f.claim_attribute, f.claim_value, f.claim_number, f.claim_unit,
    f.source_key, f.valid_at, f.invalid_at, f.created_at, f.expired_at, f.superseded_by,
    COALESCE((SELECT array_agg(fe.entity_id ORDER BY fe.position)
              FROM fact_entity fe WHERE fe.fact_id = f.id), '{}') AS entity_ids,
    COALESCE((SELECT json_agg(json_build_array(c.document_id, c.location, c.version)
                              ORDER BY c.position)
              FROM citation c WHERE c.fact_id = f.id), '[]'::json) AS citations
"""

_LIVE = """(
    (%(as_of)s::timestamptz IS NULL AND f.expired_at IS NULL)
    OR (%(as_of)s::timestamptz IS NOT NULL AND f.created_at <= %(as_of)s::timestamptz
        AND (f.expired_at IS NULL OR f.expired_at > %(as_of)s::timestamptz))
)"""
_FILTERS = """
    AND (%(category)s::text IS NULL OR f.category = %(category)s::text)
    AND (%(since)s::timestamptz IS NULL OR f.invalid_at IS NULL
         OR f.invalid_at > %(since)s::timestamptz)
"""


def _row_to_fact(row: dict[str, Any]) -> StoredFact:
    claim = None
    if row["claim_entity"] is not None:
        value: float | str = (
            float(row["claim_number"]) if row["claim_number"] is not None else row["claim_value"]
        )
        claim = StoredClaim(
            entity_id=row["claim_entity"],
            attribute=row["claim_attribute"],
            value=value,
            unit=row["claim_unit"],
        )
    raw_citations = row["citations"]
    if isinstance(raw_citations, str):
        raw_citations = json.loads(raw_citations)
    citations = tuple(
        Citation(document=d, location=loc or None, version=ver or None)
        for d, loc, ver in raw_citations
    )
    return StoredFact(
        statement=row["statement"],
        category=row["category"],
        tier=row["tier"],
        entity_ids=tuple(row["entity_ids"] or ()),
        citations=citations,
        detail=row["detail"] or "",
        claim=claim,
        valid_at=row["valid_at"],
        invalid_at=row["invalid_at"],
        source_key=row["source_key"],
        confidence=row["confidence"],
        id=row["id"],
        base_id=row["base_id"],
        episode=row["episode"],
        created_at=row["created_at"],
        expired_at=row["expired_at"],
        superseded_by=row["superseded_by"],
    )


def _row_to_entity(row: dict[str, Any]) -> Entity:
    return Entity(
        id=row["id"], name=row["name"], kind=row["kind"], aliases=tuple(row["aliases"] or ())
    )


class PostgresStore(BaseStore):
    def __init__(self, dsn: str | None = None, schema: str | None = None) -> None:
        self.dsn = dsn or dsn_from_env()
        self.schema = schema or os.environ.get("ASBUILT_PG_SCHEMA", "asbuilt")
        self.conn = psycopg.connect(
            self.dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
        )
        self._ensure_schema()

    # --------------------------------------------------------------- setup

    def _set_path(self) -> None:
        self.conn.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.schema))
        )

    def _ensure_schema(self) -> None:
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        self.conn.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema))
        )
        self._set_path()
        exists = self.conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS ok", (f"{self.schema}.fact",)
        ).fetchone()["ok"]
        if not exists:
            self.conn.execute(SCHEMA_SQL.read_text())

    def reset(self) -> None:
        self.conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
        )
        self._ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def _q(self, query: str, params: Any = None) -> list[dict[str, Any]]:
        cur = self.conn.execute(query, params)
        return cur.fetchall() if cur.description else []

    # ----------------------------------------------------------- documents

    def _ensure_source(self, source: str) -> None:
        self.conn.execute(
            "INSERT INTO source (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (source,)
        )

    def register_document(self, doc: Document) -> bool:
        self._ensure_source(doc.source)
        old = self._q("SELECT version, content_hash FROM document WHERE id = %s", (doc.id,))
        self.conn.execute(
            """
            INSERT INTO document (id, source_id, kind, version, lastmodified, title, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                source_id = EXCLUDED.source_id, kind = EXCLUDED.kind,
                version = EXCLUDED.version, lastmodified = EXCLUDED.lastmodified,
                title = EXCLUDED.title, content_hash = EXCLUDED.content_hash,
                ingested_at = clock_timestamp()
            """,
            (
                doc.id,
                doc.source,
                doc.kind,
                doc.version,
                doc.lastmodified,
                doc.title,
                doc.content_hash,
            ),
        )
        if not old:
            return True
        return old[0]["version"] != doc.version or old[0]["content_hash"] != doc.content_hash

    def _document_from_row(self, row: dict[str, Any]) -> Document:
        return Document(
            id=row["id"],
            source=row["source_id"],
            kind=row["kind"],
            version=row["version"],
            lastmodified=row["lastmodified"],
            title=row["title"],
            content_hash=row["content_hash"],
        )

    def document(self, document_id: str) -> Document | None:
        rows = self._q("SELECT * FROM document WHERE id = %s", (document_id,))
        return self._document_from_row(rows[0]) if rows else None

    def documents(self) -> list[Document]:
        return [self._document_from_row(r) for r in self._q("SELECT * FROM document ORDER BY id")]

    def _ensure_documents(self, citations: Iterable[Citation]) -> None:
        for citation in citations:
            source = source_of(citation.document)
            self._ensure_source(source)
            self.conn.execute(
                """INSERT INTO document (id, source_id, kind, version) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (citation.document, source, document_kind(citation.document), citation.version),
            )

    # ------------------------------------------------------------ entities

    def upsert_entity(self, entity: Entity) -> str:
        folded = sorted({fold(entity.name), *(fold(a) for a in entity.aliases)})
        self.conn.execute(
            """INSERT INTO entity (id, name, kind, aliases, folded, embedding)
               VALUES (%s, %s, %s, %s, %s, %s::vector) ON CONFLICT (id) DO NOTHING""",
            (
                entity.id,
                entity.name,
                entity.kind,
                list(entity.aliases),
                folded,
                vector_literal(entity.embedding),
            ),
        )
        for alias in entity.aliases:
            self.add_alias(entity.id, alias)
        return entity.id

    def add_alias(self, entity_id: str, alias: str) -> None:
        self.conn.execute(
            """
            UPDATE entity SET
                aliases = CASE WHEN lower(name) = lower(%(a)s)
                                 OR EXISTS (SELECT 1 FROM unnest(aliases) x
                                            WHERE lower(x) = lower(%(a)s))
                               THEN aliases ELSE array_append(aliases, %(a)s) END,
                folded = CASE WHEN %(f)s = ANY(folded) THEN folded
                              ELSE array_append(folded, %(f)s) END
            WHERE id = %(id)s
            """,
            {"a": alias, "f": fold(alias), "id": entity_id},
        )

    def add_relation(self, src: str, dst: str, kind: str) -> None:
        if src == dst:
            return
        self.conn.execute(
            """INSERT INTO entity_relation (src, dst, kind) VALUES (%s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (src, dst, kind),
        )

    def entity(self, entity_id: str) -> Entity | None:
        rows = self._q("SELECT id, name, kind, aliases FROM entity WHERE id = %s", (entity_id,))
        return _row_to_entity(rows[0]) if rows else None

    def entities(self) -> list[Entity]:
        return [
            _row_to_entity(r)
            for r in self._q("SELECT id, name, kind, aliases FROM entity ORDER BY id")
        ]

    def entity_by_name(self, name: str) -> Entity | None:
        rows = self._q(
            """SELECT id, name, kind, aliases FROM entity WHERE lower(name) = lower(%s)
               ORDER BY id LIMIT 1""",
            (name.strip(),),
        )
        return _row_to_entity(rows[0]) if rows else None

    def entity_by_alias(self, alias: str) -> Entity | None:
        rows = self._q(
            """SELECT id, name, kind, aliases FROM entity
               WHERE EXISTS (SELECT 1 FROM unnest(aliases) x WHERE lower(x) = lower(%s))
               ORDER BY id LIMIT 1""",
            (alias.strip(),),
        )
        return _row_to_entity(rows[0]) if rows else None

    def entities_by_folded(self, folded: str) -> list[Entity]:
        rows = self._q(
            """SELECT id, name, kind, aliases FROM entity WHERE folded @> ARRAY[%s]::text[]
               ORDER BY id""",
            (folded,),
        )
        return [_row_to_entity(r) for r in rows]

    def nearest_entity(
        self, vector: Sequence[float], kind: str | None = None
    ) -> tuple[Entity, float] | None:
        rows = self._q(
            """
            SELECT id, name, kind, aliases, 1 - (embedding <=> %(v)s::vector) AS sim
            FROM entity
            WHERE embedding IS NOT NULL AND (%(k)s::text IS NULL OR kind = %(k)s::text)
            ORDER BY embedding <=> %(v)s::vector, id LIMIT 1
            """,
            {"v": vector_literal(vector), "k": kind},
        )
        return (_row_to_entity(rows[0]), float(rows[0]["sim"])) if rows else None

    def related_entities(
        self, entity_id: str, depth: int = 1, exclude_kinds: Sequence[str] = HUB_KINDS
    ) -> list[str]:
        rows = self._q(
            """
            WITH RECURSIVE reach(id, depth) AS (
                SELECT %(start)s::text, 0
              UNION
                SELECT nb.id, reach.depth + 1
                FROM reach
                JOIN entity cur ON cur.id = reach.id
                JOIN entity_relation r ON r.src = reach.id OR r.dst = reach.id
                JOIN entity nb ON nb.id = CASE WHEN r.src = reach.id THEN r.dst ELSE r.src END
                WHERE reach.depth < %(depth)s
                  AND NOT (nb.kind = ANY(%(hubs)s))
                  AND (reach.depth = 0 OR NOT (cur.kind = ANY(%(hubs)s)))
            )
            SELECT DISTINCT id FROM reach
            """,
            {"start": entity_id, "depth": depth, "hubs": list(exclude_kinds)},
        )
        others = sorted(r["id"] for r in rows if r["id"] != entity_id)
        return [entity_id, *others]

    # --------------------------------------------------------------- facts

    def _facts(self, where: str, params: Any = None, tail: str = "") -> list[StoredFact]:
        rows = self._q(f"SELECT {_FACT_COLUMNS} FROM fact f WHERE {where} {tail}", params)
        return [_row_to_fact(r) for r in rows]

    def _facts_by_ids(self, ids: Sequence[str]) -> dict[str, StoredFact]:
        if not ids:
            return {}
        return {f.id: f for f in self._facts("f.id = ANY(%s)", (list(ids),))}

    def _episodes(self, base_id: str) -> list[StoredFact]:
        return self._facts("f.base_id = %s", (base_id,), "ORDER BY f.episode")

    def _write_links(self, fact: StoredFact) -> None:
        self._ensure_documents(fact.citations)
        for position, entity_id in enumerate(fact.entity_ids):
            self.conn.execute(
                """INSERT INTO fact_entity (fact_id, entity_id, position) VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (fact.id, entity_id, position),
            )
        for position, citation in enumerate(fact.citations):
            self.conn.execute(
                """INSERT INTO citation (fact_id, document_id, location, version, position)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (
                    fact.id,
                    citation.document,
                    citation.location or "",
                    citation.version or "",
                    position,
                ),
            )

    def _claim_params(self, fact: StoredFact) -> tuple[Any, ...]:
        claim = fact.claim
        if claim is None:
            return (None, None, None, None, None)
        number = claim.value if isinstance(claim.value, float) else None
        text = repr(claim.value) if number is not None else str(claim.value)
        return (claim.entity_id, claim.attribute, text, number, claim.unit)

    def _insert_fact(self, fact: StoredFact) -> None:
        with self.conn.transaction():
            self.conn.execute(
                """
                INSERT INTO fact (id, base_id, episode, statement, detail, category, tier,
                    confidence, claim_entity, claim_attribute, claim_value, claim_number,
                    claim_unit, source_key, valid_at, invalid_at, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::vector)
                """,
                (
                    fact.id,
                    fact.base_id,
                    fact.episode,
                    fact.statement,
                    fact.detail,
                    fact.category,
                    fact.tier,
                    fact.confidence,
                    *self._claim_params(fact),
                    fact.source_key,
                    fact.valid_at,
                    fact.invalid_at,
                    vector_literal(fact.embedding),
                ),
            )
            self._write_links(fact)

    def _update_fact(self, fact: StoredFact) -> None:
        with self.conn.transaction():
            self.conn.execute(
                """
                UPDATE fact SET tier = %s, detail = %s, valid_at = %s, confidence = %s,
                    source_key = COALESCE(source_key, %s),
                    embedding = COALESCE(embedding, %s::vector)
                WHERE id = %s
                """,
                (
                    fact.tier,
                    fact.detail,
                    fact.valid_at,
                    fact.confidence,
                    fact.source_key,
                    vector_literal(fact.embedding),
                    fact.id,
                ),
            )
            self._write_links(fact)

    def fact(self, fact_id: str) -> StoredFact | None:
        found = self._facts("f.id = %s", (fact_id,))
        return found[0] if found else None

    def supersede(self, old_id: str, new_id: str, at: datetime | None) -> None:
        if old_id == new_id:
            return
        self.conn.execute(
            """
            UPDATE fact SET
                invalid_at = CASE WHEN invalid_at IS NULL THEN %(at)s::timestamptz
                                  ELSE LEAST(invalid_at, %(at)s::timestamptz) END,
                superseded_by = COALESCE(superseded_by, %(new)s)
            WHERE id = %(old)s
            """,
            {"at": aware(at), "new": new_id, "old": old_id},
        )

    def expire(self, fact_id: str) -> None:
        self.conn.execute(
            "UPDATE fact SET expired_at = clock_timestamp() WHERE id = %s AND expired_at IS NULL",
            (fact_id,),
        )

    def retract_citation(self, fact_id: str, document_id: str) -> None:
        self.conn.execute(
            "DELETE FROM citation WHERE fact_id = %s AND document_id = %s", (fact_id, document_id)
        )
        left = self._q("SELECT count(*) AS n FROM citation WHERE fact_id = %s", (fact_id,))
        if left[0]["n"] == 0:
            self.expire(fact_id)

    def facts_by_source(self, source_key: str, current_only: bool = True) -> list[StoredFact]:
        where = "f.source_key = %s AND f.expired_at IS NULL"
        if current_only:
            where += " AND f.invalid_at IS NULL"
        return self._facts(where, (source_key,), "ORDER BY f.id")

    def facts_by_claim_key(self, entity_id: str, attribute: str) -> list[StoredFact]:
        return self._facts(
            "f.claim_entity = %s AND f.claim_attribute = %s AND f.expired_at IS NULL",
            (entity_id, attribute),
            "ORDER BY f.id",
        )

    def facts_citing(self, document_id: str) -> list[StoredFact]:
        return self._facts(
            """f.expired_at IS NULL AND EXISTS (SELECT 1 FROM citation c
               WHERE c.fact_id = f.id AND c.document_id = %s)""",
            (document_id,),
            "ORDER BY f.id",
        )

    def all_facts(self, as_of: datetime | None = None) -> list[StoredFact]:
        return self._facts(_LIVE, {"as_of": as_of}, "ORDER BY f.id")

    def query_by_entity(
        self, entity_id: str, as_of: datetime | None = None, depth: int = 0
    ) -> list[StoredFact]:
        wanted = self.related_entities(entity_id, depth) if depth else [entity_id]
        return self._facts(
            _LIVE
            + """ AND (EXISTS (SELECT 1 FROM fact_entity fe
                              WHERE fe.fact_id = f.id AND fe.entity_id = ANY(%(ids)s))
                       OR f.claim_entity = ANY(%(ids)s))""",
            {"as_of": as_of, "ids": wanted},
            "ORDER BY f.id",
        )

    def _ranked(self, ranked_sql: str, params: dict[str, Any]) -> list[tuple[StoredFact, float]]:
        rows = self._q(ranked_sql, params)
        facts = self._facts_by_ids([r["id"] for r in rows])
        return [(facts[r["id"]], float(r["score"])) for r in rows if r["id"] in facts]

    def query_text(
        self,
        query: str,
        as_of: datetime | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[StoredFact, float]]:
        return self._ranked(
            f"""
            WITH q AS (
                SELECT replace(plainto_tsquery('english', %(q)s)::text, '&', '|') AS t
            )
            SELECT f.id, ts_rank_cd(f.tsv, q.t::tsquery) AS score
            FROM fact f, q
            WHERE q.t <> '' AND f.tsv @@ q.t::tsquery AND {_LIVE} {_FILTERS}
            ORDER BY score DESC, f.id LIMIT %(limit)s
            """,
            {"q": query, "as_of": as_of, "category": category, "since": since, "limit": limit},
        )

    def query_vector(
        self,
        vector: Sequence[float],
        as_of: datetime | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[StoredFact, float]]:
        return self._ranked(
            f"""
            SELECT f.id, 1 - (f.embedding <=> %(v)s::vector) AS score
            FROM fact f
            WHERE f.embedding IS NOT NULL AND {_LIVE} {_FILTERS}
            ORDER BY f.embedding <=> %(v)s::vector, f.id LIMIT %(limit)s
            """,
            {
                "v": vector_literal(vector),
                "as_of": as_of,
                "category": category,
                "since": since,
                "limit": limit,
            },
        )

    def facts_since(self, ts: datetime, as_of: datetime | None = None) -> list[StoredFact]:
        return self._facts(
            _LIVE + " AND f.valid_at IS NOT NULL AND f.valid_at >= %(ts)s::timestamptz",
            {"as_of": as_of, "ts": aware(ts)},
            "ORDER BY f.valid_at, f.id",
        )

    # ------------------------------------------------------ contradictions

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
        self.conn.execute(
            """
            INSERT INTO contradiction (id, fact_a, fact_b, label, winner, kind, reason, opened_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                label = EXCLUDED.label, winner = EXCLUDED.winner, reason = EXCLUDED.reason,
                opened_at = LEAST(contradiction.opened_at, EXCLUDED.opened_at),
                resolved_at = NULL
            """,
            (cid, a, b, label, winner, kind, reason, aware(opened_at)),
        )
        return cid

    def resolve_contradiction(self, contradiction_id: str, at: datetime | None) -> None:
        self.conn.execute(
            """UPDATE contradiction SET resolved_at = COALESCE(%s::timestamptz, clock_timestamp())
               WHERE id = %s AND resolved_at IS NULL""",
            (aware(at), contradiction_id),
        )

    def query_contradictions(
        self, entity_id: str | None = None, as_of: datetime | None = None
    ) -> list[StoredContradiction]:
        rows = self._q(
            """
            SELECT * FROM contradiction c
            WHERE (%(as_of)s::timestamptz IS NULL OR c.created_at <= %(as_of)s::timestamptz)
              AND (%(e)s::text IS NULL
                   OR EXISTS (SELECT 1 FROM fact_entity fe
                              WHERE fe.fact_id IN (c.fact_a, c.fact_b) AND fe.entity_id = %(e)s)
                   OR EXISTS (SELECT 1 FROM fact f
                              WHERE f.id IN (c.fact_a, c.fact_b) AND f.claim_entity = %(e)s))
            ORDER BY (c.resolved_at IS NOT NULL), c.id
            """,
            {"as_of": as_of, "e": entity_id},
        )
        return [
            StoredContradiction(
                id=r["id"],
                a=r["fact_a"],
                b=r["fact_b"],
                label=r["label"],
                winner=r["winner"],
                kind=r["kind"],
                opened_at=r["opened_at"],
                resolved_at=r["resolved_at"],
                reason=r["reason"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # --------------------------------------------------------- stored time

    def snapshot(self, name: str, step: str | None = None) -> datetime:
        rows = self._q(
            """INSERT INTO snapshot (name, step) VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE SET taken_at = clock_timestamp(), step = EXCLUDED.step
               RETURNING taken_at""",
            (name, step),
        )
        return rows[0]["taken_at"]

    def snapshot_at(self, name: str) -> datetime | None:
        rows = self._q("SELECT taken_at FROM snapshot WHERE name = %s", (name,))
        return rows[0]["taken_at"] if rows else None

    def last_step(self) -> str | None:
        rows = self._q(
            """SELECT step FROM snapshot WHERE step IS NOT NULL
               ORDER BY taken_at DESC LIMIT 1"""
        )
        return rows[0]["step"] if rows else None
