"""Stack B: our own fact model on Postgres + pgvector (D-013; konyklabs/asbuilt#4).

``ingest(root, entity_kinds, incremental)``, in order:

1. A full ingest (``incremental=False``, or a store that has never ingested)
   drops and re-applies the schema; an incremental one keeps the store and
   resumes after the last step it reached.
2. The built repository's history (``pipeline.history``), and which step
   the root's ``repo/`` is (by blob hash; the latest run report's step if it
   matches none).
3. Every source document registered with its version: run reports and every
   code file now (a code file's version is the commit that last changed it);
   a wiki page, document, ticket or pull request only after step 5 has
   stored its facts, so one a budget stop or a crash interrupted stays
   pending and the next ingest extracts it. Only new, changed or pending
   text documents are extracted from.
4. The test connector (``connectors.tests``, rules extractor) at every step
   not yet ingested, in commit order, over the git history and the root's
   runs; ``pipeline.lift`` stores its facts, tiers, candidates and
   supersessions.
5. One structured call per changed wiki/doc/ticket/pull document
   (``extract.py``) through the counting client — skipped entirely when
   ``ASBUILT_B_NO_MODEL=1`` (the text documents then stay pending). A
   document whose new version no longer states a fact retracts its citation
   (the fact expires when nothing else cites it); a new value on the same
   claim key supersedes the old one only when the old one is documented and
   this document was its only source — a code or executed row, or one
   another page still states, is never closed by a page: the pair becomes a
   ``claim`` contradiction, winner by tier.
6. The contradiction pass (``pipeline.contradict``: claim join; prose pairs
   through the NLI pre-filter and a model verdict, none without a model).
7. The ``IngestReport``: tokens, dollars (a token-priced estimate: the
   claude-code provider bills the subscription, not per call), calls,
   seconds, ``services=("postgres",)``, documents new or changed.

Surfaces: ``explain(name)`` resolves the name (``pipeline.resolve.lookup``)
and returns its facts ranked by tier, then recency; ``search`` fuses
full-text and vector rankings (reciprocal rank); ``ask`` composes the top
facts for the question into one sentence each with its citations (no model
when ``ASBUILT_B_NO_MODEL=1``); ``contradictions`` and ``stale`` read the
store (``pipeline.stale`` on read).

Constructor arguments are all optional (the harness passes none): tests
hand in ``store=MemoryStore()``, a fake embedder or a fake client factory.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from bench.protocol import (
    Answer,
    Category,
    Citation,
    Claim,
    Contradiction,
    Fact,
    IngestReport,
    Sentence,
    Tier,
)
from connectors.tests.__main__ import build_step_output
from connectors.tests.evidence import Outcome, read_runs_directory
from pipeline.contradict import load_nli, run_pass
from pipeline.embed import Embedder, load_embedder
from pipeline.history import GitHistory, ensure_built
from pipeline.lift import apply_step, overlap
from pipeline.llm import ModelJudge, make_client, structured_call
from pipeline.resolve import Resolver
from pipeline.sources import (
    TEXT_KINDS,
    SourceDocument,
    code_documents,
    read_run_documents,
    read_text_sources,
)
from pipeline.stale import stale_since
from pipeline.store import (
    TIER_RANK,
    StoredFact,
    StoreInterface,
    aware,
    claims_conflict,
    display_value,
    winner_of,
)
from prototypes.b_postgres.extract import apply_extraction, extract_document, known_context

ARM = "b_postgres"
RRF_K = 60
SEARCH_LIMIT = 10
ASK_FACTS = 5
CITATIONS_PER_SENTENCE = 3
SUPERSEDED_WEIGHT = 0.5
VECTOR_FLOOR = float(os.environ.get("ASBUILT_B_VECTOR_FLOOR", "0.3"))


def _needs_extraction(store: StoreInterface, doc: SourceDocument) -> bool:
    known = store.document(doc.id)
    return (
        known is None
        or known.version != doc.document.version
        or known.content_hash != doc.document.content_hash
    )


def no_model() -> bool:
    return os.environ.get("ASBUILT_B_NO_MODEL", "") == "1"


def _outcomes_by_step(root: Path) -> dict[str, list[Outcome]]:
    runs = root / "runs"
    by_step: dict[str, list[Outcome]] = {}
    if runs.is_dir():
        for outcome in read_runs_directory(runs):
            if outcome.step:
                by_step.setdefault(outcome.step, []).append(outcome)
    return by_step


def _recency(fact: StoredFact) -> float:
    return aware(fact.valid_at).timestamp() if fact.valid_at else float("-inf")


def rank(facts: Iterable[StoredFact]) -> list[StoredFact]:
    """Tier first (executed, code, documented), then the later valid_at."""
    return sorted(facts, key=lambda f: (-TIER_RANK.get(f.tier, 0), -_recency(f), f.id or ""))


# What a sentence cites first, by the fact's own tier: an executed fact leads
# with its latest passing run, a code fact with the code (never a failing run
# that demoted it), a documented fact with its pages.
_CITATION_ORDER = {
    "executed": {"run": 0, "code": 1},
    "code": {"code": 0, "run": 2},
    "documented": {"code": 1, "run": 2},
}


def best_citations(fact: StoredFact, cap: int = CITATIONS_PER_SENTENCE) -> tuple[Citation, ...]:
    """The strongest evidence for the fact's tier first, one citation per
    document (its latest: citations are stored oldest first), then the
    remaining versions if the cap is not yet reached."""
    order = _CITATION_ORDER.get(fact.tier, {})
    indexed = list(enumerate(fact.citations))
    indexed.sort(key=lambda p: (order.get(p[1].document.split("/")[0], 0.5), -p[0]))
    first: list[Citation] = []
    rest: list[Citation] = []
    for _, citation in indexed:
        (rest if any(c.document == citation.document for c in first) else first).append(citation)
    return tuple((first + rest)[:cap])


ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "facts": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["text", "facts"],
            },
        }
    },
    "required": ["sentences"],
}
ANSWER_SYSTEM = (
    "You answer a question about a software system only from the numbered facts "
    "given. One sentence per point, each naming the numbers of the facts it rests "
    "on. Never add anything the facts do not say."
)


class Prototype:
    name = ARM

    def __init__(
        self,
        store: StoreInterface | None = None,
        embedder: Embedder | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._client_factory = client_factory
        self._resolver: Resolver | None = None
        self._names: dict[str, str] | None = None
        self._answers: dict[str, Answer] = {}
        self._client = None
        self.last_ingest: dict[str, Any] = {}

    # ----------------------------------------------------------- plumbing

    @property
    def store(self) -> StoreInterface:
        if self._store is None:
            from prototypes.b_postgres.store import PostgresStore  # noqa: PLC0415

            self._store = PostgresStore()
        return self._store

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = load_embedder()
        return self._embedder

    def _query_resolver(self) -> Resolver:
        if self._resolver is None:
            self._resolver = Resolver(self.store, self.embedder)
        return self._resolver

    def _entity_names(self) -> dict[str, str]:
        if self._names is None:
            self._names = {e.id: e.name for e in self.store.entities()}
        return self._names

    def _to_fact(self, fact: StoredFact) -> Fact:
        names = self._entity_names()
        claim = None
        if fact.claim is not None:
            claim = Claim(
                entity=names.get(fact.claim.entity_id, fact.claim.entity_id),
                attribute=fact.claim.attribute,
                value=display_value(fact.claim.value),
                unit=fact.claim.unit,
            )
        return Fact(
            statement=fact.statement,
            category=Category(fact.category),
            entities=tuple(names.get(e, e) for e in fact.entity_ids),
            tier=Tier(fact.tier),
            citations=fact.citations,
            id=fact.id,
            claim=claim,
            valid_from=fact.valid_at,
            valid_to=fact.invalid_at,
            confidence=fact.confidence,
        )

    # -------------------------------------------------------------- ingest

    def ingest(
        self,
        fixture_root: Path,
        entity_kinds: tuple[str, ...],
        incremental: bool = False,
    ) -> IngestReport:
        started = time.perf_counter()
        root = Path(fixture_root)
        store = self.store
        embedder = self.embedder
        embed_tokens_before = embedder.tokens

        resumed_from = store.last_step() if incremental else None
        if resumed_from is None:
            store.reset()

        repo, commits = ensure_built(ARM)
        history = GitHistory(repo, commits)
        step = history.step_of_checkout(root / "repo") or self._latest_run_step(root, history)
        if step is None:
            raise RuntimeError(f"{ARM}: {root}/repo matches no commit and no run names a step")
        order = history.step_ids
        start = order.index(resumed_from) + 1 if resumed_from in order else 0
        steps = order[start : order.index(step) + 1]

        services = history.services(step)
        resolver = Resolver(store, embedder, entity_kinds, services)
        for service in services:
            resolver.resolve(service, "service")

        documents: list[SourceDocument] = [
            *read_text_sources(root),
            *read_run_documents(root, history),
            *code_documents(history, step),
        ]
        # Code files and runs are registered now; a text document only once
        # its facts are stored (below), so a budget stop or a crash
        # mid-extraction leaves it pending for the next ingest to extract.
        registered = [
            d
            for d in documents
            if d.document.kind not in TEXT_KINDS and store.register_document(d.document)
        ]
        pending = [
            d for d in documents if d.document.kind in TEXT_KINDS and _needs_extraction(store, d)
        ]

        outcomes = _outcomes_by_step(root)
        lift_totals = {"facts": 0, "superseded": 0, "opened": 0, "resolved": 0}
        for step_id in steps:
            output = build_step_output(
                root, step_id, history.repo, commits, outcomes, order, timeline=history
            )
            lifted = apply_step(store, resolver, embedder, output, history)
            lift_totals["facts"] += lifted.facts
            lift_totals["superseded"] += lifted.superseded
            lift_totals["opened"] += lifted.contradictions_opened
            lift_totals["resolved"] += lifted.contradictions_resolved
            store.snapshot(f"step:{step_id}", step=step_id)

        client = None
        extracted = 0
        if not no_model():
            client = self._client or make_client(ARM, client_factory=self._client_factory)
            self._client = client
            for doc in pending:
                self._extract(store, resolver, embedder, client, doc, entity_kinds)
                store.register_document(doc.document)  # only after its facts are stored
                extracted += 1

        judge = ModelJudge(client) if client is not None else None
        contradiction_pass = run_pass(
            store, nli=load_nli() if judge is not None else None, judge=judge
        )
        store.snapshot(f"ingest:{step}", step=step)

        self._resolver = resolver
        self._names = None
        self._answers.clear()
        self.last_ingest = {
            "step": step,
            "steps": steps,
            "resumed_from": resumed_from,
            "documents_changed": len(registered) + len(pending),
            "documents_pending": len(pending) - extracted,
            "documents_extracted": extracted,
            "lift": lift_totals,
            "contradiction_pass": contradiction_pass,
            "resolver": dict(resolver.passes),
            "embedder": embedder.name,
            "model": None if client is None else client.model,
        }
        print(
            f"{ARM}: step {step}, steps {steps}, documents registered {len(registered)}, "
            f"pending {len(pending)}, extracted {extracted}, lift {lift_totals}, claim pairs "
            f"{contradiction_pass.claim_pairs}, prose pairs {contradiction_pass.prose_pairs} "
            f"({contradiction_pass.skipped_reason or contradiction_pass.prefilter}), "
            f"embedder {embedder.name}",
            file=sys.stderr,
        )
        return IngestReport(
            seconds=time.perf_counter() - started,
            input_tokens=client.input_tokens if client else 0,
            output_tokens=client.output_tokens if client else 0,
            dollars=client.dollars() if client and client.prices else 0.0,
            services=("postgres",),
            documents=len(registered) + extracted,
            model=client.model if client else None,
            embedder=embedder.name,
            calls=client.calls if client else 0,
            embedding_tokens=embedder.tokens - embed_tokens_before,
            cache_tokens=client.cache_tokens if client else 0,
        )

    @staticmethod
    def _latest_run_step(root: Path, history: GitHistory) -> str | None:
        known = [s for s in _outcomes_by_step(root) if s in history.step_ids]
        return max(known, key=history.step_ids.index, default=None)

    def _extract(
        self,
        store: StoreInterface,
        resolver: Resolver,
        embedder: Embedder,
        client: Any,
        doc: SourceDocument,
        entity_kinds: tuple[str, ...],
    ) -> None:
        prior = {f.id: f for f in store.facts_citing(doc.id)}
        known_entities, known_claims = known_context(store)
        payload = extract_document(client, doc, entity_kinds, known_entities, known_claims)
        new_ids = apply_extraction(store, resolver, embedder, doc, payload)
        new_facts = [f for f in (store.fact(i) for i in new_ids) if f is not None]
        for fact_id, old in prior.items():
            if fact_id in new_ids:
                continue
            replacement = next(
                (
                    n
                    for n in new_facts
                    if old.claim is not None
                    and n.claim is not None
                    and claims_conflict(old.claim, n.claim)
                ),
                None,
            )
            sole_source = all(c.document == doc.id for c in old.citations)
            if replacement is not None and old.tier == "documented" and sole_source:
                # The page changed its own value: the new version supersedes the old.
                store.supersede(fact_id, replacement.id, doc.document.lastmodified)
                continue
            store.retract_citation(fact_id, doc.id)
            if replacement is not None:
                # A page never closes a code or executed row, nor one another
                # page still states (the same rule as lift._supersede_by_claim):
                # its new value is a contradiction candidate against it.
                winner = winner_of(old, replacement)
                store.link_contradiction(
                    fact_id,
                    replacement.id,
                    "refutes",
                    winner=winner.id,
                    opened_at=doc.document.lastmodified,
                    kind="claim",
                )

    # ------------------------------------------------------------ surfaces

    def explain(self, entity: str) -> list[Fact]:
        entity_id = self._query_resolver().lookup(entity)
        if entity_id is None:
            return []
        return [self._to_fact(f) for f in rank(self.store.query_by_entity(entity_id))]

    def _fused(
        self,
        query: str,
        category: Category | None = None,
        since: datetime | None = None,
        limit: int = SEARCH_LIMIT,
    ) -> list[tuple[StoredFact, float]]:
        cat = category.value if isinstance(category, Category) else category
        text_hits = self.store.query_text(query, category=cat, since=since, limit=limit * 2)
        vector = self.embedder.embed([query])[0]
        vector_hits = [
            (f, s)
            for f, s in self.store.query_vector(vector, category=cat, since=since, limit=limit * 2)
            if s >= VECTOR_FLOOR
        ]
        scores: dict[str, float] = {}
        facts: dict[str, StoredFact] = {}
        for hits in (text_hits, vector_hits):
            for position, (fact, _score) in enumerate(hits):
                scores[fact.id] = scores.get(fact.id, 0.0) + 1.0 / (RRF_K + position + 1)
                facts[fact.id] = fact
        ordered = sorted(scores, key=lambda i: (-scores[i], i))
        return [(facts[i], scores[i]) for i in ordered[:limit]]

    def search(
        self,
        query: str,
        category: Category | None = None,
        since: datetime | None = None,
    ) -> list[Fact]:
        return [self._to_fact(f) for f, _ in self._fused(query, category, since)]

    def _ask_candidates(self, question: str) -> list[StoredFact]:
        scored: dict[str, tuple[float, StoredFact]] = {}
        for position, (fact, _) in enumerate(self._fused(question, limit=ASK_FACTS * 2)):
            scored[fact.id] = (1.0 / (position + 1) + overlap(question, fact.statement), fact)
        resolver = self._query_resolver()
        for entity_id in resolver.mentioned(question):
            for fact in self.store.query_by_entity(entity_id, depth=1):
                score = overlap(question, fact.statement)
                if score > 0 and (fact.id not in scored or scored[fact.id][0] < score):
                    scored[fact.id] = (score, fact)
        # A superseded fact answers "what was", rarely "what is": half weight.
        ordered = sorted(
            scored.values(),
            key=lambda p: (
                -(p[0] * (SUPERSEDED_WEIGHT if p[1].invalid_at is not None else 1.0)),
                -TIER_RANK.get(p[1].tier, 0),
                p[1].id or "",
            ),
        )
        return [f for _, f in ordered[:ASK_FACTS]]

    def ask(self, question: str) -> Answer:
        if question in self._answers:
            return self._answers[question]
        facts = self._ask_candidates(question)
        answer = None
        if facts and not no_model():
            answer = self._compose_with_model(question, facts)
        if answer is None:
            answer = Answer(
                sentences=[
                    Sentence(
                        text=f.statement if f.statement.endswith(".") else f.statement + ".",
                        citations=best_citations(f),
                    )
                    for f in facts
                ]
            )
        self._answers[question] = answer
        return answer

    def _compose_with_model(self, question: str, facts: list[StoredFact]) -> Answer | None:
        if self._client is None:
            self._client = make_client(ARM, client_factory=self._client_factory)
        numbered = "\n".join(f"[{i}] {f.statement}" for i, f in enumerate(facts, start=1))
        payload = structured_call(
            self._client,
            prompt=f"Question: {question}\nFacts:\n{numbered}",
            schema=ANSWER_SCHEMA,
            system=ANSWER_SYSTEM,
            tool_name="record_answer",
            max_tokens=800,
        )
        if not payload:
            return None
        sentences = []
        for item in payload.get("sentences") or []:
            cited = [
                facts[i - 1]
                for i in item.get("facts") or []
                if isinstance(i, int) and 1 <= i <= len(facts)
            ]
            if not cited or not str(item.get("text", "")).strip():
                continue  # every answer cites: a sentence with no fact behind it is dropped
            citations: list[Citation] = []
            for fact in cited:
                for citation in best_citations(fact):
                    if citation not in citations:
                        citations.append(citation)
            capped = tuple(citations[:CITATIONS_PER_SENTENCE])
            sentences.append(Sentence(text=str(item["text"]), citations=capped))
        return Answer(sentences=sentences) if sentences else None

    def contradictions(self, entity: str | None = None) -> list[Contradiction]:
        entity_id = None
        if entity:
            entity_id = self._query_resolver().lookup(entity)
            if entity_id is None:
                return []
        out = []
        for row in self.store.query_contradictions(entity_id):
            a, b = self.store.fact(row.a), self.store.fact(row.b)
            if a is None or b is None:
                continue
            winner = self.store.fact(row.winner) if row.winner else None
            out.append(
                Contradiction(
                    a=self._to_fact(a),
                    b=self._to_fact(b),
                    label=row.label,
                    winner=self._to_fact(winner) if winner else None,
                )
            )
        return out

    def stale(self, since: datetime) -> list[Fact]:
        return [self._to_fact(f) for f in rank(stale_since(self.store, since))]
