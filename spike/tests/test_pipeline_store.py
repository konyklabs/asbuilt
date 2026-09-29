"""The store contract on MemoryStore, and the pure identity and policy
helpers in pipeline/store.py (konyklabs/asbuilt#4). The same contract runs
on Postgres in tests/test_b_postgres.py."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pipeline.store import (
    MemoryStore,
    StoredClaim,
    base_fact_id,
    claims_conflict,
    normalize_claim_value,
    normalize_unit,
    overlaps,
    winner_of,
)
from tests._support.store_contract import CHECKS, fact


@pytest.mark.parametrize("check", CHECKS, ids=[c.__name__ for c in CHECKS])
def test_memory_store_contract(check):
    store = MemoryStore()
    store.reset()
    check(store)


def test_claim_values_normalise_money_and_numbers():
    assert normalize_claim_value("$150.00") == 150.0
    assert normalize_claim_value(150) == 150.0
    assert normalize_claim_value("07:30") == "07:30"
    assert normalize_unit("Minutes") == "minute"
    assert normalize_unit(None) is None


def test_claims_conflict_only_on_the_same_key_and_unit():
    four = StoredClaim("e-1", "late_fee", 4.0, "usd")
    assert claims_conflict(four, StoredClaim("e-1", "late_fee", 6.0, "usd"))
    assert not claims_conflict(four, StoredClaim("e-1", "late_fee", 4.0, None))
    assert not claims_conflict(four, StoredClaim("e-1", "late_fee", 6.0, "day"))
    assert not claims_conflict(four, StoredClaim("e-2", "late_fee", 6.0, "usd"))


def test_fact_id_is_stable_and_keyed_by_claim():
    claim = StoredClaim("e-1", "late_fee", 4.0, "usd")
    assert base_fact_id("Late fee is $4.", claim) == base_fact_id("  late fee is $4 ", claim)
    assert base_fact_id("Late fee is $4.", claim) != base_fact_id("Late fee is $4.", None)


def test_winner_by_tier_then_recency():
    t1, t2 = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
    page = fact("x", tier="documented", valid_at=t2)
    code = fact("y", tier="code", valid_at=t1)
    assert winner_of(page, code) is code
    newer = fact("z", tier="code", valid_at=t2)
    assert winner_of(code, newer) is newer


def test_overlap_of_world_time_intervals():
    t1, t2, t3 = (datetime(2026, m, 1, tzinfo=UTC) for m in (1, 2, 3))
    old = fact("a", valid_at=t1)
    old.invalid_at = t2
    assert not overlaps(old, fact("b", valid_at=t2))
    assert overlaps(old, fact("c", valid_at=None))
    assert overlaps(fact("d", valid_at=t1), fact("e", valid_at=t3))
