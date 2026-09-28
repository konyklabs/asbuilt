"""The contract between the benchmark harness and a prototype.

A prototype ingests the fixture once, then answers the five surfaces the
README promises agents: search, explain, contradictions, stale, ask. Every
fact it returns carries at least one citation; the scorer counts a fact
without one as a false positive, by design (README, "Three properties that
are not negotiable"). ``Fact.entities`` are entity NAMES (``farebox``,
``member-free-minutes``, ...), the ``name`` field in ``truth/entities.yaml``
— never the ``E-`` id, and never read from ``truth/aliases.yaml``, which
prototypes never see. The scorer aligns a returned name to a truth id
through that alias table, so entity resolution is itself measured rather
than handed to every arm for free (D-013). A returned fact still credits
only when it shares a resolved entity, cites one of the truth fact's carrier
documents, and states the same numbers.

Document ids are ``<kind>/<id>`` and are shared by ``truth/``, ``sources/``
and every prototype:

    wiki/<slug>            a wiki page; version is the page version number
    ticket/<KEY>           a ticket; location is a comment id or ``description``
    doc/<id>               a document; version is its head revision id
    pull/<number>          a pull-request thread; location is a comment id
    code/<path>            a file in the built repository; version is a commit SHA;
                           location is a symbol (``MEMBER_FREE_MINUTES``,
                           ``FareboxClient.close_ride``), a pytest node id or a
                           Vitest ``describe > it`` title
    run/<run-id>           a test run; location is the test node id or title

``valid_from`` and ``valid_to`` are the world-time interval in which the
statement held (Graphiti's bi-temporal shape, D-013); ``None`` means open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


class Tier(StrEnum):
    """Provenance tiers, strongest first (D-013: executed > code > documented)."""

    EXECUTED = "executed"  # a test ran and passed, at a commit, on a date
    CODE = "code"  # read from source at a commit
    DOCUMENTED = "documented"  # a page, a ticket, a comment, a document


class Category(StrEnum):
    BUSINESS_LOGIC = "business-logic"
    TECHNICAL = "technical-implementation"
    OPERATIONS = "operations"
    HISTORY = "history"  # decisions, product history, ownership, glossary


@dataclass(frozen=True)
class Citation:
    document: str
    location: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class Claim:
    """A numeric fact's identity across re-ingest (D-013): (entity,
    attribute, value, unit), e.g. (member-free-minutes, minutes, 30, None).
    Lets a numeric contradiction be a join instead of a model call."""

    entity: str
    attribute: str
    value: float | int | str
    unit: str | None = None


@dataclass
class Fact:
    statement: str
    category: Category
    entities: tuple[str, ...]
    tier: Tier
    citations: tuple[Citation, ...]
    id: str | None = None  # a stable id of the prototype's own choosing
    claim: Claim | None = None  # set when the statement is a numeric claim
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float | None = None


@dataclass
class Contradiction:
    a: Fact
    b: Fact
    label: str = "refutes"  # FEVER-style: supports | refutes (R9)
    winner: Fact | None = None  # by tier, then by recency; None if the prototype does not decide


@dataclass
class Sentence:
    text: str
    citations: tuple[Citation, ...]


@dataclass
class Answer:
    sentences: list[Sentence] = field(default_factory=list)


@dataclass
class IngestReport:
    seconds: float
    input_tokens: int
    output_tokens: int
    dollars: float
    services: tuple[str, ...]  # what had to be running, e.g. ("postgres",) or ("neo4j",)
    documents: int  # Documents ingested, all kinds
    model: str | None = None  # the extraction model id, e.g. "claude-sonnet-5"
    embedder: str | None = None  # the embedding model id, if any
    calls: int = 0  # model calls made (bench.llm.CountingClient's count)
    embedding_tokens: int = 0
    cache_tokens: int = 0  # prompt-cache tokens, counted separately from input/output


@runtime_checkable
class Prototype(Protocol):
    name: str

    def ingest(
        self,
        fixture_root: Path,
        entity_kinds: tuple[str, ...],
        incremental: bool = False,
    ) -> IngestReport:
        """Ingest `fixture_root` (an assembled ingest root, never the raw
        fixture — see bench/run.py). `entity_kinds` is the fixed vocabulary
        every arm gets (service, table, rule, job, flag, integration, queue,
        team, endpoint), the same set truth/entities.yaml uses. When
        `incremental` is True, `fixture_root` is a later checkout than an
        earlier call in the same run (`bench/run.py --incremental` ingests
        through the fixture's second-to-last step, then again through its
        last step with this set) and this call must advance the prototype's
        own existing store rather than start over. The harness records both
        calls' IngestReports and their delta (`ingest_incremental` in the
        results file); whether the resulting store avoided duplicate facts
        and superseded correctly is for the scorer to check separately, not
        a guarantee this call makes on its own."""
        ...

    def explain(self, entity: str) -> list[Fact]: ...

    def search(
        self,
        query: str,
        category: Category | None = None,
        since: datetime | None = None,
    ) -> list[Fact]: ...

    def ask(self, question: str) -> Answer: ...

    def contradictions(self, entity: str | None = None) -> list[Contradiction]: ...

    def stale(self, since: datetime) -> list[Fact]: ...
