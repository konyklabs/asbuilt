"""Entity resolution: a name to an entity row (D-013; measured by the scorer
through an alias table the arms never see).

Order, first hit wins: the exact name (case-insensitive); an exact alias;
the separator-folded name or alias (``lost bike fee``, ``lost-bike-fee`` and
``LOST_BIKE_FEE`` all fold to ``lostbikefee``); the nearest entity by
embedding, within the same kind, at or above ``threshold``; else a new
entity. Every non-exact hit records the name as an alias, so the next lookup
of it is exact. ``lookup`` is the read-only form the query surfaces use: the
same passes, never a new row, and the embedding pass across every kind (a
query does not say what kind it names).

A name's kind, when the extractor does not give one, is inferred from its
shape (``infer_kind``) inside the fixed vocabulary every arm receives; it
only narrows the embedding pass, never the exact ones.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Sequence

from pipeline.embed import Embedder
from pipeline.store import Entity, StoreInterface

DEFAULT_THRESHOLD = 0.85
_FOLD = re.compile(r"[\s\-_./]+")
_CAMEL = re.compile(r"^[a-z]+(?:[A-Z][a-z0-9]*)+$")


def fold(name: str) -> str:
    return _FOLD.sub("", name.strip().lower())


def infer_kind(name: str, entity_kinds: Sequence[str], services: Iterable[str] = ()) -> str:
    """A best guess from the name's shape; always a member of `entity_kinds`
    when that is non-empty."""
    text = name.strip()
    guess = "rule"
    if fold(text) in {fold(s) for s in services}:
        guess = "service"
    elif re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+/", text):
        guess = "endpoint"
    elif re.fullmatch(r"[a-z]+(?:\.[a-z_]+)+", text):
        guess = "queue"
    elif text.endswith("Client") or text.lower().endswith(" client"):
        guess = "integration"
    elif _CAMEL.match(text):
        guess = "job"
    elif re.fullmatch(r"[a-z]+(?:_[a-z]+)+", text):
        guess = "table"
    kinds = tuple(entity_kinds)
    if kinds and guess not in kinds:
        return "rule" if "rule" in kinds else kinds[0]
    return guess


def entity_id_for(name: str, kind: str) -> str:
    return "e-" + hashlib.sha1(f"{kind}:{fold(name)}".encode()).hexdigest()[:12]


class Resolver:
    def __init__(
        self,
        store: StoreInterface,
        embedder: Embedder,
        entity_kinds: Sequence[str] = (),
        services: Iterable[str] = (),
        threshold: float | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.entity_kinds = tuple(entity_kinds)
        self.services = tuple(services)
        env = os.environ.get("ASBUILT_RESOLVE_THRESHOLD")
        self.threshold = (
            threshold if threshold is not None else float(env) if env else DEFAULT_THRESHOLD
        )
        self._cache: dict[tuple[str, str | None], str] = {}
        self._index: dict[str, str] | None = None
        self.passes: dict[str, int] = {
            "name": 0,
            "alias": 0,
            "folded": 0,
            "embedding": 0,
            "new": 0,
        }

    def _exact(self, name: str, kind: str | None) -> tuple[str, str] | None:
        entity = self.store.entity_by_name(name)
        if entity is not None:
            return entity.id, "name"
        entity = self.store.entity_by_alias(name)
        if entity is not None:
            return entity.id, "alias"
        candidates = self.store.entities_by_folded(fold(name))
        if candidates:
            same_kind = [e for e in candidates if kind is not None and e.kind == kind]
            chosen = (same_kind or sorted(candidates, key=lambda e: e.id))[0]
            return chosen.id, "folded"
        return None

    def resolve(self, name: str, kind: str | None = None) -> str | None:
        """The entity id for `name`, creating the entity when nothing
        matches. None only for an empty name."""
        name = name.strip()
        if not name:
            return None
        key = (name.lower(), kind)
        if key in self._cache:
            return self._cache[key]
        hit = self._exact(name, kind)
        if hit is None:
            kind = kind or infer_kind(name, self.entity_kinds, self.services)
            vector = self.embedder.embed([name])[0]
            near = self.store.nearest_entity(vector, kind)
            if near is not None and near[1] >= self.threshold:
                hit = (near[0].id, "embedding")
            else:
                entity_id = entity_id_for(name, kind)
                self.store.upsert_entity(
                    Entity(id=entity_id, name=name, kind=kind, embedding=vector)
                )
                hit = (entity_id, "new")
        entity_id, via = hit
        if via in ("folded", "embedding"):
            self.store.add_alias(entity_id, name)
        if via != "name":
            self._index = None
        self.passes[via] += 1
        self._cache[key] = entity_id
        return entity_id

    def register_aliases(self, entity_id: str, aliases: Iterable[str]) -> None:
        for alias in aliases:
            alias = alias.strip()
            if alias:
                self.store.add_alias(entity_id, alias)
                self._index = None

    def lookup(self, name: str) -> str | None:
        """Read-only resolution for the query surfaces."""
        name = name.strip()
        if not name:
            return None
        hit = self._exact(name, None)
        if hit is not None:
            return hit[0]
        near = self.store.nearest_entity(self.embedder.embed([name])[0], None)
        if near is not None and near[1] >= self.threshold:
            return near[0].id
        return None

    def _folded_index(self) -> dict[str, str]:
        if self._index is None:
            index: dict[str, str] = {}
            for entity in sorted(self.store.entities(), key=lambda e: e.id):
                for label in (entity.name, *entity.aliases):
                    index.setdefault(fold(label), entity.id)
            self._index = index
        return self._index

    def mentioned(self, text: str, max_words: int = 4) -> list[str]:
        """Entity ids whose name or alias appears in `text` as a run of up to
        `max_words` words, matched exactly after folding — for `ask`. Reads
        one in-memory index of every name and alias, built on first use and
        dropped whenever `resolve` adds a name."""
        index = self._folded_index()
        words = re.findall(r"[\w.$/-]+", text)
        found: list[str] = []
        for size in range(max_words, 0, -1):
            for start in range(0, len(words) - size + 1):
                phrase = " ".join(words[start : start + size]).strip(".?,")
                folded = fold(phrase)
                if len(folded) < 4:
                    continue
                entity_id = index.get(folded)
                if entity_id is not None and entity_id not in found:
                    found.append(entity_id)
        return found

    def name_of(self, entity_id: str) -> str:
        entity = self.store.entity(entity_id)
        return entity.name if entity is not None else entity_id
