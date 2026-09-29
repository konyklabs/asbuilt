"""The embedder every arm uses (D-013: "the embedder for both arms is named in
the harness before the first run").

The real one is sentence-transformers ``all-MiniLM-L6-v2`` (Apache-2.0, 384
dimensions), pinned to a Hugging Face commit and cached under
``build/models/`` so a run is offline after the first download. It is in the
``pipeline`` optional dependency group (``uv sync --extra pipeline``); the
package is imported lazily, never at module import.

``HashEmbedder`` is the deterministic fallback, same dimension: feature
hashing of the text's word stems into 384 signed buckets, L2-normalised, so
texts sharing words have a positive cosine and a run is reproducible to the
bit. It is used when ``ASBUILT_EMBED=fake`` (every test sets it), or when
sentence-transformers is not installed; ``load_embedder`` says which one ran
and why, and the arm writes that into its ``IngestReport.embedder``.

Pins, fetched 2026-09-29 from the Hugging Face model API (``sha`` field):
``sentence-transformers/all-MiniLM-L6-v2`` at
``1110a243fdf4706b3f48f1d95db1a4f5529b4d41``, licence apache-2.0.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pipeline.store import terms

EMBED_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
SPIKE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = SPIKE_ROOT / "build" / "models"


class Embedder(Protocol):
    name: str
    dim: int
    calls: int
    tokens: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


@dataclass
class HashEmbedder:
    """Deterministic, dependency-free; see the module docstring."""

    dim: int = EMBED_DIM
    reason: str = "ASBUILT_EMBED=fake"
    calls: int = field(default=0, init=False)
    tokens: int = field(default=0, init=False)

    @property
    def name(self) -> str:
        return f"hash-{self.dim} (fake: {self.reason})"

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        words = terms(text)
        for word in words:
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        self.tokens += len(words)
        return _unit(vector)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self._one(t) for t in texts]


@dataclass
class SentenceTransformerEmbedder:
    """all-MiniLM-L6-v2 at the pinned revision; loads on first use."""

    model_name: str = MODEL_NAME
    revision: str = MODEL_REVISION
    cache_dir: Path = DEFAULT_CACHE
    dim: int = EMBED_DIM
    calls: int = field(default=0, init=False)
    tokens: int = field(default=0, init=False)
    _model: Any = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return f"{self.model_name}@{self.revision[:12]}"

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415 - lazy

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(
                self.model_name, cache_folder=str(self.cache_dir), revision=self.revision
            )
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        self.calls += 1
        self.tokens += sum(len(t.split()) for t in texts)
        vectors = model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in v] for v in vectors]


def load_embedder(cache_dir: Path | None = None) -> Embedder:
    """``ASBUILT_EMBED=fake`` -> HashEmbedder; otherwise the real model when
    sentence-transformers is importable, else HashEmbedder with the reason."""
    if os.environ.get("ASBUILT_EMBED", "").lower() == "fake":
        return HashEmbedder(reason="ASBUILT_EMBED=fake")
    try:
        import sentence_transformers  # noqa: F401, PLC0415 - availability probe only
    except ImportError:
        return HashEmbedder(reason="sentence-transformers not installed")
    return SentenceTransformerEmbedder(cache_dir=cache_dir or DEFAULT_CACHE)
