from __future__ import annotations

import shutil
from pathlib import Path

from bench.truth import (
    Carrier,
    _check_run_carrier,
    check_consistency,
    github_slugify,
    load_contradictions,
    load_entities,
    load_facts,
    load_stale,
    load_truth,
    resolve_step,
    summarize,
)
from tests._support import MINI_ROOT


def test_load_entities():
    entities = load_entities(MINI_ROOT / "truth" / "entities.yaml")
    assert set(entities) == {"E-farebox", "E-rule-member-free-minutes"}
    assert entities["E-rule-member-free-minutes"].owner == "E-farebox"


def test_load_facts_valid_from_and_valid_to():
    facts = load_facts(MINI_ROOT / "truth" / "facts.yaml")
    assert len(facts) == 13
    assert facts["F-001"].tier == "executed"
    assert facts["F-001"].valid_to == "c2"
    assert facts["F-002"].valid_from == "c2"
    assert facts["F-002"].valid_to == "c4"
    assert facts["F-003"].valid_from == "c4"
    assert facts["F-003"].valid_to is None
    # F-001 and F-003 share a statement and a code document at different
    # versions — the case score.py's version disambiguation exists for.
    assert facts["F-001"].statement == facts["F-003"].statement
    assert facts["F-001"].carriers[0].document == facts["F-003"].carriers[0].document
    assert facts["F-001"].carriers[0].version != facts["F-003"].carriers[0].version


def test_load_contradictions_and_stale():
    contradictions = load_contradictions(MINI_ROOT / "truth" / "contradictions.yaml")
    stale = load_stale(MINI_ROOT / "truth" / "stale.yaml")
    assert contradictions["X-001"].facts == ("F-005", "F-003")
    assert contradictions["X-001"].winner == "F-003"
    assert stale["S-001"].changed_by == "c4"
    assert stale["S-001"].states == "F-005"


def test_load_truth_bundles_all_four():
    truth = load_truth(MINI_ROOT / "truth")
    assert len(truth.entities) == 2
    assert len(truth.facts) == 13
    assert len(truth.contradictions) == 1
    assert len(truth.stale) == 1


def test_resolve_step():
    commits = {"c1": {"sha": "deadbeef", "date": "2026-01-01T09:00:00-05:00", "message": "m"}}
    assert resolve_step("c1", commits)["sha"] == "deadbeef"
    try:
        resolve_step("c99", commits)
    except KeyError as exc:
        assert "c99" in str(exc)
    else:
        raise AssertionError("resolve_step should raise KeyError for an unknown step")


def test_github_slugify():
    assert github_slugify("Free minutes") == "free-minutes"
    assert github_slugify("Overview") == "overview"
    assert github_slugify("Refund policy") == "refund-policy"


def test_check_consistency_passes_on_mini():
    problems = check_consistency(MINI_ROOT)
    assert problems == [], summarize(problems)


def test_check_consistency_fails_on_broken_copy(tmp_path: Path):
    broken = tmp_path / "broken"
    shutil.copytree(MINI_ROOT, broken)

    # Break it two ways: a carrier document that no longer exists, and a
    # fact referencing an entity that does not exist.
    (broken / "sources" / "wiki" / "pricing-rules-2025.md").unlink()
    facts_path = broken / "truth" / "facts.yaml"
    facts_path.write_text(
        facts_path.read_text().replace(
            "entities: [E-farebox]", "entities: [E-farebox, E-does-not-exist]", 1
        )
    )

    problems = check_consistency(broken)
    assert problems
    joined = "\n".join(problems)
    assert "pricing-rules-2025" in joined
    assert "E-does-not-exist" in joined


def test_check_consistency_catches_bad_heading_anchor_and_bad_symbol(tmp_path: Path):
    broken = tmp_path / "broken"
    shutil.copytree(MINI_ROOT, broken)

    # Rename the wiki heading F-004 anchors, so "#overview" no longer matches.
    wiki_path = broken / "sources" / "wiki" / "pricing-rules.md"
    wiki_path.write_text(wiki_path.read_text().replace("## Overview", "## Summary"))

    # Rename the code symbol F-001..F-003 point at, so it's no longer a word
    # in the materialised file at any version.
    for path in [
        broken / "system" / "farebox" / "pricing.py",
        broken / "system" / "history" / "c1" / "farebox" / "pricing.py",
        broken / "system" / "history" / "c3" / "farebox" / "pricing.py",
    ]:
        path.write_text(path.read_text().replace("FREE_MINUTES", "FREEBIE_MINUTES"))

    problems = check_consistency(broken)
    joined = "\n".join(problems)
    assert "wiki:wiki/pricing-rules:#overview" in joined
    assert any(p.startswith("code:code/farebox/pricing.py") for p in problems)


def test_check_consistency_catches_bad_vitest_title_and_bad_dotted_symbol(tmp_path: Path):
    broken = tmp_path / "broken"
    shutil.copytree(MINI_ROOT, broken)

    # F-012's location is "refundsWatcher > locks a bike ...": break the
    # describe() call's literal name so it no longer appears as a call.
    ts_path = broken / "system" / "dispatch" / "test" / "refundsWatcher.test.ts"
    ts_path.write_text(ts_path.read_text().replace("describe('refundsWatcher'", "describe('other'"))

    # F-013's location is "PricingClient.fetch_rate": rename the class.
    client_path = broken / "system" / "farebox" / "client.py"
    client_path.write_text(client_path.read_text().replace("PricingClient", "RenamedClient"))

    problems = check_consistency(broken)
    joined = "\n".join(problems)
    assert "describe('refundsWatcher')" in joined
    assert any("dotted symbol 'PricingClient.fetch_rate'" in p for p in problems)


def test_run_carrier_reconstructs_vitest_fullname_not_raw_field():
    """Vitest 5.0.2 joins ancestorTitles+title with a single space in its own
    `fullName` field (confirmed 2026-09-28 against real spike/system/dispatch
    output); truth's locations use " > ". check_consistency must reconstruct
    the join itself, never trust the raw `fullName`, or every vitest carrier
    in the real fixture would silently fail to resolve."""
    carrier = Carrier(
        document="run/vitest-c1",
        location="refunds > publishes a refund.completed event",
    )
    assert _check_run_carrier(carrier, MINI_ROOT) is None

    raw_fullname_carrier = Carrier(
        document="run/vitest-c1",
        location="refunds publishes a refund.completed event",  # the raw fullName
    )
    problem = _check_run_carrier(raw_fullname_carrier, MINI_ROOT)
    assert problem is not None
    assert "no passed vitest fullName match" in problem


def test_summarize_groups_by_kind():
    problems = ["wiki:a:b:not found", "wiki:c:d:not found", "fact: F-1 has no carriers"]
    report = summarize(problems)
    assert "3 problem(s)" in report
    assert "wiki: 2" in report
    assert "fact: 1" in report
