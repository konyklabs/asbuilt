"""The contradiction pass (D-013, stage 5), written once for every arm.

**Claims, by join.** Two stored facts contradict when their claims share the
join key (resolved entity, attribute, unit — ``store.claims_comparable``),
their values differ, and their world-time intervals overlap: a value that
changed at a commit is a supersession (``lift.py``), not a contradiction; a
page still stating the old value while the code states the new one is.
Winner: ``store.winner_of`` (executed > code > documented, then recency).
Label ``refutes``. No model call.

**Prose, by pre-filter then verdict.** Facts without a claim that share a
non-hub entity (not a service or team — every fact about ``farebox`` would
otherwise pair up), come from different documents, and include at least one
``documented`` fact are candidate pairs. The pre-filter is the NLI
cross-encoder ``cross-encoder/nli-deberta-v3-base`` (Apache-2.0, pinned,
cached under ``build/models/``, in the ``pipeline`` dependency group; labels
contradiction/entailment/neutral per its config): pairs whose contradiction
probability reaches ``NLI_THRESHOLD`` go on. When the package is not
installed the NLI step is skipped and a lexical stand-in applies instead
(word overlap at least ``LEXICAL_OVERLAP`` with a negation or a number that
differs), stated in the report as such. A surviving pair gets one model
verdict through the counting client (``refutes`` / ``supports`` /
``unrelated``, structured output); only ``refutes`` is linked. Without a
model (``judge is None``) no prose pair is decided at all: the pass never
guesses. Verdicts are capped at ``max_verdicts`` per pass.

Re-running the pass is idempotent (contradiction ids are the sorted pair's
hash); a ``claim`` contradiction that no longer holds (one side superseded or
expired since) is resolved.

Pins, fetched 2026-09-29 from the Hugging Face model API:
``cross-encoder/nli-deberta-v3-base`` at
``6c749ce3425cd33b46d187e45b92bbf96ee12ec7``, licence apache-2.0,
``id2label`` {0: contradiction, 1: entailment, 2: neutral}.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pipeline.store import (
    HUB_KINDS,
    StoredFact,
    StoreInterface,
    aware,
    claims_conflict,
    overlaps,
    terms,
    winner_of,
)

NLI_MODEL = "cross-encoder/nli-deberta-v3-base"
NLI_REVISION = "6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
NLI_LABELS = ("contradiction", "entailment", "neutral")
NLI_THRESHOLD = 0.5
LEXICAL_OVERLAP = 0.35
DEFAULT_MAX_VERDICTS = 60
SPIKE_ROOT = Path(__file__).resolve().parent.parent

_NEGATION = re.compile(r"\b(not|never|no|none|without|off|cannot|can't|isn't|doesn't)\b", re.I)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class NLI(Protocol):
    name: str

    def contradiction_probs(self, pairs: Sequence[tuple[str, str]]) -> list[float]: ...


class Judge(Protocol):
    def verdict(self, a: StoredFact, b: StoredFact) -> tuple[str, str]: ...


@dataclass
class CrossEncoderNLI:
    model_name: str = NLI_MODEL
    revision: str = NLI_REVISION
    cache_dir: Path = SPIKE_ROOT / "build" / "models"
    _model: Any = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return f"{self.model_name}@{self.revision[:12]}"

    def contradiction_probs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # noqa: PLC0415 - lazy

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = CrossEncoder(
                self.model_name, cache_folder=str(self.cache_dir), revision=self.revision
            )
        scores = self._model.predict(list(pairs), apply_softmax=True)
        index = NLI_LABELS.index("contradiction")
        return [float(row[index]) for row in scores]


def load_nli() -> NLI | None:
    """The cross-encoder when sentence-transformers is importable and
    ``ASBUILT_NLI`` is not ``off``; else None (the pre-filter is skipped)."""
    if os.environ.get("ASBUILT_NLI", "").lower() == "off":
        return None
    try:
        import sentence_transformers  # noqa: F401, PLC0415 - availability probe only
    except ImportError:
        return None
    return CrossEncoderNLI()


def lexical_candidate(a: str, b: str) -> bool:
    ta, tb = set(terms(a)), set(terms(b))
    if not ta or not tb or len(ta & tb) / min(len(ta), len(tb)) < LEXICAL_OVERLAP:
        return False
    negation_differs = bool(_NEGATION.search(a)) != bool(_NEGATION.search(b))
    na, nb = set(_NUMBER.findall(a)), set(_NUMBER.findall(b))
    return negation_differs or (bool(na) and bool(nb) and na != nb)


@dataclass
class PassReport:
    claim_pairs: int = 0
    prose_pairs: int = 0
    prefilter: str = "none"
    prefiltered: int = 0
    verdicts: int = 0
    linked: int = 0
    resolved: int = 0
    skipped_reason: str | None = None


def _opened(a: StoredFact, b: StoredFact) -> datetime | None:
    stamps = [aware(t) for t in (a.valid_at, b.valid_at) if t is not None]
    return max(stamps) if stamps else None


def claim_candidates(facts: Sequence[StoredFact]) -> list[tuple[StoredFact, StoredFact]]:
    groups: dict[tuple[str, str], list[StoredFact]] = {}
    for fact in facts:
        if fact.claim is not None and fact.expired_at is None:
            groups.setdefault((fact.claim.entity_id, fact.claim.attribute), []).append(fact)
    pairs = []
    for members in groups.values():
        members.sort(key=lambda f: f.id or "")
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if claims_conflict(a.claim, b.claim) and overlaps(a, b):
                    pairs.append((a, b))
    return pairs


def _documents(fact: StoredFact) -> set[str]:
    return {c.document for c in fact.citations}


def prose_candidates(
    store: StoreInterface, facts: Sequence[StoredFact]
) -> list[tuple[StoredFact, StoredFact]]:
    hubs = {e.id for e in store.entities() if e.kind in HUB_KINDS}
    prose = [f for f in facts if f.claim is None and f.expired_at is None]
    by_entity: dict[str, list[StoredFact]] = {}
    for fact in prose:
        for entity_id in fact.entity_ids:
            if entity_id not in hubs:
                by_entity.setdefault(entity_id, []).append(fact)
    seen: set[tuple[str, str]] = set()
    pairs = []
    for members in by_entity.values():
        members.sort(key=lambda f: f.id or "")
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                key = (a.id or "", b.id or "")
                if key in seen or "documented" not in (a.tier, b.tier):
                    continue
                if _documents(a) & _documents(b) or not overlaps(a, b):
                    continue
                seen.add(key)
                pairs.append((a, b))
    return pairs


def run_pass(
    store: StoreInterface,
    *,
    nli: NLI | None = None,
    judge: Judge | None = None,
    max_verdicts: int = DEFAULT_MAX_VERDICTS,
) -> PassReport:
    report = PassReport()
    facts = store.all_facts()

    live_claim_ids: set[str] = set()
    for a, b in claim_candidates(facts):
        winner = winner_of(a, b)
        cid = store.link_contradiction(
            a.id, b.id, "refutes", winner=winner.id, opened_at=_opened(a, b), kind="claim"
        )
        live_claim_ids.add(cid)
        report.claim_pairs += 1
    for contradiction in store.query_contradictions():
        if (
            contradiction.kind == "claim"
            and contradiction.resolved_at is None
            and contradiction.id not in live_claim_ids
        ):
            store.resolve_contradiction(contradiction.id, None)
            report.resolved += 1

    pairs = prose_candidates(store, facts)
    report.prose_pairs = len(pairs)
    if judge is None:
        report.skipped_reason = "no model: prose pairs are not decided"
        return report
    if nli is not None:
        report.prefilter = nli.name
        probs = nli.contradiction_probs([(a.statement, b.statement) for a, b in pairs])
        survivors = [p for p, prob in zip(pairs, probs, strict=True) if prob >= NLI_THRESHOLD]
    else:
        report.prefilter = "lexical (NLI not installed)"
        survivors = [(a, b) for a, b in pairs if lexical_candidate(a.statement, b.statement)]
    report.prefiltered = len(survivors)
    for a, b in survivors[:max_verdicts]:
        label, reason = judge.verdict(a, b)
        report.verdicts += 1
        if label == "refutes":
            winner = winner_of(a, b)
            store.link_contradiction(
                a.id,
                b.id,
                "refutes",
                winner=winner.id,
                opened_at=_opened(a, b),
                kind="prose",
                reason=reason,
            )
            report.linked += 1
    return report
