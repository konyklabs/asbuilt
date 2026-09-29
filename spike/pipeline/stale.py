"""Staleness (D-013, stage 5): which ``documented`` facts no longer describe
the system. Computed on read from the store, so it is always as of the
store's current state; two rules, first hit wins per fact.

1. **Claim.** A current documented fact with a claim, and a current
   ``code``/``executed`` fact on the same join key with a different value
   whose ``valid_at`` is later than the documented fact's (a documented
   fact's ``valid_at`` is its document's lastmodified, unless the extractor
   gave it an explicit validity). The page states the value the code had
   before it changed.
2. **Lastmodified.** A current documented fact citing a page (``wiki/`` or
   ``doc/``) whose lastmodified precedes the commit that last changed a code
   document it relates to, where "relates" is either (a) the fact itself
   cites that ``code/`` document, or (b) a current code/executed fact sharing
   one of its non-hub entities cites it and the two statements' numbers
   differ. The disagreement is required in (b): without it every page older
   than any commit touching the same entity would be stale.

A documented fact with a closed interval (``invalid_at`` set: "was 45 from
February to June") states history, not the present, and is never stale.

``stale_since(store, since)`` returns the stale facts whose triggering change
is dated after ``since`` — the ``stale`` surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from pipeline.store import (
    CONNECTOR_TIERS,
    HUB_KINDS,
    StoredFact,
    StoreInterface,
    claims_conflict,
    later,
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
PAGE_KINDS = ("wiki", "doc")


@dataclass(frozen=True)
class StaleFinding:
    fact_id: str
    rule: str  # "claim" | "lastmodified"
    changed_at: datetime | None
    because: str  # the superseding fact id or the changed code document


def _numbers(text: str) -> set[str]:
    return {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER.findall(text)}


def stale_findings(store: StoreInterface) -> list[StaleFinding]:
    facts = store.all_facts()
    documents = {d.id: d for d in store.documents()}
    hubs = {e.id for e in store.entities() if e.kind in HUB_KINDS}
    code_facts = [f for f in facts if f.tier in CONNECTOR_TIERS and f.invalid_at is None]
    documented = [f for f in facts if f.tier == "documented" and f.invalid_at is None]

    findings: dict[str, StaleFinding] = {}
    for doc_fact in documented:
        if doc_fact.claim is not None:
            for code_fact in code_facts:
                if (
                    code_fact.claim is not None
                    and claims_conflict(doc_fact.claim, code_fact.claim)
                    and later(code_fact.valid_at, doc_fact.valid_at)
                ):
                    findings[doc_fact.id] = StaleFinding(
                        doc_fact.id, "claim", code_fact.valid_at, code_fact.id
                    )
                    break
        if doc_fact.id in findings:
            continue

        pages = [
            documents[c.document]
            for c in doc_fact.citations
            if c.document in documents and documents[c.document].kind in PAGE_KINDS
        ]
        page_times = [p.lastmodified for p in pages if p.lastmodified is not None]
        if not page_times:
            continue
        page_time = max(page_times)

        related_code: list[str] = [
            c.document for c in doc_fact.citations if c.document.startswith("code/")
        ]
        doc_entities = set(doc_fact.entity_ids) - hubs
        doc_numbers = _numbers(doc_fact.statement)
        for code_fact in code_facts:
            if not doc_entities & set(code_fact.entity_ids):
                continue
            code_numbers = _numbers(code_fact.statement)
            if doc_numbers and code_numbers and doc_numbers != code_numbers:
                related_code += [
                    c.document for c in code_fact.citations if c.document.startswith("code/")
                ]
        for code_document in related_code:
            code_doc = documents.get(code_document)
            if code_doc is not None and later(code_doc.lastmodified, page_time):
                findings[doc_fact.id] = StaleFinding(
                    doc_fact.id, "lastmodified", code_doc.lastmodified, code_document
                )
                break
    return list(findings.values())


def stale_since(store: StoreInterface, since: datetime) -> list[StoredFact]:
    out = []
    for finding in stale_findings(store):
        if finding.changed_at is None or later(finding.changed_at, since):
            fact = store.fact(finding.fact_id)
            if fact is not None:
                out.append(fact)
    return out
