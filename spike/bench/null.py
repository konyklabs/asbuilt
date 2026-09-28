"""The null prototype: a baseline that ingests nothing and answers nothing.

Every score against it should be zero (or undefined, where a denominator is
zero) — it exists to prove the scorer's arithmetic and the harness's
plumbing end to end before a real prototype exists.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from bench.protocol import Answer, Category, Contradiction, Fact, IngestReport


def _count_documents(fixture_root: Path) -> int:
    total = 0
    for dirname in ("sources", "system", "runs"):
        directory = fixture_root / dirname
        if directory.is_dir():
            total += sum(1 for p in directory.rglob("*") if p.is_file())
    return total


class NullPrototype:
    name = "null"

    def ingest(self, fixture_root: Path) -> IngestReport:
        return IngestReport(
            seconds=0.0,
            input_tokens=0,
            output_tokens=0,
            dollars=0.0,
            services=(),
            documents=_count_documents(fixture_root),
        )

    def explain(self, entity: str) -> list[Fact]:
        return []

    def search(
        self,
        query: str,
        category: Category | None = None,
        since: datetime | None = None,
    ) -> list[Fact]:
        return []

    def ask(self, question: str) -> Answer:
        return Answer(sentences=[])

    def contradictions(self, entity: str | None = None) -> list[Contradiction]:
        return []

    def stale(self, since: datetime) -> list[Fact]:
        return []
