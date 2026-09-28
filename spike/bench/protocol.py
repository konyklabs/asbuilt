"""The contract between the benchmark harness and a prototype.

A prototype ingests the fixture once, then answers the five surfaces the
README promises agents: search, explain, contradictions, stale, ask. Every
fact it returns carries at least one citation; the scorer drops a fact
without one, by design (README, "Three properties that are not negotiable").

Document ids are ``<kind>/<id>`` and are shared by ``truth/``, ``sources/``
and every prototype:

    wiki/<slug>            a wiki page; version is the page version number
    ticket/<KEY>           a ticket; location is a comment id or ``description``
    doc/<id>               a document; version is its head revision id
    pull/<number>          a pull-request thread; location is a comment id
    code/<path>            a file in the built repository; version is a commit SHA
    run/<run-id>           a test run; location is the test node id

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


@dataclass
class Fact:
    statement: str
    category: Category
    entities: tuple[str, ...]
    tier: Tier
    citations: tuple[Citation, ...]
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


@runtime_checkable
class Prototype(Protocol):
    name: str

    def ingest(self, fixture_root: Path) -> IngestReport: ...

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
