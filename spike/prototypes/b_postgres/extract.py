"""Stack B's extraction from documents: one structured-output call per wiki
page, document, ticket or pull-request thread, against a fixed schema (the
schema-guided pattern, no framework), through the pipeline's counting client.

The schema makes the citation mandatory: every fact names the document id and
a location in it (a ``#heading`` anchor, ``description``, ``body`` or a
``comment-<k>`` id). ``apply_extraction`` then checks it: the document is
forced to the one being read, the version is the registered one, and a
location the document does not have becomes no location rather than a
made-up one. The prompt carries the entity-kind vocabulary every arm gets,
the entities already known (so the model reuses their names) and the claim
keys already known (so a page's value for ``lost_bike_fee`` joins the code's
claim instead of inventing a new attribute).

A documented fact's ``valid_at`` is the document's lastmodified unless the
document itself says when the statement held (``valid_from``/``valid_to``,
history facts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bench.llm import CountingClient
from bench.protocol import Citation
from connectors.tests.extract_model import DEFAULT_MODEL, PRICE_TABLE
from pipeline.embed import Embedder
from pipeline.lift import link_entities, to_claim
from pipeline.llm import prompt_tokens, schema_text, structured_call
from pipeline.resolve import Resolver
from pipeline.sources import SourceDocument
from pipeline.store import StoredFact, StoreInterface

CATEGORIES = ("business-logic", "technical-implementation", "operations", "history")
TOOL_NAME = "record_document_facts"
OUTPUT_TOKENS_PER_DOCUMENT = 900  # dry-run assumption, stated
MAX_KNOWN_ENTITIES = 200
MAX_KNOWN_CLAIMS = 120

SYSTEM = (
    "You extract cited facts from one document about a software system. Each fact "
    "is one sentence in the present tense that says exactly what the document "
    "states, never more. Every fact cites the document and the location it came "
    "from. Respond only with the JSON the schema requires."
)


def build_schema(entity_kinds: tuple[str, ...]) -> dict[str, Any]:
    kind = {"type": "string", "enum": list(entity_kinds)} if entity_kinds else {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kind": kind,
                        "aliases": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "kind"],
                },
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "claim": {
                            "type": ["object", "null"],
                            "properties": {
                                "entity": {"type": "string"},
                                "attribute": {"type": "string"},
                                # anyOf, not ["number", "string"]: the CLI validates
                                # the schema with Ajv in strict mode, which prohibits
                                # a type array of two non-null types ("strict mode:
                                # use allowUnionTypes ...", the stack-B run of
                                # 2026-10-02) while a [T, "null"] array, as on the
                                # fields around it, is allowed. bench.claude_code
                                # refuses the prohibited form before spawning.
                                "value": {"anyOf": [{"type": "number"}, {"type": "string"}]},
                                "unit": {"type": ["string", "null"]},
                            },
                            "required": ["entity", "attribute", "value"],
                        },
                        "citation": {
                            "type": "object",
                            "properties": {
                                "document": {"type": "string"},
                                "location": {"type": "string"},
                            },
                            "required": ["document", "location"],
                        },
                        "valid_from": {"type": ["string", "null"]},
                        "valid_to": {"type": ["string", "null"]},
                    },
                    "required": ["statement", "category", "entities", "citation"],
                },
            },
        },
        "required": ["entities", "facts"],
    }


def build_prompt(
    doc: SourceDocument,
    entity_kinds: tuple[str, ...],
    known_entities: list[tuple[str, str]],
    known_claims: list[tuple[str, str, str | None]],
) -> str:
    meta = doc.document
    stamp = meta.lastmodified.isoformat() if meta.lastmodified else "unknown"
    lines = [
        "Extract every fact this document states about the system.",
        f"Document id: {meta.id} (kind {meta.kind}, version {meta.version}, last modified {stamp})",
        f"Title: {meta.title or '(none)'}",
        f"Cite every fact to document {meta.id!r} and one of these locations: "
        + ", ".join(doc.anchors or ("(none: use an empty string)",)),
        "Entity kinds: " + ", ".join(entity_kinds),
        "Categories: business-logic (rules the system applies), technical-implementation "
        "(how it is built), operations (running it), history (decisions, product history, "
        "ownership, glossary).",
        "A fact with a number, a money amount, a duration or a clock time carries exactly "
        "one claim (entity, attribute in snake_case, value, unit: usd, minute, day, hour, "
        "second, percent, count, clock or null); a fact without one has claim null.",
        "valid_from / valid_to: an ISO date only when the document says when the statement "
        "held; otherwise null.",
        "List under `entities` every system entity the document names, with the other "
        "names it uses for the same thing as aliases.",
    ]
    if known_entities:
        lines.append(
            "Known entities (use these exact names when the document means them): "
            + "; ".join(f"{n} ({k})" for n, k in known_entities[:MAX_KNOWN_ENTITIES])
        )
    if known_claims:
        lines.append(
            "Known claim keys (reuse the entity and attribute when the fact is about one): "
            + "; ".join(f"{e}/{a}/{u or '-'}" for e, a, u in known_claims[:MAX_KNOWN_CLAIMS])
        )
    lines += ["---", doc.text]
    return "\n".join(lines)


def known_context(
    store: StoreInterface,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str | None]]]:
    names = {e.id: e.name for e in store.entities()}
    entities = sorted((e.name, e.kind) for e in store.entities())
    claims = sorted(
        {
            (names.get(f.claim.entity_id, f.claim.entity_id), f.claim.attribute, f.claim.unit)
            for f in store.all_facts()
            if f.claim is not None
        },
        key=lambda t: (t[0], t[1], t[2] or ""),
    )
    return entities, claims


def extract_document(
    client: CountingClient,
    doc: SourceDocument,
    entity_kinds: tuple[str, ...],
    known_entities: list[tuple[str, str]],
    known_claims: list[tuple[str, str, str | None]],
) -> dict[str, Any]:
    payload = structured_call(
        client,
        prompt=build_prompt(doc, entity_kinds, known_entities, known_claims),
        schema=build_schema(entity_kinds),
        system=SYSTEM,
        tool_name=TOOL_NAME,
        max_tokens=4000,
    )
    return payload or {"entities": [], "facts": []}


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def apply_extraction(
    store: StoreInterface,
    resolver: Resolver,
    embedder: Embedder,
    doc: SourceDocument,
    payload: dict[str, Any],
) -> list[str]:
    """Upserts the extracted facts; returns their ids."""
    for entity in payload.get("entities") or []:
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        entity_id = resolver.resolve(name, entity.get("kind"))
        if entity_id is not None:
            resolver.register_aliases(entity_id, entity.get("aliases") or [])

    meta = doc.document
    anchors = set(doc.anchors)
    ids: list[str] = []
    for raw in payload.get("facts") or []:
        statement = str(raw.get("statement") or "").strip()
        if not statement:
            continue
        entity_ids: list[str] = []
        for name in raw.get("entities") or []:
            entity_id = resolver.resolve(str(name))
            if entity_id is not None and entity_id not in entity_ids:
                entity_ids.append(entity_id)
        claim = to_claim(raw.get("claim"), resolver)
        if claim is not None and claim.entity_id not in entity_ids:
            entity_ids.append(claim.entity_id)
        if not entity_ids:
            continue  # a fact about nothing the store can name is not kept
        location = str((raw.get("citation") or {}).get("location") or "")
        citation = Citation(
            document=meta.id,
            location=location if location in anchors else None,
            version=meta.version,
        )
        category = raw.get("category") if raw.get("category") in CATEGORIES else "business-logic"
        fact = StoredFact(
            statement=statement,
            category=category,
            tier="documented",
            entity_ids=tuple(entity_ids),
            citations=(citation,),
            claim=claim,
            valid_at=_parse_date(raw.get("valid_from")) or meta.lastmodified,
            invalid_at=_parse_date(raw.get("valid_to")),
            source_key=f"doc:{meta.id}",
            embedding=embedder.embed([statement])[0],
        )
        fact_id = store.upsert_fact(fact)
        link_entities(store, fact.entity_ids)
        if fact_id not in ids:
            ids.append(fact_id)
    return ids


@dataclass(frozen=True)
class DryRun:
    documents: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    model: str
    estimated_dollars: float


def dry_run(docs: list[SourceDocument], entity_kinds: tuple[str, ...]) -> DryRun:
    """Every prompt built as `extract_document` would build it on an empty
    store (no known entities or claims: a lower bound on input), priced from
    the connector's stated `PRICE_TABLE`; no call is made."""
    schema = schema_text(build_schema(entity_kinds))
    input_tokens = sum(
        prompt_tokens(SYSTEM, schema, build_prompt(d, entity_kinds, [], [])) for d in docs
    )
    output_tokens = OUTPUT_TOKENS_PER_DOCUMENT * len(docs)
    prices = PRICE_TABLE[DEFAULT_MODEL]
    dollars = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
    return DryRun(len(docs), input_tokens, output_tokens, DEFAULT_MODEL, dollars)
