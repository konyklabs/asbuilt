"""pipeline/embed.py and pipeline/resolve.py (konyklabs/asbuilt#4), on the
hash embedder; nothing is downloaded. Names are invented."""

from __future__ import annotations

import builtins
import math

from pipeline.embed import EMBED_DIM, MODEL_REVISION, HashEmbedder, load_embedder
from pipeline.resolve import Resolver, fold, infer_kind
from pipeline.store import Entity, MemoryStore, cosine

KINDS = ("service", "table", "rule", "job", "flag", "integration", "queue", "team", "endpoint")


def test_hash_embedder_is_deterministic_unit_length_and_word_sensitive():
    embedder = HashEmbedder()
    a, again, near, far = embedder.embed(
        ["late return fee", "late return fee", "late return fees apply", "dock sensor battery"]
    )
    assert len(a) == EMBED_DIM and a == again
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert cosine(a, near) > 0.5 > cosine(a, far)
    assert embedder.calls == 1 and embedder.tokens > 0


def test_load_embedder_names_which_embedder_ran(monkeypatch):
    monkeypatch.setenv("ASBUILT_EMBED", "fake")
    assert load_embedder().name == "hash-384 (fake: ASBUILT_EMBED=fake)"

    monkeypatch.delenv("ASBUILT_EMBED")
    real_import = builtins.__import__

    def no_sentence_transformers(name, *args, **kwargs):
        if name.startswith("sentence_transformers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sentence_transformers)
    assert load_embedder().name == "hash-384 (fake: sentence-transformers not installed)"
    assert len(MODEL_REVISION) == 40  # pinned to a commit, not a branch


def test_fold_and_infer_kind():
    assert fold("LOST_RETURN-fee") == fold("lost return fee") == "lostreturnfee"
    assert infer_kind("ticketbox", KINDS, ["ticketbox"]) == "service"
    assert infer_kind("POST /waivers", KINDS) == "endpoint"
    assert infer_kind("fee.events", KINDS) == "queue"
    assert infer_kind("LedgerClient", KINDS) == "integration"
    assert infer_kind("nightlySweep", KINDS) == "job"
    assert infer_kind("fee_ledger", KINDS) == "table"
    assert infer_kind("LATE_FEE", KINDS) == "rule"
    assert infer_kind("nightlySweep", ("rule",)) == "rule"


def test_resolver_passes_in_order_and_records_aliases():
    store = MemoryStore()
    resolver = Resolver(store, HashEmbedder(), KINDS, services=["ticketbox"])
    service = resolver.resolve("ticketbox")
    rule = resolver.resolve("late return fee")
    assert store.entity(service).kind == "service"
    assert resolver.resolve("LATE_RETURN_FEE") == rule  # separator-folded
    assert "LATE_RETURN_FEE" in store.entity(rule).aliases
    assert resolver.passes == {"name": 0, "alias": 0, "folded": 1, "embedding": 0, "new": 2}

    fresh = Resolver(store, HashEmbedder(), KINDS)  # a new cache over the same store
    assert fresh.resolve("Late Return Fee") == rule  # exact name, any case
    assert fresh.resolve("late_return_fee") == rule  # now an exact alias
    assert fresh.passes == {"name": 1, "alias": 1, "folded": 0, "embedding": 0, "new": 0}


def test_resolver_embedding_pass_stays_within_a_kind():
    class Fixed:
        name, dim, calls, tokens = "fixed", 2, 0, 0

        def embed(self, texts):
            return [[1.0, 0.0] if "overdue" in t else [0.0, 1.0] for t in texts]

    store = MemoryStore()
    store.upsert_entity(Entity(id="e-a", name="overdue charge", kind="rule", embedding=[1.0, 0.0]))
    store.upsert_entity(Entity(id="e-b", name="overdue flag", kind="flag", embedding=[1.0, 0.0]))
    resolver = Resolver(store, Fixed(), KINDS, threshold=0.9)
    assert resolver.resolve("overdue penalty", "rule") == "e-a"
    assert "overdue penalty" in store.entity("e-a").aliases
    assert resolver.resolve("overdue thing", "table") not in ("e-a", "e-b")  # a new table


def test_lookup_never_creates_and_mentioned_finds_names_in_text():
    store = MemoryStore()
    resolver = Resolver(store, HashEmbedder(), KINDS)
    fee = resolver.resolve("late return fee")
    resolver.register_aliases(fee, ["the late fee"])
    assert resolver.lookup("late-return-fee") == fee
    assert resolver.lookup("the late fee") == fee
    assert resolver.lookup("dock sensor") is None
    assert len(store.entities()) == 1
    assert resolver.mentioned("Why is the late fee four dollars?") == [fee]
