from __future__ import annotations

import difflib
import functools
import json
import re
from datetime import datetime

import pytest

from bench.run import run
from bench.score import (
    _TRUTH_FILTER_PREFIXES,
    DEFAULT_CALIBRATION,
    SPIKE_ROOT,
    _attributes_match,
    _bound_direction_conflict,
    _boundary_numbers_ok,
    _citation_fidelities,
    _claim_metrics,
    _claim_value_as_number_token,
    _claim_values_match,
    _claims_match,
    _current_at_step,
    _duplicate_count,
    _entity_mention_conflict,
    _executed_by_step,
    _expected_fidelity_at_step,
    _expected_tier_at_step,
    _fidelity_by_step,
    _first_step,
    _flag_state_conflict,
    _flag_states,
    _has_filter_carrier_by_step,
    _has_negation,
    _has_test_carrier_by_step,
    _mentioned_entities,
    _merge_fidelity_counts,
    _normalise_unit,
    _number_tokens,
    _outcome_conflict,
    _resolve_contradiction_entities,
    _resolve_step_or_sha,
    _resolve_temporal_value_to_step,
    _run_step_rank,
    _shares_matching_version,
    _side_matches,
    _split_camel,
    _split_restated,
    _statement_matches,
    _step_dates,
    _step_order,
    _temporal_field_matches,
    _text_similarity,
    _without_http_codes,
    aggregate_reports,
    align_entities,
    bootstrap_compare,
    build_alias_index,
    build_mention_index,
    calibrate,
    classify_unmatched,
    distinct_executed,
    facts_match,
    load_calibration,
    main,
    match_facts,
    norm,
    norm_entity,
    print_comparison,
    print_multi_report,
    print_report,
    print_test_connector_report,
    resolve_fact_entities,
    score,
    score_ask_query,
    score_contradictions,
    score_fact_query,
    score_stale,
    score_test_connector,
    truth_runs,
    wilson_lower_bound,
)
from bench.truth import (
    Carrier,
    Entity,
    Fidelities,
    StaleEntry,
    TruthContradiction,
    TruthFact,
    load_facts,
    load_truth,
)
from tests._support import MINI_ROOT

STATEMENT = "A member's free minutes are 20."

TRUTH = TruthFact(
    id="F-1",
    statement=STATEMENT,
    category="business-logic",
    entities=("E-farebox",),
    tier="documented",
    carriers=(Carrier(document="wiki/x"),),
)


def test_facts_match_true_positive():
    returned = {
        "statement": STATEMENT,
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    assert facts_match(returned, TRUTH)


def test_facts_match_false_without_shared_entity():
    returned = {
        "statement": STATEMENT,
        "entities": ["E-something-else"],
        "citations": [{"document": "wiki/x"}],
    }
    assert not facts_match(returned, TRUTH)


def test_facts_match_false_without_shared_citation():
    returned = {
        "statement": STATEMENT,
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/y"}],
    }
    assert not facts_match(returned, TRUTH)


def test_facts_match_false_below_similarity_threshold():
    returned = {
        "statement": "Completely unrelated sentence about something else entirely.",
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    assert not facts_match(returned, TRUTH)


def test_facts_match_false_without_citations_is_dropped():
    returned = {
        "statement": STATEMENT,
        "entities": ["E-farebox"],
        "citations": [],
    }
    assert not facts_match(returned, TRUTH)


def test_facts_match_false_when_integers_differ():
    """Review finding: "45 minutes" vs F-003's "30 minutes" scores 0.959 on
    text similarity alone (verified below) but must not match once the
    statements' numbers are required to agree."""
    truth = TruthFact(
        id="F-x",
        statement="A member's first 30 minutes of every ride are free.",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "A member's first 45 minutes of every ride are free.",
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    ratio = difflib.SequenceMatcher(
        None, norm(returned["statement"]), norm(truth.statement)
    ).ratio()
    assert ratio >= 0.6  # sanity: text similarity alone would have matched
    assert not facts_match(returned, truth)


def test_facts_match_false_when_money_differs():
    """Review finding: "$25.00" vs "$30.00" scores 0.648 on text similarity
    alone but must not match."""
    truth = TruthFact(
        id="F-y",
        statement="The most a single ride can cost is $25.00.",
        category="business-logic",
        entities=("E-farebox",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "A single ride costs at most $30.00.",
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    ratio = difflib.SequenceMatcher(
        None, norm(returned["statement"]), norm(truth.statement)
    ).ratio()
    assert ratio >= 0.6
    assert not facts_match(returned, truth)


def test_facts_match_true_when_numbers_match_despite_different_wording():
    truth = TruthFact(
        id="F-z",
        statement="A member's first 30 minutes of every ride are free.",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "Members get the first 30 minutes free on every ride.",
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    assert facts_match(returned, truth)


def test_score_contradictions_winner_rejects_planted_loser():
    """A returned winner whose statement carries the LOSING fact's number
    must not be credited as agreeing with the (different-valued) expected
    winner — this is the same facts_match the number fix applies to."""
    winner_fact = TruthFact(
        id="F-w",
        statement="A single ride costs at most $30.00.",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(Carrier(document="code/pricing.py"),),
    )
    loser_fact = TruthFact(
        id="F-l",
        statement="The most a single ride can cost is $25.00.",
        category="business-logic",
        entities=("E-farebox",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    contradiction = TruthContradiction(
        id="X-1", facts=("F-l", "F-w"), kind="wiki-vs-code", winner="F-w"
    )
    truth_facts = {"F-w": winner_fact, "F-l": loser_fact}

    returned_a = {
        "statement": loser_fact.statement,
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    returned_b = {
        "statement": winner_fact.statement,
        "entities": ["E-farebox"],
        "citations": [{"document": "code/pricing.py"}],
    }
    # The prototype wrongly declares the LOSER's statement as the winner.
    returned_winner_wrong = {
        "statement": loser_fact.statement,
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }

    result = score_contradictions(
        [{"a": returned_a, "b": returned_b, "winner": returned_winner_wrong}],
        {"X-1": contradiction},
        truth_facts,
    )
    assert result["matched"] == 1
    assert result["winner_checked"] == 1
    assert result["winner_correct"] == 0


def test_score_contradictions_tolerates_unknown_fact_id(tmp_path):
    """The entity-filtered contradictions branch in score() must not raise
    KeyError when a contradiction names a fact id that doesn't resolve — a
    broken truth reference contributes no entities from that side, rather
    than crashing scoring for every other surface too."""
    truth_dir = tmp_path / "truth"
    truth_dir.mkdir()
    (truth_dir / "entities.yaml").write_text("- id: E-x\n  kind: service\n  name: x\n")
    (truth_dir / "facts.yaml").write_text(
        "- id: F-known\n"
        "  statement: Known fact.\n"
        "  category: business-logic\n"
        "  entities: [E-x]\n"
        "  tier: documented\n"
        "  carriers:\n"
        "    - document: wiki/x\n"
    )
    (truth_dir / "contradictions.yaml").write_text(
        "- id: X-broken\n  facts: [F-known, F-does-not-exist]\n  kind: wiki-vs-test\n"
    )
    (truth_dir / "stale.yaml").write_text("[]\n")

    results = {
        "prototype": "test",
        "fixture": str(tmp_path),
        "weights": {},
        "ingest": {},
        "queries": [
            {
                "id": "q1",
                "surface": "contradictions",
                "latency_ms": 1.0,
                "params": {"entity": "x"},  # a name, never an id (konyklabs/asbuilt#7)
                "result": [],
            }
        ],
    }
    report = score(results, truth_dir)  # must not raise
    # F-known carries E-x, so X-broken still resolves via that side.
    assert report["surfaces"]["contradictions"]["expected"] == 1


def test_score_stale_credits_multiple_entries_from_one_returned_fact():
    """Review finding: a flawless answer returning one fact that cites two
    stale pages must credit both planted entries, not stop at the first."""
    shared_fact = TruthFact(
        id="F-shared",
        statement="Members ride free for the first 45 minutes.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(
            Carrier(document="wiki/member-pricing"),
            Carrier(document="wiki/support-playbook"),
        ),
    )
    truth_facts = {"F-shared": shared_fact}
    stale_entries = {
        "S-1": StaleEntry(
            id="S-1", document="wiki/member-pricing", states="F-shared", changed_by="c2"
        ),
        "S-2": StaleEntry(
            id="S-2", document="wiki/support-playbook", states="F-shared", changed_by="c2"
        ),
    }
    step_dates = {"c2": datetime.fromisoformat("2026-02-01T00:00:00-05:00")}
    since = datetime.fromisoformat("2026-01-01T00:00:00-05:00")

    returned_fact = {
        "statement": shared_fact.statement,
        "entities": ["E-x"],
        "citations": [
            {"document": "wiki/member-pricing"},
            {"document": "wiki/support-playbook"},
        ],
    }
    result = score_stale([returned_fact], since, stale_entries, step_dates, truth_facts)
    assert result["tp"] == 2
    assert result["expected"] == 2


def test_score_stale_shared_document_disambiguates_by_statement():
    """Review finding: S-005 and S-007 share a document (doc/fares-price-sheet)
    but state different facts; a returned fact citing that document must only
    be credited toward the entry whose statement it actually matches."""
    fact_cap = TruthFact(
        id="F-cap",
        statement="The most a single ride can cost is $25.00.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="doc/shared"),),
    )
    fact_fee = TruthFact(
        id="F-fee",
        statement="The lost-bike fee is $100.00.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="doc/shared"),),
    )
    truth_facts = {"F-cap": fact_cap, "F-fee": fact_fee}
    # F-fee's entry listed first: the old document-only check would grab it
    # regardless of the returned statement, since dict order is insertion order.
    stale_entries = {
        "S-fee": StaleEntry(id="S-fee", document="doc/shared", states="F-fee", changed_by="c2"),
        "S-cap": StaleEntry(id="S-cap", document="doc/shared", states="F-cap", changed_by="c2"),
    }
    step_dates = {"c2": datetime.fromisoformat("2026-02-01T00:00:00-05:00")}
    since = datetime.fromisoformat("2026-01-01T00:00:00-05:00")

    # Cites the shared document but its statement matches neither entry: the
    # old document-only check would still have credited one; must credit none.
    returned_unrelated = {
        "statement": "Something else entirely, sharing no numbers with either.",
        "entities": ["E-x"],
        "citations": [{"document": "doc/shared"}],
    }
    result_unrelated = score_stale(
        [returned_unrelated], since, stale_entries, step_dates, truth_facts
    )
    assert result_unrelated["tp"] == 0
    assert result_unrelated["expected"] == 2

    # Its statement genuinely matches F-cap: only S-cap should be credited.
    returned_cap = {
        "statement": fact_cap.statement,
        "entities": ["E-x"],
        "citations": [{"document": "doc/shared"}],
    }
    result_cap = score_stale([returned_cap], since, stale_entries, step_dates, truth_facts)
    assert result_cap["tp"] == 1


def test_match_facts_disambiguates_by_version():
    """F-001 and F-003 share a statement and a code document, at versions c1
    and c4; a returned citation's version picks the right one."""
    facts = load_facts(MINI_ROOT / "truth" / "facts.yaml")
    expected = {"F-001": facts["F-001"], "F-003": facts["F-003"]}

    def returned_with_version(version: str) -> dict:
        return {
            "statement": "A member's free minutes are 15.",
            "entities": ["E-farebox", "E-rule-member-free-minutes"],
            "citations": [{"document": "code/farebox/pricing.py", "version": version}],
        }

    matches_c1, uncited_c1 = match_facts([returned_with_version("c1")], expected)
    assert uncited_c1 == 0
    assert matches_c1[0][1] == "F-001"

    matches_c4, _ = match_facts([returned_with_version("c4")], expected)
    assert matches_c4[0][1] == "F-003"


def test_match_facts_disambiguates_by_sha_via_commits():
    facts = load_facts(MINI_ROOT / "truth" / "facts.yaml")
    expected = {"F-001": facts["F-001"], "F-003": facts["F-003"]}
    commits = {"c4": {"sha": "deadbeefsha"}}
    returned = {
        "statement": "A member's free minutes are 15.",
        "entities": ["E-farebox", "E-rule-member-free-minutes"],
        "citations": [{"document": "code/farebox/pricing.py", "version": "deadbeefsha"}],
    }
    matches, _ = match_facts([returned], expected, commits)
    assert matches[0][1] == "F-003"


def _hand_built_results() -> dict:
    """One explain/search hit whose version disambiguates to F-003 (not
    F-001, which shares its statement and code document), one search miss.
    Entities are given as NAMES (bench/protocol.py: arms never return ids),
    deliberately using two different aliases from tests/fixtures/mini/truth/
    aliases.yaml ("Farebox" and "member free minutes") to exercise the
    scorer's own alignment through `score()`, not just the loader."""
    correct = {
        "statement": "A member's free minutes are 15.",
        "category": "business-logic",
        "entities": ["Farebox", "member free minutes"],
        "tier": "executed",
        "citations": [{"document": "code/farebox/pricing.py", "version": "c4"}],
        "valid_from": None,
        "valid_to": None,
        "confidence": None,
    }
    wrong = {
        "statement": "Totally unrelated statement about something else.",
        "category": "operations",
        "entities": ["farebox"],
        "tier": "documented",
        "citations": [{"document": "wiki/pricing-rules"}],
        "valid_from": None,
        "valid_to": None,
        "confidence": None,
    }
    return {
        "prototype": "hand-built",
        "fixture": str(MINI_ROOT),
        "weights": {"explain": 1.0, "search": 1.0, "ask": 1.0, "contradictions": 1.0, "stale": 1.0},
        "ingest": {
            "seconds": 1.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "dollars": 0.0,
            "services": [],
            "documents": 5,
        },
        "queries": [
            {
                "id": "q-explain-1",
                "surface": "explain",
                "latency_ms": 1.0,
                "params": {"entity": "member-free-minutes"},
                "result": [correct],
            },
            {
                "id": "q-search-1",
                "surface": "search",
                "latency_ms": 1.0,
                "params": {"query": "free minutes", "expects": ["F-001", "F-003"]},
                "result": [correct, wrong],
            },
            {
                "id": "q-ask-1",
                "surface": "ask",
                "latency_ms": 1.0,
                "params": {"question": "How many free minutes?", "expects": ["F-003"]},
                "result": {"sentences": []},
            },
            {
                "id": "q-contradictions-1",
                "surface": "contradictions",
                "latency_ms": 1.0,
                "params": {"entity": "member-free-minutes"},
                "result": [],
            },
            {
                "id": "q-stale-1",
                "surface": "stale",
                "latency_ms": 1.0,
                "params": {"since": "2026-01-15T00:00:00-05:00"},
                "result": [],
            },
        ],
    }


def test_score_hand_built_results_known_precision_recall():
    report = score(_hand_built_results(), MINI_ROOT / "truth")

    # explain: 1 returned, matches F-003 (not F-001, by version); expected =
    # {F-001, F-002, F-003, F-005} (all four name the entity).
    explain = report["surfaces"]["explain"]
    assert explain["tp"] == 1
    assert explain["returned"] == 1
    assert explain["expected"] == 4
    assert explain["precision"] == 1.0
    assert explain["recall"] == 0.25

    # search: 2 returned (1 correct -> F-003, 1 wrong-but-cited), expected = F-001, F-003.
    search = report["surfaces"]["search"]
    assert search["tp"] == 1
    assert search["returned"] == 2
    assert search["expected"] == 2
    assert search["precision"] == 0.5
    assert search["recall"] == 0.5

    # ask: no sentences -> precision undefined (0 denominator); recall is a
    # real 0.0, not undefined, since expected has one fact (F-003).
    ask = report["surfaces"]["ask"]
    assert ask["precision"] is None
    assert ask["recall"] == 0.0

    # contradictions/stale: nothing returned, something expected -> recall 0, precision n/a.
    assert report["surfaces"]["contradictions"]["recall"] == 0.0
    assert report["surfaces"]["contradictions"]["precision"] is None
    assert report["surfaces"]["stale"]["recall"] == 0.0

    # entity resolution: the matched explain fact's two aliased names both
    # resolved and both agree with F-003's own entities.
    er = explain["entity_resolution"]
    assert er["tp"] == 2
    assert er["returned"] == 2
    assert er["expected"] == 2
    assert er["precision"] == 1.0
    assert er["recall"] == 1.0
    assert er["unresolved"] == []


def test_null_prototype_zero_scores_with_correct_denominators():
    results = run(MINI_ROOT, "null")
    report = score(results, MINI_ROOT / "truth")

    for name in ("explain", "search", "stale"):
        surface = report["surfaces"][name]
        assert surface["tp"] == 0
        assert surface["returned"] == 0
        assert surface["expected"] > 0
        assert surface["precision"] is None
        assert surface["recall"] == 0.0

    ask = report["surfaces"]["ask"]
    assert ask["sentences"] == 0
    assert ask["expected"] == 1
    assert ask["precision"] is None
    assert ask["recall"] == 0.0

    contradictions = report["surfaces"]["contradictions"]
    assert contradictions["matched"] == 0
    assert contradictions["expected"] == 1
    assert contradictions["recall"] == 0.0

    assert report["headline"] == 0.0


# --------------------------------------------------------------------------
# Entity alignment (konyklabs/asbuilt#7): arms return names, the scorer
# aligns them to truth ids through the alias index.
# --------------------------------------------------------------------------


def test_align_entities_resolves_name_and_alias_case_insensitively():
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    resolved, unresolved = align_entities(["Farebox", "FARE BOX", "member free minutes"], index)
    assert resolved == ["E-farebox", "E-rule-member-free-minutes"]
    assert unresolved == []


def test_align_entities_no_longer_resolves_a_bare_id():
    """konyklabs/asbuilt#7 review: an arm emitting a raw E- id (instead of a
    name) must not "resolve" for free — that would let it skip real entity
    resolution entirely. queries/mix.yaml's own entity fields are names now,
    so there is no caller left that needs id lookup to keep working."""
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    resolved, unresolved = align_entities(["E-farebox"], index)
    assert resolved == []
    assert unresolved == ["E-farebox"]


def test_align_entities_fuzzy_fallback_on_a_typo():
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    resolved, unresolved = align_entities(["farebx"], index)  # missing an 'o'
    assert resolved == ["E-farebox"]
    assert unresolved == []


def test_align_entities_unresolved_name_is_reported_not_dropped():
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    resolved, unresolved = align_entities(["a completely unrelated name"], index)
    assert resolved == []
    assert unresolved == ["a completely unrelated name"]


def test_align_entities_ambiguous_fuzzy_match_is_not_guessed():
    """Two entities equidistant (by SequenceMatcher ratio) from a typo at
    the fuzzy cutoff must not be resolved to either, and (with no `entities`/
    `category` given to disambiguate by kind) stay unresolved."""
    index = {"station alpha": ["E-a"], "station alphb": ["E-b"]}
    resolved, unresolved = align_entities(["station alphx"], index)
    assert resolved == []
    assert unresolved == ["station alphx"]


def test_align_entities_keeps_hyphen_and_underscore_distinct():
    """konyklabs/asbuilt#7 review: `ebike_surcharge` (a flag) and
    `ebike-surcharge` (a rule) are different entities in the real fixture;
    normalising both separators to the same thing would collide them."""
    index = {"ebike_surcharge": ["E-flag"], "ebike-surcharge": ["E-rule"]}
    resolved, _ = align_entities(["ebike_surcharge"], index)
    assert resolved == ["E-flag"]
    resolved, _ = align_entities(["ebike-surcharge"], index)
    assert resolved == ["E-rule"]


def test_align_entities_disambiguates_a_tied_fuzzy_match_by_category_kind():
    """The real collision case: a query written with a space ("ebike
    surcharge") is equally one character away from both the flag's name
    (underscore) and the rule's name (hyphen); the caller's category picks
    the entity whose kind matches."""
    flag = Entity(id="E-flag-ebike-surcharge", kind="flag", name="ebike_surcharge")
    rule = Entity(id="E-rule-ebike-surcharge", kind="rule", name="ebike-surcharge")
    index = {
        "ebike_surcharge": ["E-flag-ebike-surcharge"],
        "ebike-surcharge": ["E-rule-ebike-surcharge"],
    }
    entities = {flag.id: flag, rule.id: rule}

    resolved, unresolved = align_entities(
        ["ebike surcharge"], index, entities, category="technical-implementation"
    )
    assert resolved == ["E-flag-ebike-surcharge"]
    assert unresolved == []

    resolved, unresolved = align_entities(
        ["ebike surcharge"], index, entities, category="business-logic"
    )
    assert resolved == ["E-rule-ebike-surcharge"]
    assert unresolved == []

    # No category (or one with no kind preference) -> still ambiguous -> unresolved.
    resolved, unresolved = align_entities(["ebike surcharge"], index, entities, category=None)
    assert resolved == []
    assert unresolved == ["ebike surcharge"]


def test_resolve_fact_entities_disambiguates_by_the_facts_own_category():
    flag = Entity(id="E-flag-ebike-surcharge", kind="flag", name="ebike_surcharge")
    rule = Entity(id="E-rule-ebike-surcharge", kind="rule", name="ebike-surcharge")
    index = {
        "ebike_surcharge": ["E-flag-ebike-surcharge"],
        "ebike-surcharge": ["E-rule-ebike-surcharge"],
    }
    entities = {flag.id: flag, rule.id: rule}

    fact = {"entities": ["ebike surcharge"], "category": "business-logic", "statement": "x"}
    resolved = resolve_fact_entities(fact, index, entities)
    assert resolved["entities"] == ["E-rule-ebike-surcharge"]
    assert resolved["_unresolved_entities"] == []


@pytest.mark.fixture
def test_real_fixture_ebike_surcharge_flag_and_rule_resolve_distinctly():
    """The actual collision the review flagged: truth/entities.yaml carries
    both E-flag-ebike-surcharge (name "ebike_surcharge") and
    E-rule-ebike-surcharge (name "ebike-surcharge") — this uses the real
    truth/, not a synthetic index. Their canonical (underscore vs hyphen)
    names resolve exactly, distinctly, and unambiguously."""
    truth = load_truth(SPIKE_ROOT / "truth")
    if not truth.entities:
        pytest.skip()
    index = build_alias_index(truth)

    resolved, unresolved = align_entities(["ebike_surcharge"], index, truth.entities)
    assert resolved == ["E-flag-ebike-surcharge"]
    assert unresolved == []

    resolved, unresolved = align_entities(["ebike-surcharge"], index, truth.entities)
    assert resolved == ["E-rule-ebike-surcharge"]
    assert unresolved == []


@pytest.mark.fixture
def test_real_fixture_refund_auto_approve_tied_match_by_category():
    """`refund_auto_approve` (flag) and `refund-auto-approve` (rule) both
    fold (see `_fold_separators`) to "refundautoapprove", the same as the
    punctuation-free query "refund auto approve" — an exact tie on the
    folded key (not a fuzzy one: 0.8947 SequenceMatcher ratio was the old,
    now-superseded, tie point before the folded-exact pass existed), and the
    category disambiguates it."""
    truth = load_truth(SPIKE_ROOT / "truth")
    if not truth.entities:
        pytest.skip()
    index = build_alias_index(truth)

    resolved, unresolved = align_entities(
        ["refund auto approve"], index, truth.entities, category="technical-implementation"
    )
    assert resolved == ["E-flag-refund-auto-approve"]
    assert unresolved == []

    resolved, unresolved = align_entities(
        ["refund auto approve"], index, truth.entities, category="business-logic"
    )
    assert resolved == ["E-rule-refund-auto-approve"]
    assert unresolved == []

    resolved, unresolved = align_entities(["refund auto approve"], index, truth.entities)
    assert resolved == []
    assert unresolved == ["refund auto approve"]


def test_real_fixture_ebike_surcharge_space_query_disambiguates_by_category():
    """The bug the review found: "ebike surcharge" (space) used to resolve
    to the rule for EVERY category, because the rule's alias "e-bike
    surcharge" outscored both canonical names on fuzzy similarity (0.968 vs
    0.933) before category disambiguation ever ran. The folded-exact pass
    (both canonical names AND that alias fold to "ebikesurcharge") now ties
    them honestly, so category actually decides."""
    truth = load_truth(SPIKE_ROOT / "truth")
    if not truth.entities:
        pytest.skip()
    index = build_alias_index(truth)

    resolved, _ = align_entities(
        ["ebike surcharge"], index, truth.entities, category="technical-implementation"
    )
    assert resolved == ["E-flag-ebike-surcharge"]

    resolved, _ = align_entities(
        ["ebike surcharge"], index, truth.entities, category="business-logic"
    )
    assert resolved == ["E-rule-ebike-surcharge"]


def test_resolve_fact_entities_keeps_unresolved_names_for_audit():
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    fact = {"entities": ["Farebox", "nonsense-entity"], "statement": "x", "citations": []}
    resolved = resolve_fact_entities(fact, index)
    assert resolved["entities"] == ["E-farebox"]
    assert resolved["_unresolved_entities"] == ["nonsense-entity"]


# --------------------------------------------------------------------------
# Tier confusion, executed-tier hard errors, category & validity accuracy
#
# These tests exercise score_fact_query's own bookkeeping, not entity
# alignment (which has its own tests above) — `_identity_index` is a
# minimal alias index mapping each ad-hoc id's normalised form to itself, so
# a returned fact naming the SAME id string as the truth fact resolves
# like-for-like without a real Truth/aliases fixture behind it.
# --------------------------------------------------------------------------


def _identity_index(*entity_ids: str) -> dict[str, list[str]]:
    return {norm_entity(eid): [eid] for eid in entity_ids}


def test_score_fact_query_tier_confusion_and_executed_precision_recall():
    truth_executed = TruthFact(
        id="F-e",
        statement="A ride costs $30.",
        category="business-logic",
        entities=("E-x",),
        tier="executed",
        carriers=(Carrier(document="run/pytest-c1", location="t"),),
    )
    truth_code = TruthFact(
        id="F-c",
        statement="A refund window is 14 days.",
        category="business-logic",
        entities=("E-x",),
        tier="code",
        carriers=(Carrier(document="code/x.py"),),
    )
    expected = {"F-e": truth_executed, "F-c": truth_code}

    returned_correct_executed = {
        "statement": "A ride costs $30.",
        "entities": ["E-x"],
        "tier": "executed",
        "category": "business-logic",
        "citations": [{"document": "run/pytest-c1"}],
    }
    # Matches the CODE-tier truth fact but wrongly claims "executed" — lands
    # off the confusion matrix's diagonal, and (no run/ citation) is also a
    # hard error.
    returned_wrong_tier = {
        "statement": "A refund window is 14 days.",
        "entities": ["E-x"],
        "tier": "executed",
        "category": "business-logic",
        "citations": [{"document": "code/x.py"}],
    }
    # Claims "executed" but matches nothing at all — still counts toward
    # returned_executed (a wrong claim, whether or not it happens to match
    # something) and is a hard error (no run/ citation).
    returned_unmatched_executed = {
        "statement": "Something else entirely, with a $5 number.",
        "entities": ["E-x"],
        "tier": "executed",
        "category": "business-logic",
        "citations": [{"document": "wiki/somewhere"}],
    }

    result = score_fact_query(
        [returned_correct_executed, returned_wrong_tier, returned_unmatched_executed],
        expected,
        alias_index=_identity_index("E-x"),
    )
    tier = result["tier"]
    assert tier["confusion"] == {"executed": {"executed": 1}, "code": {"executed": 1}}
    assert tier["returned_executed"] == 3
    assert tier["tp_executed"] == 1
    assert tier["expected_executed"] == 1
    assert tier["hard_errors"] == 2


def test_score_fact_query_category_and_validity_accuracy():
    truth = TruthFact(
        id="F-v",
        statement="Grace was 3 days before c3.",
        category="history",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
        valid_to="c3",
    )
    expected = {"F-v": truth}
    returned_right = {
        "statement": "Grace was 3 days before c3.",
        "entities": ["E-x"],
        "category": "history",
        "citations": [{"document": "wiki/x"}],
        "valid_from": None,
        "valid_to": "c3",
    }
    result = score_fact_query([returned_right], expected, alias_index=_identity_index("E-x"))
    assert result["category_accuracy"] == {"correct": 1, "total": 1}
    assert result["validity"] == {"correct": 1, "total": 1}


def test_score_fact_query_wrong_category_and_validity_are_not_credited():
    truth = TruthFact(
        id="F-v",
        statement="Grace was 3 days before c3.",
        category="history",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
        valid_to="c3",
    )
    expected = {"F-v": truth}
    returned_wrong = {
        "statement": "Grace was 3 days before c3.",
        "entities": ["E-x"],
        "category": "operations",
        "citations": [{"document": "wiki/x"}],
        "valid_from": None,
        "valid_to": "c5",
    }
    result = score_fact_query([returned_wrong], expected, alias_index=_identity_index("E-x"))
    assert result["category_accuracy"] == {"correct": 0, "total": 1}
    assert result["validity"] == {"correct": 0, "total": 1}


def test_score_fact_query_validity_resolves_sha_via_commits():
    truth = TruthFact(
        id="F-v",
        statement="X",
        category="history",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
        valid_to="c3",
    )
    expected = {"F-v": truth}
    returned = {
        "statement": "X",
        "entities": ["E-x"],
        "category": "history",
        "citations": [{"document": "wiki/x"}],
        "valid_from": None,
        "valid_to": "deadbeef",
    }
    commits = {"c3": {"sha": "deadbeef"}}
    result = score_fact_query([returned], expected, commits, alias_index=_identity_index("E-x"))
    assert result["validity"] == {"correct": 1, "total": 1}


def test_score_fact_query_validity_excludes_facts_with_no_valid_from_or_to():
    truth = TruthFact(
        id="F-open",
        statement="X",
        category="history",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    expected = {"F-open": truth}
    returned = {
        "statement": "X",
        "entities": ["E-x"],
        "category": "history",
        "citations": [{"document": "wiki/x"}],
    }
    result = score_fact_query([returned], expected, alias_index=_identity_index("E-x"))
    assert result["validity"] == {"correct": 0, "total": 0}


# --------------------------------------------------------------------------
# Validity matching by datetime instant, and every cited version
# (konyklabs/asbuilt#4 review)
# --------------------------------------------------------------------------

_STACK_B_COMMITS = {
    "c1": {"sha": "s1", "date": "2026-01-12T10:00:00-05:00"},
    "c5": {"sha": "s5", "date": "2026-07-22T14:00:00-04:00"},
}


def test_resolve_temporal_value_to_step_tolerates_offset_and_rounding():
    # Same instant as c5, but serialised in UTC with a fractional second.
    assert _resolve_temporal_value_to_step("2026-07-22T18:00:00.4+00:00", _STACK_B_COMMITS) == "c5"
    # More than a second off -> no match.
    assert _resolve_temporal_value_to_step("2026-07-22T18:00:03+00:00", _STACK_B_COMMITS) is None
    # Already a step id or a SHA still resolves directly.
    assert _resolve_temporal_value_to_step("c1", _STACK_B_COMMITS) == "c1"
    assert _resolve_temporal_value_to_step("s5", _STACK_B_COMMITS) == "c5"
    # Not datetime-shaped and not found in commits -> passed through
    # unchanged (an already-correct step id must still compare equal even
    # with no commits.json, or a minimal one, at hand).
    assert _resolve_temporal_value_to_step("c9", {}) == "c9"


def test_temporal_field_matches_maps_a_returned_datetime_to_its_step():
    assert _temporal_field_matches("2026-07-22T18:00:00+00:00", "c5", _STACK_B_COMMITS)
    assert not _temporal_field_matches("2026-01-12T15:00:00+00:00", "c5", _STACK_B_COMMITS)


def test_temporal_field_matches_open_valid_from_accepts_first_step_or_none():
    first_step = _first_step(_STACK_B_COMMITS)
    assert first_step == "c1"
    assert _temporal_field_matches(None, None, _STACK_B_COMMITS, first_step)
    assert _temporal_field_matches("2026-01-12T15:00:00+00:00", None, _STACK_B_COMMITS, first_step)
    # c5's own date, not the first step's -> still open-ended is false.
    assert not _temporal_field_matches(
        "2026-07-22T18:00:00+00:00", None, _STACK_B_COMMITS, first_step
    )
    # valid_to's caller never passes first_step -- only an absent value
    # counts as open there.
    assert not _temporal_field_matches("2026-01-12T15:00:00+00:00", None, _STACK_B_COMMITS)


def test_shares_matching_version_checks_every_cited_version_not_just_the_last():
    """konyklabs/asbuilt#4 review, reproduced: a fact re-cited across every
    commit its test ran at (c4, c5, c6) previously kept only the LAST
    version for that document (a dict comprehension overwrites on a
    repeated key), so a truth carrier at an EARLIER version (c4) never
    matched."""
    truth_fact = TruthFact(
        id="F-early",
        statement="x",
        category="business-logic",
        entities=("E-x",),
        tier="executed",
        carriers=(Carrier(document="code/t.py", version="c4"),),
    )
    returned = {
        "citations": [
            {"document": "code/t.py", "version": "sha-c4"},
            {"document": "code/t.py", "version": "sha-c5"},
            {"document": "code/t.py", "version": "sha-c6"},
        ]
    }
    commits = {"c4": {"sha": "sha-c4"}, "c5": {"sha": "sha-c5"}, "c6": {"sha": "sha-c6"}}
    assert _shares_matching_version(returned, truth_fact, commits)


# --------------------------------------------------------------------------
# Unmatched returned facts: hard false positives vs. unplanted; precision@5
# and recall@10 (search)
# --------------------------------------------------------------------------


def test_classify_unmatched_hard_false_positive_vs_unplanted():
    truth_fact = TruthFact(
        id="F-1",
        statement="A ride costs $30.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    all_facts = {"F-1": truth_fact}
    hard_fp_candidate = {  # same entity+document as F-1, wrong number
        "statement": "A ride costs $99.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    unplanted_candidate = {  # no entity/document overlap with anything
        "statement": "Something never planted.",
        "entities": ["E-nowhere"],
        "citations": [{"document": "wiki/nowhere"}],
    }
    hard_fp, unplanted = classify_unmatched([hard_fp_candidate, unplanted_candidate], all_facts)
    assert hard_fp == [hard_fp_candidate]
    assert unplanted == [unplanted_candidate]


def test_score_fact_query_reports_hard_false_positives_and_unplanted():
    truth_fact = TruthFact(
        id="F-1",
        statement="A ride costs $30.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    expected = {"F-1": truth_fact}
    hard_fp_candidate = {
        "statement": "A ride costs $99.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    unplanted_candidate = {
        "statement": "Something never planted.",
        "entities": ["E-nowhere"],
        "citations": [{"document": "wiki/nowhere"}],
    }
    result = score_fact_query(
        [hard_fp_candidate, unplanted_candidate],
        expected,
        alias_index=_identity_index("E-x", "E-nowhere"),
    )
    assert result["hard_false_positives"] == 1
    # unplanted_facts carries the resolved copy (entities as ids, plus the
    # private _unresolved_entities audit key), not the original dict as-is.
    assert len(result["unplanted_facts"]) == 1
    assert result["unplanted_facts"][0]["statement"] == unplanted_candidate["statement"]


def test_score_fact_query_uncited_fact_is_not_also_unplanted():
    """konyklabs/asbuilt#7 review: a fact with no citations was counted
    once as `uncited` (in match_facts) and AGAIN as unplanted — the same
    fact must not show up in both."""
    truth_fact = TruthFact(
        id="F-1",
        statement="A ride costs $30.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    uncited_candidate = {"statement": "A ride costs $30.", "entities": ["E-x"], "citations": []}
    result = score_fact_query(
        [uncited_candidate], {"F-1": truth_fact}, alias_index=_identity_index("E-x")
    )
    assert result["uncited"] == 1
    assert result["hard_false_positives"] == 0
    assert result["unplanted_facts"] == []


def test_facts_match_citation_without_document_key_is_not_a_keyerror():
    truth_fact = TruthFact(
        id="F-1",
        statement="A ride costs $30.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    malformed = {
        "statement": "A ride costs $30.",
        "entities": ["E-x"],
        "citations": [{"location": "#somewhere"}],  # no "document" key
    }
    assert not facts_match(malformed, truth_fact)  # must not raise KeyError


def test_score_ask_query_citation_without_document_key_is_ignored():
    fact = _free_minutes_fact()
    answer = {
        "sentences": [
            {
                "text": "Members get their first 30 minutes free.",
                "citations": [{"location": "#x"}],  # no "document" key
            }
        ]
    }
    result = score_ask_query(answer, {"F-1": fact})  # must not raise KeyError
    assert result["correct_sentences"] == 0


def test_score_fact_query_hard_false_positive_uses_full_truth_set():
    """A returned fact about an entity/document pair that isn't in this
    query's own `expected` but IS elsewhere in the ground truth is still a
    hard false positive, not unplanted noise (module docstring)."""
    truth_fact = TruthFact(
        id="F-elsewhere",
        statement="A different rule.",
        category="business-logic",
        entities=("E-y",),
        tier="documented",
        carriers=(Carrier(document="wiki/y"),),
    )
    all_facts = {"F-elsewhere": truth_fact}
    candidate = {
        "statement": "A different rule entirely, with a $1 twist.",
        "entities": ["E-y"],
        "citations": [{"document": "wiki/y"}],
    }
    result = score_fact_query(
        [candidate], expected={}, alias_index=_identity_index("E-y"), all_facts=all_facts
    )
    assert result["hard_false_positives"] == 1
    assert result["unplanted_facts"] == []


def test_score_fact_query_precision_at_5_and_recall_at_10():
    facts = {
        f"F-{i}": TruthFact(
            id=f"F-{i}",
            statement=f"Fact number {i}.",
            category="business-logic",
            entities=("E-x",),
            tier="documented",
            carriers=(Carrier(document=f"wiki/{i}"),),
        )
        for i in range(1, 4)
    }
    returned = [
        {
            "statement": "Unrelated filler.",
            "entities": ["E-x"],
            "citations": [{"document": "wiki/nowhere"}],
        }
        for _ in range(5)
    ]
    returned.append(
        {
            "statement": "Fact number 1.",
            "entities": ["E-x"],
            "citations": [{"document": "wiki/1"}],
        }
    )
    result = score_fact_query(returned, facts, alias_index=_identity_index("E-x"))
    assert result["rank"] == {"p5_hits": 0, "p5_n": 5, "r10_hits": 1}


# --------------------------------------------------------------------------
# ask: text-match (not citation-only), and the per-sentence citation cap
# --------------------------------------------------------------------------


def _free_minutes_fact() -> TruthFact:
    return TruthFact(
        id="F-1",
        statement="A member's first 30 minutes are free.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/pricing"),),
    )


def test_score_ask_query_requires_text_match_not_just_citation():
    expected = {"F-1": _free_minutes_fact()}
    # Cites the right document but states something unrelated: must not count.
    answer = {
        "sentences": [
            {"text": "The weather was nice that day.", "citations": [{"document": "wiki/pricing"}]}
        ]
    }
    result = score_ask_query(answer, expected)
    assert result["correct_sentences"] == 0
    assert result["covered_facts"] == 0


def test_score_ask_query_credits_a_text_and_citation_match():
    expected = {"F-1": _free_minutes_fact()}
    answer = {
        "sentences": [
            {
                "text": "Members get their first 30 minutes free.",
                "citations": [{"document": "wiki/pricing"}],
            }
        ]
    }
    result = score_ask_query(answer, expected)
    assert result["correct_sentences"] == 1
    assert result["covered_facts"] == 1


def test_score_ask_query_citation_cap_ignores_extra_citations():
    expected = {"F-1": _free_minutes_fact()}
    # The correct citation is 4th; with a cap of 3 it's never considered.
    answer = {
        "sentences": [
            {
                "text": "Members get their first 30 minutes free.",
                "citations": [
                    {"document": "wiki/a"},
                    {"document": "wiki/b"},
                    {"document": "wiki/c"},
                    {"document": "wiki/pricing"},
                ],
            }
        ]
    }
    capped = score_ask_query(answer, expected, citation_cap=3)
    assert capped["correct_sentences"] == 0
    uncapped = score_ask_query(answer, expected, citation_cap=4)
    assert uncapped["correct_sentences"] == 1


# --------------------------------------------------------------------------
# contradictions: precision (returned/matched), in addition to recall
# --------------------------------------------------------------------------


def test_score_contradictions_reports_precision():
    fact_a = TruthFact(
        id="F-a",
        statement="A.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/a"),),
    )
    fact_b = TruthFact(
        id="F-b",
        statement="B.",
        category="business-logic",
        entities=("E-x",),
        tier="executed",
        carriers=(Carrier(document="run/r1"),),
    )
    contradiction = TruthContradiction(id="X-1", facts=("F-a", "F-b"), kind="wiki-vs-test")
    expected = {"X-1": contradiction}
    truth_facts = {"F-a": fact_a, "F-b": fact_b}

    returned_a = {"statement": "A.", "entities": ["E-x"], "citations": [{"document": "wiki/a"}]}
    returned_b = {"statement": "B.", "entities": ["E-x"], "citations": [{"document": "run/r1"}]}
    returned_bogus_a = {
        "statement": "Nothing like A.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/nowhere"}],
    }
    returned_bogus_b = {
        "statement": "Nothing like B.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/nowhere"}],
    }

    result = score_contradictions(
        [{"a": returned_a, "b": returned_b}, {"a": returned_bogus_a, "b": returned_bogus_b}],
        expected,
        truth_facts,
    )
    assert result["matched"] == 1
    assert result["returned"] == 2


def test_score_contradictions_precision_via_score():
    facts = load_facts(MINI_ROOT / "truth" / "facts.yaml")
    f3, f5 = facts["F-003"], facts["F-005"]

    def _fact(fact):
        return {
            "statement": fact.statement,
            "entities": ["farebox", "member-free-minutes"],
            "citations": [{"document": c.document} for c in fact.carriers],
        }

    returned_correct = {"a": _fact(f5), "b": _fact(f3), "winner": _fact(f3)}
    returned_bogus = {
        "a": {
            "statement": "Nothing.",
            "entities": ["farebox"],
            "citations": [{"document": "wiki/nowhere"}],
        },
        "b": {
            "statement": "Nothing else.",
            "entities": ["farebox"],
            "citations": [{"document": "wiki/nowhere"}],
        },
    }
    results = {
        "prototype": "test",
        "fixture": str(MINI_ROOT),
        "weights": {},
        "ingest": {},
        "queries": [
            {
                "id": "q1",
                "surface": "contradictions",
                "latency_ms": 1.0,
                "params": {"entity": None},
                "result": [returned_correct, returned_bogus],
            }
        ],
    }
    report = score(results, MINI_ROOT / "truth")
    c = report["surfaces"]["contradictions"]
    assert c["matched"] == 1
    assert c["returned"] == 2
    assert c["expected"] == 1
    assert c["precision"] == 0.5
    assert c["recall"] == 1.0


# --------------------------------------------------------------------------
# Multiple runs (median/min/max) and the paired bootstrap comparison
# --------------------------------------------------------------------------


def test_aggregate_reports_median_min_max():
    good = score(_hand_built_results(), MINI_ROOT / "truth")
    worse_results = _hand_built_results()
    worse_results["queries"][0]["result"] = []  # explain returns nothing this run
    worse = score(worse_results, MINI_ROOT / "truth")

    agg = aggregate_reports([good, worse])
    recall_stats = agg["surfaces"]["explain"]["recall"]
    assert recall_stats["max"] == good["surfaces"]["explain"]["recall"]
    assert recall_stats["min"] == worse["surfaces"]["explain"]["recall"]
    assert recall_stats["min"] <= recall_stats["median"] <= recall_stats["max"]


def test_bootstrap_compare_identical_arms_diff_is_zero():
    report = score(_hand_built_results(), MINI_ROOT / "truth")
    comparison = bootstrap_compare(report["by_query"], report["by_query"], iterations=200, seed=0)
    for name in ("explain", "search", "ask", "contradictions", "stale"):
        c = comparison["surfaces"][name]
        assert c["point_diff"] == 0.0
        assert not c["excludes_zero"]


def test_bootstrap_compare_is_deterministic_with_a_fixed_seed():
    report_a = score(_hand_built_results(), MINI_ROOT / "truth")
    worse_results = _hand_built_results()
    worse_results["queries"][1]["result"] = []  # search returns nothing
    report_b = score(worse_results, MINI_ROOT / "truth")

    c1 = bootstrap_compare(report_a["by_query"], report_b["by_query"], iterations=200, seed=42)
    c2 = bootstrap_compare(report_a["by_query"], report_b["by_query"], iterations=200, seed=42)
    assert c1 == c2


def test_bootstrap_compare_errors_on_mismatched_query_ids():
    """konyklabs/asbuilt#7 review: pairing must be by query id, erroring on
    a mismatch, never silently truncating to the shorter arm."""
    report_a = score(_hand_built_results(), MINI_ROOT / "truth")
    renamed_results = _hand_built_results()
    renamed_results["queries"][0]["id"] = "q-explain-renamed"
    report_b = score(renamed_results, MINI_ROOT / "truth")

    with pytest.raises(ValueError, match="query id sets differ"):
        bootstrap_compare(report_a["by_query"], report_b["by_query"], iterations=50, seed=0)


def test_bootstrap_compare_detects_a_real_difference():
    report_a = score(_hand_built_results(), MINI_ROOT / "truth")
    worse_results = _hand_built_results()
    worse_results["queries"][1]["result"] = []  # search returns nothing
    report_b = score(worse_results, MINI_ROOT / "truth")

    comparison = bootstrap_compare(
        report_a["by_query"], report_b["by_query"], iterations=200, seed=1
    )
    search = comparison["surfaces"]["search"]
    assert search["point_diff"] > 0
    assert search["excludes_zero"]


def test_print_multi_report_smoke(capsys):
    report = score(_hand_built_results(), MINI_ROOT / "truth")
    print_multi_report([report, report])
    out = capsys.readouterr().out
    assert "across 2 runs" in out


def test_print_comparison_smoke(capsys):
    report = score(_hand_built_results(), MINI_ROOT / "truth")
    comparison = bootstrap_compare(report["by_query"], report["by_query"], iterations=50, seed=0)
    print_comparison(comparison)
    out = capsys.readouterr().out
    assert "executed_precision" in out


# --------------------------------------------------------------------------
# Matcher hardening: number words, prose dates, clock times, negation
# --------------------------------------------------------------------------


def test_statement_matches_number_words():
    truth = TruthFact(
        id="F-1",
        statement="3 fault reports lock the bike.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "Three fault reports lock the bike.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    assert facts_match(returned, truth)


def test_statement_matches_prose_date():
    truth = TruthFact(
        id="F-1",
        statement="The promotion ended on 2026-04-01.",
        category="history",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "The promotion ended on April 1, 2026.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    assert facts_match(returned, truth)


def test_statement_matches_clock_time():
    truth = TruthFact(
        id="F-1",
        statement="The job runs at 03:00.",
        category="operations",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "The job runs at 3am.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    assert facts_match(returned, truth)


def test_statement_matches_negation_guard_blocks_a_polarity_flip():
    truth = TruthFact(
        id="F-1",
        statement="Dynamic pricing is on in production.",
        category="operations",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "Dynamic pricing is off in production.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    assert not facts_match(returned, truth)


def test_statement_matches_negation_guard_catches_a_contraction():
    truth = TruthFact(
        id="F-1",
        statement="Casual riders can unlock a bike without a membership.",
        category="business-logic",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    returned = {
        "statement": "Casual riders cannot unlock a bike without a membership.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
    }
    assert not facts_match(returned, truth)


# --------------------------------------------------------------------------
# Entity-mention conflict guard (konyklabs/asbuilt#7 review): mentions of a
# team/service/integration/queue/job/flag entity are read straight out of
# the mini fixture's own aliases.yaml — no hardcoded vocabulary in the
# guard, and none in these tests either.
# --------------------------------------------------------------------------


def test_build_mention_index_covers_mention_kinds_only():
    truth = load_truth(MINI_ROOT / "truth")
    mention_index = build_mention_index(truth)
    kinds = {kind for _, _, kind in mention_index}
    assert kinds == {"service", "team"}  # the mini fixture has no integration/queue/job/flag
    ids = {entity_id for _, entity_id, _ in mention_index}
    assert "E-rule-member-free-minutes" not in ids  # kind "rule" is not a mention kind


def test_statement_matches_blocks_a_team_mention_conflict():
    truth = load_truth(MINI_ROOT / "truth")
    mention_index = build_mention_index(truth)
    truth_statement = "Skyglass severity reports are reviewed by the ops team."
    candidate = "Skyglass severity reports are reviewed by the fares team."
    assert not _statement_matches(candidate, truth_statement, mention_index)
    # Without a mention index, the guard is a no-op (the earlier behaviour):
    # this pair still fails on text similarity alone here, so assert the
    # guard specifically via the lower-level check instead.
    assert _entity_mention_conflict(candidate, truth_statement, mention_index)
    assert not _entity_mention_conflict(candidate, truth_statement, None)


def test_statement_matches_allows_the_same_team_mentioned_twice():
    truth = load_truth(MINI_ROOT / "truth")
    mention_index = build_mention_index(truth)
    truth_statement = "The fares team reviews Skyglass severity reports."
    candidate = "Skyglass severity reports are reviewed by the fares team."
    assert not _entity_mention_conflict(candidate, truth_statement, mention_index)


def test_entity_mention_conflict_ignores_kinds_outside_the_guard_list():
    """A rule-vs-rule difference (kind "rule", not in _MENTION_KINDS) must
    not trip the guard — only team/service/integration/queue/job/flag do."""
    truth = load_truth(MINI_ROOT / "truth")
    mention_index = build_mention_index(truth)
    truth_statement = "member-free-minutes governs how long a ride stays free."
    candidate = "member-free-minutes and casual-unlock-fee both govern pricing."
    assert not _entity_mention_conflict(candidate, truth_statement, mention_index)


def test_facts_match_blocks_a_team_owner_swap_end_to_end():
    truth_fact = TruthFact(
        id="F-owner",
        statement="Skyglass severity reports are reviewed by the ops team.",
        category="operations",
        entities=("E-farebox",),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
    )
    mention_index = build_mention_index(load_truth(MINI_ROOT / "truth"))
    returned = {
        "statement": "Skyglass severity reports are reviewed by the fares team.",
        "entities": ["E-farebox"],
        "citations": [{"document": "wiki/x"}],
    }
    assert not facts_match(returned, truth_fact, mention_index)


def test_mentioned_entities_prefers_the_longest_alias_at_a_position():
    """A short alias ("ops") must not steal a span already claimed by a
    longer one naming a DIFFERENT entity ("ops team") — built from a
    synthetic index (not the mini fixture, which has no such overlap) to
    isolate the longest-match-first rule itself."""
    mention_index = [
        (re.compile(r"\bops team\b", re.IGNORECASE), "E-team-ops", "team"),
        (re.compile(r"\bops\b", re.IGNORECASE), "E-flag-ops", "flag"),
    ]
    mentions = _mentioned_entities("The ops team is paged.", mention_index)
    assert mentions == {"team": {"E-team-ops"}}  # not also {"flag": {"E-flag-ops"}}


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------


def test_calibrate_basic_precision_recall():
    pairs = [
        {"truth": "A costs $5.", "candidate": "A costs $5.", "expect": True},
        {"truth": "A costs $5.", "candidate": "A costs $9.", "expect": False},
        {"truth": "A costs $5.", "candidate": "Totally unrelated text.", "expect": True},
    ]
    report = calibrate(pairs)
    assert report["tp"] == 1
    assert report["tn"] == 1
    assert report["fn"] == 1
    assert report["fp"] == 0
    assert report["precision"] == 1.0
    assert report["recall"] == 0.5
    assert len(report["misclassified"]) == 1


def test_calibration_set_meets_precision_and_recall_bar():
    """konyklabs/asbuilt#7 deliverable 5: the matcher's own calibration set,
    measured via `calibrate()`, must clear precision >= 0.9 and
    recall >= 0.85 (tune the rules, not the set, until it holds). Builds the
    mention index from the real truth/, same as `score.py --calibrate`."""
    pairs = load_calibration(SPIKE_ROOT / DEFAULT_CALIBRATION)
    assert len(pairs) >= 90  # "about 100" per the task
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    alias_index = build_alias_index(truth)
    report = calibrate(pairs, mention_index, alias_index, truth.entities)
    assert report["precision"] >= 0.9, report["misclassified"]
    assert report["recall"] >= 0.85, report["misclassified"]


# --------------------------------------------------------------------------
# Incremental phase: duplicates count, supersession label (konyklabs/
# asbuilt#7 review)
# --------------------------------------------------------------------------


def test_duplicate_count_same_statement_and_document():
    facts = [
        {"statement": "A ride costs $30.", "citations": [{"document": "wiki/x"}]},
        {"statement": "a ride costs $30", "citations": [{"document": "wiki/x"}]},  # norm()-equal
        {"statement": "A ride costs $30.", "citations": [{"document": "wiki/y"}]},  # diff. document
    ]
    assert _duplicate_count(facts) == 1


def test_duplicate_count_counts_per_cited_document():
    facts = [
        {
            "statement": "X",
            "citations": [{"document": "wiki/a"}, {"document": "wiki/b"}],
        },
        {"statement": "X", "citations": [{"document": "wiki/a"}]},
        {"statement": "X", "citations": [{"document": "wiki/b"}]},
    ]
    # (X, wiki/a): 2 copies -> 1 duplicate; (X, wiki/b): 2 copies -> 1 duplicate.
    assert _duplicate_count(facts) == 2


def test_score_incremental_phase_reports_duplicates_and_phase():
    fact = {
        "statement": "A member's free minutes are 15.",
        "category": "business-logic",
        "entities": ["Farebox", "member free minutes"],
        "tier": "executed",
        "citations": [{"document": "code/farebox/pricing.py", "version": "c4"}],
    }
    results = {
        "prototype": "test",
        "fixture": str(MINI_ROOT),
        "weights": {},
        "ingest": {},
        "phase": "incremental",
        "queries": [
            {
                "id": "q-explain-1",
                "surface": "explain",
                "latency_ms": 1.0,
                "params": {"entity": "member-free-minutes"},
                # The same (statement, document) pair returned twice — a
                # genuine duplicate under an incremental re-ingest.
                "result": [fact, dict(fact)],
            }
        ],
    }
    report = score(results, MINI_ROOT / "truth")
    assert report["phase"] == "incremental"
    assert report["duplicates"] == 1


def test_score_non_incremental_phase_duplicates_is_none():
    report = score(_hand_built_results(), MINI_ROOT / "truth")
    assert report["phase"] is None
    assert report["duplicates"] is None


def test_print_report_labels_validity_as_supersession_when_incremental(capsys):
    results = _hand_built_results()
    results["phase"] = "incremental"
    report = score(results, MINI_ROOT / "truth")
    print_report(report)
    out = capsys.readouterr().out
    assert "supersession accuracy=" in out
    assert "validity accuracy=" not in out
    assert "duplicates=" in out


# --------------------------------------------------------------------------
# The test connector's bag of facts (konyklabs/asbuilt#8)
# --------------------------------------------------------------------------

_MINI_COMMITS = {
    "c1": {"sha": "sha-c1", "date": "2026-01-01T09:00:00-05:00"},
    "c2": {"sha": "sha-c2", "date": "2026-02-01T09:00:00-05:00"},
    "c3": {"sha": "sha-c3", "date": "2026-03-01T09:00:00-05:00"},
    "c4": {"sha": "sha-c4", "date": "2026-04-01T09:00:00-05:00"},
}


def test_step_order_by_date():
    assert _step_order(_MINI_COMMITS) == {"c1": 0, "c2": 1, "c3": 2, "c4": 3}


def test_resolve_step_or_sha_accepts_either_or_neither():
    assert _resolve_step_or_sha("c2", _MINI_COMMITS) == "c2"
    assert _resolve_step_or_sha("sha-c2", _MINI_COMMITS) == "c2"
    assert _resolve_step_or_sha("unknown", _MINI_COMMITS) == "unknown"


def test_current_at_step_is_half_open_at_valid_to():
    """[valid_from, valid_to), the fixture's own window (konyklabs/
    asbuilt#66; it was closed from the #8 review until then): AT the
    boundary step only the introduced fact is in scope, never the one it
    superseded, so a retired fact and its successor never overlap."""
    order = _step_order(_MINI_COMMITS)
    retired_at_c2 = TruthFact(
        id="F-x",
        statement="x",
        category="business-logic",
        entities=(),
        tier="executed",
        carriers=(),
        valid_to="c2",
    )
    introduced_at_c2 = TruthFact(
        id="F-y",
        statement="y",
        category="business-logic",
        entities=(),
        tier="executed",
        carriers=(),
        valid_from="c2",
    )
    assert _current_at_step(retired_at_c2, order, order["c1"])
    assert not _current_at_step(retired_at_c2, order, order["c2"])  # not at its own valid_to
    assert not _current_at_step(retired_at_c2, order, order["c3"])
    assert not _current_at_step(introduced_at_c2, order, order["c1"])
    assert _current_at_step(introduced_at_c2, order, order["c2"])


def test_score_test_connector_on_mini_fixture_perfect_wrong_tier_wrong_number():
    """At step c4, F-003 ("free minutes are 15", executed) and F-012 ("...
    three fault reports...", code) are the two current truth facts carrying
    a test document. One perfect match, one wrong-tier match (still a
    match — tier isn't a facts_match criterion — but off the confusion
    diagonal, and a hard error since it claims executed with no run/
    citation), one wrong-number non-match (a hard false positive: same
    entity and cited document, different value)."""
    perfect = {
        "statement": "A member's free minutes are 15.",
        "category": "business-logic",
        "entities": ["farebox", "member free minutes"],
        "tier": "executed",
        "citations": [
            {"document": "code/tests/test_pricing.py", "version": "c4"},
            {"document": "run/pytest-c4"},
        ],
    }
    wrong_tier = {
        "statement": (
            "A dispatch test confirms the refunds watcher locks a bike with three fault reports."
        ),
        "category": "technical-implementation",
        "entities": ["farebox"],
        "tier": "executed",  # truth says "code"; also no run/ citation
        "citations": [{"document": "code/dispatch/test/refundsWatcher.test.ts", "version": "c1"}],
    }
    wrong_number = {
        "statement": "A member's free minutes are 99.",
        "category": "business-logic",
        "entities": ["farebox", "member free minutes"],
        "tier": "executed",
        "citations": [{"document": "code/tests/test_pricing.py", "version": "c4"}],
    }
    payload = {"facts": [perfect, wrong_tier, wrong_number], "contradiction_candidates": []}
    report = score_test_connector(payload, MINI_ROOT / "truth", "c4", _MINI_COMMITS)

    assert report["step"] == "c4"
    # F-003 and F-012: F-002's validity window is [c2, c4), half-open
    # (konyklabs/asbuilt#66), so F-003 (valid_from=c4) replaces it at c4
    # and the two never overlap (see _current_at_step's docstring).
    assert report["expected"] == 2
    assert report["tp"] == 2  # perfect + wrong_tier both match; tier isn't a match criterion
    assert report["hard_false_positives"] == 1
    assert report["tier_confusion"]["confusion"] == {
        "executed": {"executed": 1},
        "code": {"executed": 1},
    }
    # Both wrong_tier and wrong_number claim "executed" with no run/
    # citation — every such claim is a hard error, matched or not.
    assert report["tier_confusion"]["hard_errors"] == 2
    assert report["by_tier"]["executed"]["tp"] == 1
    assert report["by_tier"]["code"]["tp"] == 0
    assert report["missed"] == []
    assert report["contradiction_candidates"]["expected"] == 0  # mini has no run-vs-code kind


def test_score_test_connector_bare_list_skips_contradiction_candidates():
    report = score_test_connector([], MINI_ROOT / "truth", "c4", _MINI_COMMITS)
    assert report["returned"] == 0
    assert report["contradiction_candidates"]["expected"] == 0


def test_print_test_connector_report_smoke(capsys):
    report = score_test_connector([], MINI_ROOT / "truth", "c4", _MINI_COMMITS)
    print_test_connector_report(report)
    out = capsys.readouterr().out
    assert "step: c4" in out
    assert "missed truth facts: 2" in out  # F-003, F-012 (see the perfect/wrong-tier test)


def test_claim_metrics_uses_claims_match_not_exact_attribute_equality():
    """konyklabs/asbuilt#8 review: the earlier version required exact
    attribute-string equality, scoring a constant-derived "lost_bike_fee"
    against truth's "fee" as wrong even though _claims_match's word-overlap
    rule already accepts that pair — _claim_metrics must reuse
    _claims_match, not a separate, stricter check."""
    truth_fact = TruthFact(
        id="F-1",
        statement="x",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(),
        claim={"entity": "E-farebox", "attribute": "fee", "value": 150.0, "unit": "usd"},
    )
    accepted_by_overlap = {
        "claim": {
            "attribute": "lost_bike_fee",
            "value": "150.0",
            "unit": "usd",
            "_resolved_entities": ["E-farebox"],
        }
    }
    result = _claim_metrics(
        [accepted_by_overlap], [(accepted_by_overlap, "F-1")], {"F-1": truth_fact}
    )
    assert result == {"agree": 1, "returned": 1, "expected": 1, "precision": 1.0, "recall": 1.0}


def test_claim_metrics_precision_penalises_an_unmatched_resolvable_claim():
    """A resolvable claim on a fact that never matched anything at all
    still counts against precision (konyklabs/asbuilt#8 review) — not just
    towards a denominator it happens never to reach, the way the earlier
    tautological "claim accuracy" only looked at already-matched facts."""
    truth_fact = TruthFact(
        id="F-1",
        statement="x",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(),
        claim={"entity": "E-farebox", "attribute": "fee", "value": 150.0, "unit": "usd"},
    )
    matching = {
        "claim": {
            "attribute": "fee",
            "value": "150.0",
            "unit": "usd",
            "_resolved_entities": ["E-farebox"],
        }
    }
    unmatched_with_resolvable_claim = {
        "claim": {
            "attribute": "cap",
            "value": "30.0",
            "unit": "usd",
            "_resolved_entities": ["E-farebox"],
        }
    }
    result = _claim_metrics(
        [matching, unmatched_with_resolvable_claim], [(matching, "F-1")], {"F-1": truth_fact}
    )
    assert result == {"agree": 1, "returned": 2, "expected": 1, "precision": 0.5, "recall": 1.0}


def test_claim_metrics_wrong_value_is_zero_not_tautological():
    truth_fact = TruthFact(
        id="F-1",
        statement="x",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(),
        claim={"entity": "E-farebox", "attribute": "fee", "value": 150.0, "unit": "usd"},
    )
    wrong_value = {
        "claim": {
            "attribute": "fee",
            "value": "100.0",
            "unit": "usd",
            "_resolved_entities": ["E-farebox"],
        }
    }
    result = _claim_metrics([wrong_value], [(wrong_value, "F-1")], {"F-1": truth_fact})
    assert result == {"agree": 0, "returned": 1, "expected": 1, "precision": 0.0, "recall": 0.0}


def test_claim_metrics_ignores_unresolved_claims_for_precisions_denominator():
    truth_fact = TruthFact(
        id="F-1",
        statement="x",
        category="business-logic",
        entities=("E-farebox",),
        tier="executed",
        carriers=(),
        claim={"entity": "E-farebox", "attribute": "fee", "value": 150.0, "unit": "usd"},
    )
    unresolved = {
        "claim": {"attribute": "fee", "value": "150.0", "unit": "usd", "_resolved_entities": []}
    }
    result = _claim_metrics([unresolved], [], {"F-1": truth_fact})
    assert result == {"agree": 0, "returned": 0, "expected": 1, "precision": None, "recall": 0.0}


def test_claim_metrics_zero_when_truth_has_no_claim():
    truth_fact = TruthFact(
        id="F-1",
        statement="x",
        category="business-logic",
        entities=("E-x",),
        tier="executed",
        carriers=(),
    )
    returned = {
        "claim": {"attribute": "a", "value": 1, "unit": None, "_resolved_entities": ["E-x"]}
    }
    result = _claim_metrics([returned], [(returned, "F-1")], {"F-1": truth_fact})
    assert result == {"agree": 0, "returned": 1, "expected": 0, "precision": 0.0, "recall": None}


# --------------------------------------------------------------------------
# Claim-first matching (konyklabs/asbuilt#8 review)
# --------------------------------------------------------------------------


def test_claim_values_match_numeric_and_text():
    assert _claim_values_match(30, 30.0)
    assert _claim_values_match("30", 30)
    assert not _claim_values_match(30, 45)
    assert _claim_values_match("03:00", "03:00")
    assert _claim_values_match("Station_Full", "station_full")
    assert not _claim_values_match("station_full", "too_many_faults")


def test_claim_values_match_dollar_formatted_string():
    """konyklabs/asbuilt#8 trace: a real connector payload emitted a claim
    value of "$150.00" for a usd claim, against truth's plain 150.0 — the
    schema fixes value as a plain number, but the scorer's own "money as a
    number" unit-normalisation promise should still accept the common
    deviation, not just the conformant form."""
    assert _claim_values_match("$150.00", 150.0)
    assert _claim_values_match("$1,250", 1250)
    assert not _claim_values_match("$150.00", 100.0)


def test_attributes_match_the_tasks_own_worked_examples():
    assert _attributes_match("member_free_minutes", "free_minutes")
    assert _attributes_match("cap", "single_ride_cap")
    assert not _attributes_match("fee", "retries")


def test_claims_match_requires_resolved_entity_value_unit_and_attribute():
    truth_claim = {"entity": "E-x", "attribute": "free_minutes", "value": 30, "unit": "minute"}
    matching = {
        "entity": "y",
        "attribute": "member_free_minutes",
        "value": "30",
        "unit": "minute",
        "_resolved_entities": ["E-x"],
    }
    assert _claims_match(matching, truth_claim)

    wrong_entity = {**matching, "_resolved_entities": ["E-other"]}
    assert not _claims_match(wrong_entity, truth_claim)

    wrong_value = {**matching, "value": "45"}
    assert not _claims_match(wrong_value, truth_claim)

    wrong_unit = {**matching, "unit": "hour"}
    assert not _claims_match(wrong_unit, truth_claim)

    # An unset unit on either side never blocks a match.
    unset_unit = {**matching, "unit": None}
    assert _claims_match(unset_unit, truth_claim)

    wrong_attribute = {**matching, "attribute": "retries"}
    assert not _claims_match(wrong_attribute, truth_claim)


def test_claim_value_as_number_token_renders_by_unit():
    assert _claim_value_as_number_token(30.0, "usd") == "$30"
    assert _claim_value_as_number_token(20, "percent") == "20%"
    assert _claim_value_as_number_token(14, "day") == "14"
    assert _claim_value_as_number_token("03:00", "clock") == "03:00"
    assert _claim_value_as_number_token(None, "day") is None


def test_boundary_numbers_ok_requires_subset_and_membership():
    truth_claim = {"value": 30, "unit": "minute"}
    # returned names extra numbers of ANOTHER kind (the amounts), contains
    # everything truth's own statement names, and the claim's own value is
    # among them.
    assert _boundary_numbers_ok({"30", "$0", "$0.15"}, {"30"}, None, truth_claim)
    # an extra of the claim's own kind is a competing value, not a boundary:
    # "31 minutes" beside 30 is refused (konyklabs/asbuilt#17 — the first
    # draft allowed the immediate neighbour, which re-admitted the hedge for
    # every contradiction whose values differ by one).
    assert not _boundary_numbers_ok({"30", "31", "$0.15"}, {"30"}, None, truth_claim)
    # returned is missing one of truth's own numbers -> not a superset.
    assert not _boundary_numbers_ok({"31", "$0.15"}, {"30", "99"}, None, truth_claim)
    # the claim's value never appears in the other side's numbers at all.
    assert not _boundary_numbers_ok({"31", "$0.15"}, {"31"}, None, truth_claim)
    # neither/both sides carry a claim -> never relaxed.
    assert not _boundary_numbers_ok({"30"}, {"30", "31"}, None, None)


def test_facts_match_claim_first_overrides_dissimilar_statement_text():
    """Both sides carry a claim: the match is decided by the claim — a
    statement well under the similarity threshold is credited once the
    claim agrees, and a matching statement doesn't save a disagreeing
    claim. Since konyklabs/asbuilt#35 the statement must still name the
    claim's quantity and value: a text sharing nothing with the fact is not
    rescued by its claim."""
    truth_fact = TruthFact(
        id="F-1",
        statement="A member's first 30 minutes of every ride are free.",
        category="business-logic",
        entities=("E-x",),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
        claim={"entity": "E-x", "attribute": "free_minutes", "value": 30, "unit": "minute"},
    )
    claim = {
        "attribute": "free_minutes",
        "value": 30,
        "unit": "minute",
        "_resolved_entities": ["E-x"],
    }
    returned_matching_claim = {
        "statement": "Billing skips 30 free minutes per membership ride today here.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
        "claim": claim,
    }
    assert _text_similarity(returned_matching_claim["statement"], truth_fact.statement) < 0.6
    assert facts_match(returned_matching_claim, truth_fact)
    returned_unrelated_text = {
        **returned_matching_claim,
        "statement": "Totally different phrasing sharing hardly any vocabulary.",
    }
    assert not facts_match(returned_unrelated_text, truth_fact)
    assert not facts_match(returned_unrelated_text, truth_fact, strict=False)

    returned_disagreeing_claim = {
        "statement": "A member's first 30 minutes of every ride are free.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
        "claim": {
            "attribute": "free_minutes",
            "value": 45,
            "unit": "minute",
            "_resolved_entities": ["E-x"],
        },
    }
    assert not facts_match(returned_disagreeing_claim, truth_fact)


def test_facts_match_claim_first_falls_back_when_returned_entity_unresolved():
    """konyklabs/asbuilt#8 review, reproduced at c6 (tp 14/24 -> 17/24 with
    returned claims stripped entirely): an unresolved returned claim entity
    must not reject a fact whose plain entities, document and statement all
    otherwise agree — it should fall back to the statement path instead of
    letting `_claims_match` alone decide with no way back."""
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    truth_fact = TruthFact(
        id="F-1",
        statement="A member's free minutes are 15.",
        category="business-logic",
        entities=("E-farebox", "E-rule-member-free-minutes"),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
        claim={
            "entity": "E-rule-member-free-minutes",
            "attribute": "free_minutes",
            "value": 15,
            "unit": "minute",
        },
    )
    fact_with_unresolvable_claim_entity = {
        "statement": "A member's free minutes are 15.",
        "entities": ["Farebox", "member-free-minutes"],
        "category": "business-logic",
        "citations": [{"document": "wiki/x"}],
        "claim": {
            "entity": "totally unrelated gibberish",
            "attribute": "free_minutes",
            "value": 15,
            "unit": "minute",
        },
    }
    resolved = resolve_fact_entities(fact_with_unresolvable_claim_entity, index, truth.entities)
    assert resolved["claim"]["_resolved_entities"] == []  # confirms the reproduction premise
    assert facts_match(resolved, truth_fact)  # falls back to the (matching) statement/entities


def test_facts_match_claim_first_still_rejects_when_both_resolve_and_disagree():
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    truth_fact = TruthFact(
        id="F-1",
        statement="A member's free minutes are 15.",
        category="business-logic",
        entities=("E-farebox", "E-rule-member-free-minutes"),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
        claim={
            "entity": "E-rule-member-free-minutes",
            "attribute": "free_minutes",
            "value": 15,
            "unit": "minute",
        },
    )
    fact_with_wrong_value = {
        "statement": "A member's free minutes are 15.",
        "entities": ["Farebox", "member-free-minutes"],
        "category": "business-logic",
        "citations": [{"document": "wiki/x"}],
        "claim": {
            "entity": "member-free-minutes",
            "attribute": "free_minutes",
            "value": 30,
            "unit": "minute",
        },
    }
    resolved = resolve_fact_entities(fact_with_wrong_value, index, truth.entities)
    assert resolved["claim"]["_resolved_entities"] == ["E-rule-member-free-minutes"]
    # Both resolve; the claim disagrees (30 vs 15) -> rejected even though
    # the plain statement text is identical on both sides.
    assert not facts_match(resolved, truth_fact)


def test_resolve_fact_entities_resolves_the_claims_own_entity():
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    fact = {
        "entities": ["Farebox"],
        "category": "business-logic",
        "statement": "x",
        "claim": {"entity": "Farebox", "attribute": "a", "value": 1, "unit": None},
    }
    resolved = resolve_fact_entities(fact, index, truth.entities)
    assert resolved["claim"]["_resolved_entities"] == ["E-farebox"]


@pytest.mark.fixture
def test_real_fixture_f011_f012_per_step_tier_reproduction():
    """konyklabs/asbuilt#8 review, reproduced directly against the real
    F-011/F-012/commits.json: F-012 must not be in scope at c5 (its only
    test carrier is version c6); F-011 must be "executed" at c1..c4 (a
    run/pytest-<step> carrier at each of those steps). The review also had
    F-011 in scope at c5, its own `valid_to`; since konyklabs/asbuilt#66 it
    is not (the window is half-open), and its tier there is still "code"."""
    commits_path = SPIKE_ROOT / "build" / "commits.json"
    if not commits_path.is_file():
        pytest.skip()
    commits = json.loads(commits_path.read_text())
    truth = load_truth(SPIKE_ROOT / "truth")
    if "F-011" not in truth.facts or "F-012" not in truth.facts:
        pytest.skip()
    order = _step_order(commits)
    prefixes = _TRUTH_FILTER_PREFIXES["tests"]
    f011, f012 = truth.facts["F-011"], truth.facts["F-012"]

    assert not _has_test_carrier_by_step(f012, prefixes, order, order["c5"])
    assert _has_test_carrier_by_step(f012, prefixes, order, order["c6"])

    for step in ("c1", "c2", "c3", "c4"):
        assert _has_test_carrier_by_step(f011, prefixes, order, order[step])
        assert _current_at_step(f011, order, order[step])
        assert _expected_tier_at_step(f011, step) == "executed"
    assert _has_test_carrier_by_step(f011, prefixes, order, order["c5"])
    assert not _current_at_step(f011, order, order["c5"])
    assert _expected_tier_at_step(f011, "c5") == "code"


@pytest.mark.fixture
def test_real_fixture_score_test_connector_smoke():
    facts_path = SPIKE_ROOT / "build" / "connector" / "tests-c6.json"
    if not facts_path.is_file():
        pytest.skip()
    commits_path = SPIKE_ROOT / "build" / "commits.json"
    commits = json.loads(commits_path.read_text()) if commits_path.is_file() else {}
    payload = json.loads(facts_path.read_text())
    report = score_test_connector(payload, SPIKE_ROOT / "truth", "c6", commits)
    assert report["expected"] > 0
    assert report["precision"] is None or 0.0 <= report["precision"] <= 1.0


# --------------------------------------------------------------------------
# konyklabs/asbuilt#17: fuller statements in the candidate's own vocabulary,
# calibrated on the first model run's judged pairs
# --------------------------------------------------------------------------


@pytest.mark.fixture
def test_judged_model_run_pairs_have_no_false_positive_and_a_recall_floor():
    """The judged pairs from the first real model run (2026-09-29): every
    model and rules statement at c6 against its truth fact, plus a cross
    pair per model statement, plus targeted pairs in both directions for
    each rule the matcher loosened or added (the cross pairs all sit far
    below the similarity threshold, so they alone prove nothing about
    those rules — a local lens round's finding). Precision must be perfect
    (no candidate is credited with a fact it does not state) and recall is
    pinned at the measured floor, not at 1.0: the remaining misses are
    narratives of the test scenario, a negated side clause, a missing or
    competing number of the fact's own kind and close paraphrases under
    the similarity threshold, all listed on #17. Raising this floor by
    changing the matcher needs a judged pair in each direction, never the
    model's output alone. asbuilt#35 relabelled five pairs under the strict
    reading (two dropping the flag condition, two leaving the value to the
    claim, one over-claim: each pair's `why`) and added the F-077 paraphrase
    the over-claim rule misses in both readings, which moved the floor from
    35/55 to 30/51. asbuilt#63 gave F-051 its flag condition and relabelled
    the three pairs whose candidate drops it (each pair's `why`), which moved
    it to 27/48; the lenient reading is unchanged at 34/55."""
    pairs = load_calibration(SPIKE_ROOT / "tests/fixtures/calibration-model-run.yaml")
    assert len(pairs) == 91
    truth = load_truth(SPIKE_ROOT / "truth")
    report = calibrate(pairs, build_mention_index(truth), build_alias_index(truth), truth.entities)
    assert report["fp"] == 0, report["misclassified"]
    assert report["precision"] == 1.0
    assert report["recall"] >= 0.56, report["misclassified"]
    assert report["recall"] < 0.9  # an honest floor: see the docstring
    # every targeted rule pair (both directions) must hold exactly
    rule_pairs = [p for p in pairs if str(p.get("source", "")).startswith("rule-")]
    assert len(rule_pairs) == 18
    missed_rule_pairs = [
        m for m in report["misclassified"] if str(m.get("source", "")).startswith("rule-")
    ]
    assert missed_rule_pairs == []
    # the lenient reading keeps the asbuilt#17 labels except the over-claim,
    # wrong in both readings, and misses F-077: 35/55 then, 34/55 now
    lenient = calibrate(
        pairs, build_mention_index(truth), build_alias_index(truth), truth.entities, strict=False
    )
    assert lenient["fp"] == 0, lenient["misclassified"]
    assert lenient["recall"] >= 0.61, lenient["misclassified"]


def _wiki_truth(statement: str, claim: dict | None = None, entities=("E-x",)) -> TruthFact:
    return TruthFact(
        id="F-1",
        statement=statement,
        category="business-logic",
        entities=tuple(entities),
        tier="documented",
        carriers=(Carrier(document="wiki/x"),),
        claim=claim,
    )


def _wiki_fact(statement: str, claim: dict | None = None, entities=("E-x",)) -> dict:
    fact = {
        "statement": statement,
        "entities": list(entities),
        "citations": [{"document": "wiki/x"}],
    }
    if claim is not None:
        fact["claim"] = claim
    return fact


def test_off_is_a_flag_state_not_a_negation():
    """ "the flag is off" used to read as a negated sentence, so a candidate
    saying the same thing without the word was vetoed as a polarity flip
    (three facts of the first model run). The state is compared on its own:
    a candidate naming no state is not vetoed as a flip, one naming the
    opposite state is (the polarity-flip test above still holds through
    this). Since konyklabs/asbuilt#35 the strict reading no longer credits
    the stateless candidate: it drops the fact's condition; the lenient
    reading still does."""
    truth = _wiki_truth(
        "A check-in at a full station is refused when the overflow_parking flag is off."
    )
    assert facts_match(_wiki_fact("Check-in at a full station is refused."), truth, strict=False)
    assert not facts_match(_wiki_fact("Check-in at a full station is refused."), truth)
    assert facts_match(
        _wiki_fact("With the overflow parking flag off, a check-in at a full station is refused."),
        truth,
    )
    assert not facts_match(
        _wiki_fact("With the overflow parking flag on, a check-in at a full station is refused."),
        truth,
    )
    assert not _has_negation("The dynamic_pricing flag is off by default.")
    assert _flag_states("the feature flag is enabled.") == {"on"}
    assert _flag_states("switched off") == {"off"}
    assert _flag_states("Dynamic pricing is on in production.") == {"on"}
    # a state word leading into a noun names no state (a lens-round finding)
    assert _flag_states("depends on the station") == set()
    assert _flag_states("The fee is on the invoice.") == set()
    assert _flag_states("the station was disabled for maintenance") == set()


def test_numbers_a_fuller_statement_may_name_more_than_the_truth_never_fewer():
    """The number rule is containment, not equality: a candidate naming the
    HTTP code beside the fact's own number is the same fact; one missing
    the fact's number, or naming a different one, is not (30 against 45 is
    still the calibration set's hard negative)."""
    truth = _wiki_truth(
        "A rider can hold at most 2 bikes at once, so a third check-out is refused."
    )
    assert facts_match(
        _wiki_fact(
            "A rider can hold at most 2 bikes at once; a third check-out is refused with HTTP 409."
        ),
        truth,
    )
    assert not facts_match(
        _wiki_fact("A rider can hold at most 3 bikes at once, so a fourth check-out is refused."),
        truth,
    )
    free = _wiki_truth("A member's first 30 minutes of every ride are free.")
    assert not facts_match(_wiki_fact("A member's first 45 minutes of every ride are free."), free)
    assert not facts_match(_wiki_fact("A member's first minutes of every ride are free."), free)
    # a second value of the fact's own kind is a competing value, never an
    # extra (the hedge must match neither side of a supersession); a number of
    # another kind beside the fact's is fine; a digit ordinal is no quantity
    assert not facts_match(
        _wiki_fact("A member's first 45 minutes of every ride are free; the code applies 30."),
        free,
    )
    assert facts_match(_wiki_fact("A member's first 30 minutes of every ride are free ($0)."), free)
    assert facts_match(_wiki_fact("A member's 1st 30 minutes of every ride are free."), free)
    # a fact naming no quantity admits none
    hourly = _wiki_truth("The maintenance sweep job runs every hour.")
    assert not facts_match(_wiki_fact("The maintenance sweep job runs every 2 hours."), hourly)


def test_http_status_codes_are_set_aside_unless_the_fact_is_about_the_response():
    """A code named as one ("returns HTTP 422", "with a 200 response") is
    not a quantity of the fact, so a fuller statement naming it beside the
    fact's number is the same fact. When the truth itself names a code the
    fact is about the response: the code stays and must agree."""
    refund = _wiki_truth("A refund requested more than 14 days after the ride ended is rejected.")
    assert facts_match(
        _wiki_fact(
            "A refund requested more than 14 days after the ride ended is rejected with HTTP 422."
        ),
        refund,
    )
    checkin = _wiki_truth(
        "POST /rides/{id}/checkin at a full station returns HTTP 409 with error code station_full."
    )
    assert facts_match(
        _wiki_fact("Checking in at a full station returns HTTP 409 with error code station_full."),
        checkin,
    )
    assert not facts_match(
        _wiki_fact("Checking in at a full station returns HTTP 404 with error code station_full."),
        checkin,
    )
    assert (
        _number_tokens(_without_http_codes("retries after a 5xx response, never after a 4xx"))
        == set()
    )


def test_claim_naming_the_entity_its_own_way_lets_the_statement_decide():
    """A comparable claim decides the match when it agrees in full; a value
    conflict, another attribute (a different quantity; `snapshot_interval`
    against a retention fact was the second lens round's case, and no word
    rule separates it from a camelCase paraphrase) or another unit vetoes;
    only a claim naming the ENTITY its own way, with value, attribute and
    unit agreeing, hands the decision to the statement."""
    truth = load_truth(MINI_ROOT / "truth")
    index = build_alias_index(truth)
    truth_fact = TruthFact(
        id="F-1",
        statement="A member's free minutes are 15.",
        category="business-logic",
        entities=("E-farebox", "E-rule-member-free-minutes"),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
        claim={
            "entity": "E-rule-member-free-minutes",
            "attribute": "free_minutes",
            "value": 15,
            "unit": "minute",
        },
    )

    def fact(entity: str, attribute: str, value, unit="minute"):
        return resolve_fact_entities(
            {
                "statement": "A member's free minutes are 15.",
                "entities": ["Farebox", "member-free-minutes"],
                "category": "business-logic",
                "citations": [{"document": "wiki/x"}],
                "claim": {"entity": entity, "attribute": attribute, "value": value, "unit": unit},
            },
            index,
            truth.entities,
        )

    assert facts_match(
        fact("member-free-minutes", "memberFreeMinutes", 15), truth_fact
    )  # camelCase
    assert facts_match(
        fact("member-free-minutes", "free_minutes", 15, "minutes"), truth_fact
    )  # plural
    assert not facts_match(fact("member-free-minutes", "retries", 15), truth_fact)  # other quantity
    assert not facts_match(fact("member-free-minutes", "minutesBeforeBilling", 15), truth_fact)
    assert not facts_match(fact("member-free-minutes", "free_minutes", 30), truth_fact)  # value
    assert not facts_match(
        fact("member-free-minutes", "free_minutes", 15, "hour"), truth_fact
    )  # unit
    # the entity named the candidate's way: resolves to the service, not the
    # rule; value, attribute and unit agree, so the statement decides
    other = fact("Farebox", "free_minutes", 15)
    assert other["claim"]["_resolved_entities"] == ["E-farebox"]
    assert facts_match(other, truth_fact)


def test_claim_units_fold_cents_to_dollars_and_plurals_to_singular():
    assert _claim_values_match(15000, 150.0, "usd_cents", "usd")
    assert _claim_values_match(15000, 150.0, "cents", "usd")
    assert not _claim_values_match(150, 150.0, "cents", "usd")
    assert _normalise_unit("days") == ("day", 1.0)
    assert _normalise_unit("USD") == ("usd", 1.0)
    assert _normalise_unit(None) == (None, 1.0)
    assert _claims_match(
        {
            "entity": "e",
            "attribute": "fee",
            "value": 15000,
            "unit": "usd_cents",
            "_resolved_entities": ["E-r"],
        },
        {"entity": "E-r", "attribute": "fee", "value": 150.0, "unit": "usd"},
    )
    assert _claims_match(
        {
            "entity": "e",
            "attribute": "window",
            "value": 14,
            "unit": "days",
            "_resolved_entities": ["E-r"],
        },
        {"entity": "E-r", "attribute": "window", "value": 14, "unit": "day"},
    )


def test_split_camel_lets_typescript_attributes_compare_word_by_word():
    assert _split_camel("severityThresholdToPause") == "severity Threshold To Pause"
    assert _split_camel("min_severity") == "min_severity"
    assert _attributes_match("faultReportLockThreshold", "fault_report_threshold")


# --------------------------------------------------------------------------
# The code and documented tier lines, the code and documents truth filters,
# and expected sets held to the run's step (konyklabs/asbuilt#34)
# --------------------------------------------------------------------------


def test_score_fact_query_code_and_documented_tier_lines():
    """Counted exactly as the executed line is: every returned fact claiming
    the tier, matched or not, over the static truth tier of its match."""
    truth_code = TruthFact(
        id="F-c",
        statement="A refund window is 14 days.",
        category="business-logic",
        entities=("E-x",),
        tier="code",
        carriers=(Carrier(document="code/x.py"),),
    )
    truth_documented = TruthFact(
        id="F-d",
        statement="Refunds are reviewed by the payments team.",
        category="operations",
        entities=("E-x",),
        tier="documented",
        carriers=(Carrier(document="wiki/refunds"),),
    )
    expected = {"F-c": truth_code, "F-d": truth_documented}

    def returned(statement: str, tier: str, document: str) -> dict:
        return {
            "statement": statement,
            "entities": ["E-x"],
            "tier": tier,
            "category": "business-logic",
            "citations": [{"document": document}],
        }

    result = score_fact_query(
        [
            returned("A refund window is 14 days.", "code", "code/x.py"),
            # matches the documented fact but claims code: off the code line's tp
            returned("Refunds are reviewed by the payments team.", "code", "wiki/refunds"),
            returned("Something else entirely.", "documented", "wiki/elsewhere"),
        ],
        expected,
        alias_index=_identity_index("E-x"),
    )
    tier = result["tier"]
    assert (tier["returned_code"], tier["tp_code"], tier["expected_code"]) == (2, 1, 1)
    assert (tier["returned_documented"], tier["tp_documented"], tier["expected_documented"]) == (
        1,
        0,
        1,
    )
    assert (tier["returned_executed"], tier["tp_executed"], tier["expected_executed"]) == (0, 0, 0)


def _results_with_a_documented_hit() -> dict:
    """`_hand_built_results` plus an explain hit on F-005, the mini
    fixture's documented fact, claimed `documented`."""
    results = _hand_built_results()
    results["queries"][0]["result"].append(
        {
            "statement": "A member's free minutes are 20.",
            "category": "business-logic",
            "entities": ["member free minutes"],
            "tier": "documented",
            "citations": [{"document": "wiki/pricing-rules-2025", "version": "1"}],
        }
    )
    return results


def test_score_reports_code_and_documented_tier_lines_on_explain_and_search(capsys):
    report = score(_results_with_a_documented_hit(), MINI_ROOT / "truth")

    # explain expects F-001, F-002, F-003 (executed) and F-005 (documented).
    explain = report["surfaces"]["explain"]["tier"]
    assert explain["precision_documented"] == 1.0
    assert explain["recall_documented"] == 1.0
    assert (explain["tp_documented"], explain["returned_documented"]) == (1, 1)
    assert explain["expected_documented"] == 1
    assert explain["precision_code"] is None  # nothing returned claims code
    assert explain["recall_code"] is None  # nothing expected is code
    # the executed line is untouched by the new ones
    assert (explain["tp_executed"], explain["returned_executed"]) == (1, 1)
    assert explain["expected_executed"] == 3

    # search: the wrong fact claims documented and matches nothing.
    search = report["surfaces"]["search"]["tier"]
    assert search["precision_documented"] == 0.0
    assert search["recall_documented"] is None
    assert search["returned_documented"] == 1

    print_report(report)
    out = capsys.readouterr().out
    assert "    tier code: precision=n/a (0/0) recall=n/a (0/0)" in out
    assert "    tier documented: precision=1.000 (1/1) recall=1.000 (1/1)" in out
    assert "    tier documented: precision=0.000 (0/1) recall=n/a (0/0)" in out


def test_score_json_carries_the_tier_lines_under_tier(tmp_path):
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(_results_with_a_documented_hit()))
    out = tmp_path / "score.json"
    argv = [str(results_path), "--truth", str(MINI_ROOT / "truth"), "--json", str(out)]
    argv += ["--commits", str(tmp_path / "no-commits.json")]
    assert main(argv) == 0
    tier = json.loads(out.read_text())["surfaces"]["explain"]["tier"]
    for t in ("code", "documented"):
        for key in ("returned", "tp", "expected", "precision", "recall"):
            assert f"{key}_{t}" in tier
    assert tier["recall_documented"] == 1.0


def test_aggregate_reports_carries_code_and_documented_tier_lines(capsys):
    good = score(_results_with_a_documented_hit(), MINI_ROOT / "truth")
    worse = score(_hand_built_results(), MINI_ROOT / "truth")  # no documented hit

    agg = aggregate_reports([good, worse])["surfaces"]
    recall = agg["explain"]["documented_tier_recall"]
    assert (recall["median"], recall["min"], recall["max"]) == (0.5, 0.0, 1.0)
    # worse returned nothing claiming documented on explain: undefined, left out
    precision = agg["explain"]["documented_tier_precision"]
    assert (precision["median"], precision["min"], precision["max"]) == (1.0, 1.0, 1.0)
    assert "code_tier_recall" not in agg["explain"]  # nothing code-tier is expected
    assert agg["search"]["documented_tier_precision"]["max"] == 0.0

    print_multi_report([good, worse])
    out = capsys.readouterr().out
    assert "explain        documented_tier_recall    0.500     0.000     1.000" in out


def test_score_test_connector_code_filter_keeps_code_outside_tests_by_step():
    """`code`: a `code/` carrier outside the test directories, at or before
    the step, on a fact current at it. F-012 carries only a dispatch test,
    so it is never in; F-001 (retired at c2), F-002 (c2 until c4) and F-003
    (from c4) move in and out with the step; F-013 is there throughout."""
    at_c1 = score_test_connector([], MINI_ROOT / "truth", "c1", _MINI_COMMITS, "code")
    at_c4 = score_test_connector([], MINI_ROOT / "truth", "c4", _MINI_COMMITS, "code")
    assert sorted(m["id"] for m in at_c1["missed"]) == ["F-001", "F-013"]
    assert sorted(m["id"] for m in at_c4["missed"]) == ["F-003", "F-013"]
    assert {m["id"]: m["test"] for m in at_c4["missed"]}["F-013"] == "PricingClient.fetch_rate"
    assert set(at_c4["by_tier"]) == {"executed", "code"}
    assert at_c4["truth_filter"] == "code"


def test_has_filter_carrier_by_step_holds_a_code_carrier_to_its_own_version():
    order = _step_order(_MINI_COMMITS)
    fact = TruthFact(
        id="F-x",
        statement="x",
        category="business-logic",
        entities=(),
        tier="executed",
        carriers=(
            Carrier(document="code/tests/test_x.py", version="c1"),
            Carrier(document="code/farebox/x.py", version="c3"),
        ),
    )
    assert _has_filter_carrier_by_step(fact, "tests", order, order["c2"])
    assert not _has_filter_carrier_by_step(fact, "code", order, order["c2"])
    assert _has_filter_carrier_by_step(fact, "code", order, order["c3"])
    test_only = TruthFact(
        id="F-t",
        statement="t",
        category="business-logic",
        entities=(),
        tier="code",
        carriers=(Carrier(document="code/dispatch/test/x.test.ts", version="c1"),),
    )
    assert not _has_filter_carrier_by_step(test_only, "code", order, order["c4"])
    assert _has_filter_carrier_by_step(test_only, "tests", order, order["c4"])
    assert _has_filter_carrier_by_step(test_only, "tests", order, order["c4"]) == (
        _has_test_carrier_by_step(test_only, _TRUTH_FILTER_PREFIXES["tests"], order, order["c4"])
    )


def test_score_test_connector_documents_filter_counts_unversioned_carriers():
    """`documents`: a wiki, doc, ticket or pull carrier. A wiki/doc version
    is a page revision and tickets and pulls carry none, so no carrier is
    held to a step; the seven documented mini facts are all in at c1. A
    fact with no `code/` carrier is labelled by its own tier, not `code`."""
    perfect = {
        "statement": "Refunds are processed within 5 business days.",
        "category": "operations",
        "entities": ["farebox"],
        "tier": "documented",
        "citations": [{"document": "doc/DOC-1", "version": "1"}],
    }
    report = score_test_connector([perfect], MINI_ROOT / "truth", "c1", _MINI_COMMITS, "documents")
    assert report["expected"] == 7
    assert report["tp"] == 1
    assert report["by_tier"]["documented"]["expected"] == 7
    assert report["by_tier"]["documented"]["tp"] == 1
    assert report["by_tier"]["code"]["expected"] == 0
    assert report["tier_confusion"]["confusion"] == {"documented": {"documented": 1}}
    assert "F-007" in {m["id"] for m in report["missed"]}  # a ticket carrier, no version


def _write_step_truth(root) -> None:
    """A two-step synthetic fixture: F-old holds from c1, F-new from c2, the
    contradiction pairs them, and the stale page goes stale at c2."""
    history = root / "system" / "history"
    history.mkdir(parents=True)
    (history / "steps.yaml").write_text(
        '- id: c1\n  date: "2026-01-01T09:00:00-05:00"\n'
        '- id: c2\n  date: "2026-02-01T09:00:00-05:00"\n'
    )
    truth_dir = root / "truth"
    truth_dir.mkdir()
    (truth_dir / "entities.yaml").write_text("- id: E-x\n  kind: service\n  name: x\n")
    (truth_dir / "facts.yaml").write_text(
        "- id: F-old\n"
        "  statement: The x window is 3 days.\n"
        "  category: business-logic\n"
        "  entities: [E-x]\n"
        "  tier: documented\n"
        "  carriers:\n"
        "    - document: wiki/x\n"
        "- id: F-new\n"
        "  statement: The x window is 7 days.\n"
        "  category: business-logic\n"
        "  entities: [E-x]\n"
        "  tier: documented\n"
        "  valid_from: c2\n"
        "  carriers:\n"
        "    - document: wiki/y\n"
    )
    (truth_dir / "contradictions.yaml").write_text(
        "- id: X-1\n  facts: [F-old, F-new]\n  kind: wiki-vs-test\n  winner: F-new\n"
    )
    (truth_dir / "stale.yaml").write_text(
        "- id: S-1\n  document: wiki/x\n  states: F-old\n  changed_by: c2\n"
    )


def _step_results(root, through_step: str | None) -> dict:
    def query(qid: str, surface: str, params: dict, result) -> dict:
        return {
            "id": qid,
            "surface": surface,
            "latency_ms": 1.0,
            "params": params,
            "result": result,
        }

    results = {
        "prototype": "test",
        "fixture": str(root),
        "weights": {},
        "ingest": {},
        "queries": [
            query("q-explain", "explain", {"entity": "x"}, []),
            query("q-search", "search", {"expects": ["F-old", "F-new"]}, []),
            query("q-ask", "ask", {"expects": ["F-new"]}, {"sentences": []}),
            query("q-contradictions", "contradictions", {"entity": "x"}, []),
            query("q-contradictions-all", "contradictions", {}, []),
            query("q-stale", "stale", {"since": "2025-12-01"}, []),
        ],
    }
    if through_step is not None:
        results["through_step"] = through_step
    return results


def _expected_by_surface(report: dict) -> dict[str, int]:
    return {name: s["expected"] for name, s in report["surfaces"].items()}


def test_score_holds_later_step_truth_back_from_an_earlier_run(tmp_path):
    """A fact valid from c2, a contradiction one of whose facts is valid
    from c2, and a page made stale at c2 are not expected of a run ingested
    through c1, on any surface; through c2 they are."""
    _write_step_truth(tmp_path)
    truth_dir = tmp_path / "truth"

    at_c1 = score(_step_results(tmp_path, "c1"), truth_dir)
    assert _expected_by_surface(at_c1) == {
        "explain": 1,
        "search": 1,
        "ask": 0,
        "contradictions": 0,  # both queries, the entity one and the unfiltered one
        "stale": 0,
    }
    at_c2 = score(_step_results(tmp_path, "c2"), truth_dir)
    assert _expected_by_surface(at_c2) == {
        "explain": 2,
        "search": 2,
        "ask": 1,
        "contradictions": 2,
        "stale": 1,
    }


def test_score_without_a_known_through_step_holds_nothing_back(tmp_path):
    """A results file with no `through_step` (or one naming a step the
    fixture doesn't have) is scored as before the rule: every truth entry
    expected, as of the last step."""
    _write_step_truth(tmp_path)
    truth_dir = tmp_path / "truth"
    at_c2 = _expected_by_surface(score(_step_results(tmp_path, "c2"), truth_dir))
    assert _expected_by_surface(score(_step_results(tmp_path, None), truth_dir)) == at_c2
    assert _expected_by_surface(score(_step_results(tmp_path, "c9"), truth_dir)) == at_c2


def test_run_step_rank_orders_by_step_dates_then_commits():
    step_dates = {
        "c2": datetime.fromisoformat("2026-02-01T09:00:00-05:00"),
        "c1": datetime.fromisoformat("2026-01-01T09:00:00-05:00"),
    }
    assert _run_step_rank("c2", step_dates, {}) == ({"c1": 0, "c2": 1}, 1)
    # no steps.yaml: commits.json's order
    assert _run_step_rank("c3", {}, _MINI_COMMITS) == (_step_order(_MINI_COMMITS), 2)
    assert _run_step_rank(None, step_dates, {})[1] is None


def test_score_test_connector_documents_filter_is_step_current(tmp_path):
    """Like `tests`, the documents filter keeps only the facts current at
    the step: F-new, valid from c2, is not expected at c1."""
    _write_step_truth(tmp_path)
    commits = {
        "c1": {"sha": "sha-c1", "date": "2026-01-01T09:00:00-05:00"},
        "c2": {"sha": "sha-c2", "date": "2026-02-01T09:00:00-05:00"},
    }
    truth_dir = tmp_path / "truth"
    at_c1 = score_test_connector([], truth_dir, "c1", commits, "documents")
    at_c2 = score_test_connector([], truth_dir, "c2", commits, "documents")
    assert [m["id"] for m in at_c1["missed"]] == ["F-old"]
    assert sorted(m["id"] for m in at_c2["missed"]) == ["F-new", "F-old"]


def _append_truth(root, facts: str = "", contradictions: str = "", stale: str = "") -> None:
    truth_dir = root / "truth"
    for name, text in (
        ("facts.yaml", facts),
        ("contradictions.yaml", contradictions),
        ("stale.yaml", stale),
    ):
        path = truth_dir / name
        path.write_text(path.read_text() + text)


def test_score_keeps_a_retired_fact_expected_on_explain(tmp_path):
    """`valid_to` is deliberately not checked: explain expects a fact's
    whole history, so a value retired at c1 is still expected of a run
    through c2."""
    _write_step_truth(tmp_path)
    _append_truth(
        tmp_path,
        facts=(
            "- id: F-retired\n"
            "  statement: The x window is 1 day.\n"
            "  category: business-logic\n"
            "  entities: [E-x]\n"
            "  tier: documented\n"
            "  valid_to: c1\n"
            "  carriers:\n"
            "    - document: wiki/z\n"
        ),
    )
    report = score(_step_results(tmp_path, "c2"), tmp_path / "truth")
    assert report["surfaces"]["explain"]["expected"] == 3  # F-old, F-new, F-retired


def test_score_holds_back_truth_naming_a_step_the_fixture_does_not_list(tmp_path, capsys):
    """A truth checkout ahead of the run's fixture (a c7 the fixture's
    steps.yaml doesn't have): the fact, the contradiction it is in and the
    page it makes stale are not expected of a run with a known
    through_step, and stderr names the step. Without a through_step
    nothing is held back and nothing is said."""
    _write_step_truth(tmp_path)
    _append_truth(
        tmp_path,
        facts=(
            "- id: F-ahead\n"
            "  statement: The x window is 9 days.\n"
            "  category: business-logic\n"
            "  entities: [E-x]\n"
            "  tier: documented\n"
            "  valid_from: c7\n"
            "  carriers:\n"
            "    - document: wiki/z\n"
        ),
        contradictions="- id: X-ahead\n  facts: [F-old, F-ahead]\n  kind: wiki-vs-test\n",
        stale="- id: S-ahead\n  document: wiki/x\n  states: F-old\n  changed_by: c7\n",
    )
    truth_dir = tmp_path / "truth"

    def results(through_step: str | None) -> dict:
        r = _step_results(tmp_path, through_step)
        r["queries"][1]["params"]["expects"].append("F-ahead")  # search
        r["queries"][2]["params"]["expects"].append("F-ahead")  # ask
        return r

    at_c2 = score(results("c2"), truth_dir)
    assert _expected_by_surface(at_c2) == {
        "explain": 2,
        "search": 2,
        "ask": 1,
        "contradictions": 2,
        "stale": 1,
    }
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "warning: truth names step(s) c7 that the run's fixture does not list; held back "
        "as later than through_step c2: 1 facts, 1 contradictions, 1 stale pages\n"
    )

    unfiltered = score(results(None), truth_dir)
    assert _expected_by_surface(unfiltered) == {
        "explain": 3,
        "search": 3,
        "ask": 2,
        "contradictions": 4,
        # score_stale itself never expects a page whose step has no date
        "stale": 1,
    }
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------
# The hand audit's corrections (konyklabs/asbuilt#35, spike/AUDIT.md)
# --------------------------------------------------------------------------


def test_compound_number_words_are_one_number():
    """Item 2: "forty-five" is 45, not 40 and 5, joined by a hyphen, a space
    or nothing; the test connector's "fortyfive" comes from a test name."""
    assert _number_tokens("A member's first forty-five minutes are free.") == {"45"}
    assert _number_tokens("open for twenty four hours") == {"24"}
    assert _number_tokens("Member 1st fortyfive minutes free.") == {"1", "45"}
    assert _number_tokens("ninety-nine, twenty, three") == {"99", "20", "3"}
    assert _number_tokens("the forty-five-minute example ride") == {"45"}
    # a comma or "and" between the words leaves two numbers
    assert _number_tokens("forty, five") == {"40", "5"}
    assert _number_tokens("forty and five") == {"40", "5"}
    assert _statement_matches(
        "A member's first forty-five minutes of every ride are free.",
        "A member's first 45 minutes of every ride are free.",
    )
    assert not _statement_matches(
        "A member's first forty-five minutes of every ride are free.",
        "A member's first 40 minutes of every ride are free.",
    )


def test_allowed_and_refused_are_opposite_outcomes():
    """Item 3: an outcome and its antonym never match, however alike the
    rest of the sentence; outcomes of one kind in different words do."""
    assert not _statement_matches(
        "A refund under $5 is approved.", "A refund under $5 is rejected."
    )
    assert not _statement_matches(
        "Checkin at a full station allowed.", "A check-in at a full station is refused."
    )
    assert _statement_matches(
        "A check-in at a full station is rejected.", "A check-in at a full station is refused."
    )


@pytest.mark.fixture
def test_overflow_parking_pair_is_matched_on_polarity_and_condition():
    """Items 3 and 4 on the audit's own pair (AUDIT.md, "Polarity"): the
    "allowed" sentence matches F-018 (allowed when the flag is on) and not
    F-017 (refused when it is off); the terse "refused" sentence names no
    condition, so the strict reading credits it with neither, and the
    lenient reading with both, as before."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    f017, f018 = truth.facts["F-017"].statement, truth.facts["F-018"].statement
    allowed = "Checkin at full station allowed with overflow parking."
    refused = "Checkin at full station refused."
    assert _statement_matches(allowed, f018, mention_index)
    assert not _statement_matches(allowed, f017, mention_index)
    assert not _statement_matches(allowed, f017, mention_index, strict=False)
    assert not _statement_matches(refused, f017, mention_index)
    assert not _statement_matches(refused, f018, mention_index)
    assert _statement_matches(refused, f017, mention_index, strict=False)
    assert _statement_matches(refused, f018, mention_index, strict=False)


def test_a_claim_does_not_rescue_an_over_claim():
    """Item 4: the claim agrees (7 days of grace), but the statement says
    the membership lapses, which the grace period's assertion never proves;
    it does not name the quantity the fact is about, so no reading credits
    it. A statement naming the grace period is credited by the same claim."""
    truth = _wiki_truth(
        "A failed renewal gives a membership a grace period that ends 7 days after the failure.",
        claim={"entity": "E-x", "attribute": "grace", "value": 7, "unit": "day"},
    )
    claim = {"attribute": "grace_days", "value": 7, "unit": "days", "_resolved_entities": ["E-x"]}
    over_claim = _wiki_fact("Membership lapses 7 days after failed renewal.", claim)
    assert not facts_match(over_claim, truth)
    assert not facts_match(over_claim, truth, strict=False)
    assert facts_match(
        _wiki_fact("Membership grace ends 7 days after a failed renewal.", claim), truth
    )


def test_strict_reading_wants_the_value_in_the_statement():
    """Item 4: "Casual rate from 1st minute." with a claim of $0.25 leaves
    the value to its claim; the strict reading does not credit it, the
    lenient one does (the claim agrees in full)."""
    truth = _wiki_truth(
        "A rider without a membership pays $0.25 per minute from the first minute of the ride.",
        claim={
            "entity": "E-x",
            "attribute": "casual_rate_per_minute",
            "value": 0.25,
            "unit": "usd",
        },
    )
    claim = {
        "attribute": "casual_rate",
        "value": 0.25,
        "unit": "usd",
        "_resolved_entities": ["E-x"],
    }
    assert not facts_match(_wiki_fact("Casual rate from 1st minute.", claim), truth)
    assert facts_match(_wiki_fact("Casual rate from 1st minute.", claim), truth, strict=False)
    assert facts_match(_wiki_fact("Casual rate $0.25 from 1st minute.", claim), truth)


def test_wilson_lower_bound():
    """26 of 27 passes 0.95 at a Wilson 95% lower bound of 0.82 (D-014)."""
    assert round(wilson_lower_bound(26, 27), 3) == 0.817
    assert round(wilson_lower_bound(20, 27), 3) == 0.553
    assert wilson_lower_bound(0, 0) is None


def test_distinct_executed_counts_each_fact_once_against_any_executed_truth_fact():
    """Item 1: every returned executed fact counted once, by id or by its
    statement and citations, whichever query returned it, and correct when
    it matches any executed truth fact — not only one its query expected."""
    planted = _wiki_truth("A single ride costs at most $30.00.")
    planted = TruthFact(**{**planted.__dict__, "tier": "executed"})
    documented = TruthFact(**{**planted.__dict__, "id": "F-2", "tier": "documented"})
    hit = {**_wiki_fact("Single ride cap $30.00."), "tier": "executed", "id": "f-1"}
    restated = {**hit, "statement": "A single ride is capped at $30.00."}  # same id
    unnamed = {**_wiki_fact("A single ride costs at most $30.00."), "tier": "executed"}
    wrong = {**_wiki_fact("A single ride costs at most $25.00."), "tier": "executed"}
    other_tier = {**_wiki_fact("A single ride costs at most $30.00."), "tier": "code"}
    returned = [hit, restated, unnamed, dict(unnamed), wrong, other_tier]
    report = distinct_executed(returned, {"F-1": planted})
    assert report["strict"]["n"] == 3
    assert report["strict"]["tp"] == 2
    assert report["strict"]["wrong"] == ["A single ride costs at most $25.00."]
    assert report["strict"]["wilson_lower"] == wilson_lower_bound(2, 3)
    assert distinct_executed(returned, {"F-2": documented})["strict"]["tp"] == 0


def test_score_reports_distinct_executed_across_explain_and_search(capsys):
    """Item 1 through `score()`: the hand-built run returns its one executed
    fact on explain and on search; the distinct reading counts it once, and
    the line is printed beside the per-surface lines."""
    report = score(_hand_built_results(), MINI_ROOT / "truth")
    assert report["surfaces"]["explain"]["tier"]["returned_executed"] == 1
    assert report["surfaces"]["search"]["tier"]["returned_executed"] == 1
    distinct = report["distinct_executed"]
    assert {r: (d["tp"], d["n"]) for r, d in distinct.items()} == {
        "strict": (1, 1),
        "lenient": (1, 1),
    }
    print_report(report)
    assert (
        "executed tier, distinct facts (explain+search): strict precision=1.000 (1/1, "
        "Wilson 95% lower=0.207) | lenient precision=1.000 (1/1, Wilson 95% lower=0.207)"
    ) in capsys.readouterr().out
    agg = aggregate_reports([report, report])
    assert agg["distinct_executed"]["strict"] == {"median": 1.0, "min": 1.0, "max": 1.0}


def test_a_restated_fact_is_counted_apart_from_hard_false_positives():
    """Item 6: a second returned fact that would match the truth fact the
    query already credited is `restated`, not a hard false positive; an
    unmatched fact naming the right entity and document at another value
    still is one."""
    truth = _wiki_truth("A single ride costs at most $30.00.")
    first = _wiki_fact("A single ride costs at most $30.00.")
    second = _wiki_fact("The most a single ride can cost is $30.00.")
    other = _wiki_fact("A single ride costs at most $25.00.")
    outcome = score_fact_query([first, second, other], {"F-1": truth}, None, _identity_index("E-x"))
    assert outcome["tp"] == 1
    assert outcome["restated"] == 1
    assert outcome["hard_false_positives"] == 1
    restated, rest = _split_restated([second, other], {"F-1"}, {"F-1": truth})
    assert restated == [second]
    assert rest == [other]


def test_invented_calibration_set_is_perfect_under_both_readings():
    """Item 4: the invented set, with the #35 pairs and relabels, holds at
    1.0/1.0 under the strict reading and the lenient one; each relabelled
    pair says which strict rule decides it and keeps its lenient label."""
    pairs = load_calibration(SPIKE_ROOT / DEFAULT_CALIBRATION)
    truth = load_truth(SPIKE_ROOT / "truth")
    indexes = (build_mention_index(truth), build_alias_index(truth), truth.entities)
    for strict in (True, False):
        report = calibrate(pairs, *indexes, strict=strict)
        assert (report["precision"], report["recall"]) == (1.0, 1.0), report["misclassified"]
    relabelled = [p for p in pairs if str(p.get("why", "")).startswith("#35 item 4")]
    assert len(relabelled) == 2
    assert all(p["expect"] is False and p["lenient_expect"] is True for p in relabelled)


def _side(statement: str, entities: list[str], documents: list[str]) -> dict:
    return {
        "statement": statement,
        "entities": entities,
        "category": "business-logic",
        "citations": [{"document": d} for d in documents],
    }


@pytest.mark.fixture
def test_contradiction_side_with_a_kind_prefix_and_a_clause_is_credited():
    """Item 5, the baseline's X-002 pair: its sides name the entity
    "rule:membership-grace-period", which only resolves once the known kind
    prefix is stripped, and the test side states F-016 in its second clause
    only ("GRACE_DAYS is 7; a lapsed-payment membership stays in grace for 7
    days after a failed renewal.")."""
    truth = load_truth(SPIKE_ROOT / "truth")
    alias_index, mention_index = build_alias_index(truth), build_mention_index(truth)
    rc = {
        "a": _side(
            "GRACE_DAYS is 7; a lapsed-payment membership stays in grace for 7 days after a "
            "failed renewal.",
            ["rule:membership-grace-period"],
            ["code/farebox/services/memberships.py", "run/pytest-c3"],
        ),
        "b": _side(
            "A member who misses a renewal gets a 3-day grace period to fix their payment "
            "method before anything lapses.",
            ["rule:membership-grace-period"],
            ["wiki/membership-faq"],
        ),
    }
    expected = {"X-002": truth.contradictions["X-002"]}
    resolved = _resolve_contradiction_entities(rc, alias_index, truth.entities)
    assert resolved["a"]["entities"] == ["E-rule-membership-grace"]
    assert _side_matches(resolved["a"], truth.facts["F-016"], mention_index)
    assert not facts_match(resolved["a"], truth.facts["F-016"], mention_index)  # whole wording
    assert score_contradictions([resolved], expected, truth.facts, mention_index)["matched"] == 1
    unstripped = {k: resolve_fact_entities(v, alias_index, truth.entities) for k, v in rc.items()}
    assert unstripped["a"]["entities"] == []
    assert score_contradictions([unstripped], expected, truth.facts, mention_index)["matched"] == 0


@pytest.mark.fixture
def test_contradiction_side_naming_one_threshold_of_two_is_not_credited():
    """Item 5, hard negative (the baseline's X-006 pair): F-021 has two
    thresholds (under 20% or over 90%); a side naming only the 20% one does
    not state it, so the pair is not credited, though its wiki side states
    F-047 and nothing is loosened for contradictions."""
    truth = load_truth(SPIKE_ROOT / "truth")
    alias_index, mention_index = build_alias_index(truth), build_mention_index(truth)
    entities = ["rule:rebalance-trigger", "job:nightly-rebalance"]
    rc = _resolve_contradiction_entities(
        {
            "a": _side(
                "A station is flagged for rebalance once it falls under 20% full (LOW_FILL = 0.2).",
                entities,
                ["code/dispatch/src/jobs/nightlyRebalance.ts"],
            ),
            "b": _side(
                "A station gets flagged for a rebalance order once it drops under 25% full.",
                entities,
                ["wiki/rebalancing-overview"],
            ),
        },
        alias_index,
        truth.entities,
    )
    assert _side_matches(rc["b"], truth.facts["F-047"], mention_index)
    assert not _side_matches(rc["a"], truth.facts["F-021"], mention_index)
    expected = {"X-006": truth.contradictions["X-006"]}
    assert score_contradictions([rc], expected, truth.facts, mention_index)["matched"] == 0


# --------------------------------------------------------------------------
# The #35 lens round
# --------------------------------------------------------------------------

_F019 = "A rider can hold at most 2 bikes at once, so a third check-out is refused."
_F013 = "A refund requested more than 14 days after the ride ended is rejected."


_F017 = "A check-in at a full station is refused when the overflow_parking flag is off."


def test_a_flipped_outcome_is_refused_whatever_bound_it_names():
    """Item 3: an allowed side against a refused fact is refused in both
    readings, whatever bound or number it names: the lens rounds' probes,
    each of which an exception for bounded statements let through."""
    for candidate, truth in (
        ("3rd checkout allowed.", _F019),
        ("Checkin at full station allowed with overflow parking.", _F017),
        ("Refunds are accepted within 30 days after the ride ended.", _F013),
        ("A third check-out is allowed within the 2 bikes at once limit for a rider.", _F019),
        (
            "A check-in at a full station is accepted within seconds when the "
            "overflow_parking flag is off.",
            _F017,
        ),
        (
            "A refund requested more than 14 days after the ride ended is accepted before review.",
            _F013,
        ),
        (
            "A rider can hold at most 2 bikes at once, so a check-out of a further bike is "
            "allowed.",
            _F019,
        ),
    ):
        assert _outcome_conflict(candidate, truth), candidate
        assert not _statement_matches(candidate, truth), candidate
        assert not _statement_matches(candidate, truth, strict=False), candidate


def test_a_permitted_side_statement_of_a_limit_is_refused_as_the_vetos_known_cost():
    """Decided in the asbuilt#35 lens round (conductor, by delegation): the
    outcome veto is lexical and has no exception. "A rider is allowed to
    hold at most 2 bikes at once." states F-019 correctly from its
    permitted side, and is refused: a known false negative, accepted,
    because telling the permitted side of a limit from its opposite is
    semantic, two exceptions for it each let a flipped outcome through,
    and this scorer keeps precision at 1.0 and reports recall."""
    permitted = "A rider is allowed to hold at most 2 bikes at once."
    assert _outcome_conflict(permitted, _F019)
    assert not _statement_matches(permitted, _F019)
    assert not _statement_matches(permitted, _F019, strict=False)


def test_the_over_claim_is_refused_without_a_claim_too():
    """F2: whether an arm sent a claim does not decide whether its
    statement over-claims."""
    truth = _wiki_truth(
        "A failed renewal gives a membership a grace period that ends 7 days after the failure.",
        claim={"entity": "E-x", "attribute": "grace", "value": 7, "unit": "day"},
    )
    claimless = _wiki_fact("Membership lapses 7 days after failed renewal.")
    assert not facts_match(claimless, truth)
    assert not facts_match(claimless, truth, strict=False)
    assert facts_match(_wiki_fact("A failed renewal starts a grace period of 7 days."), truth)


@pytest.mark.fixture
def test_a_flag_named_with_other_separators_carries_its_condition_and_state():
    """F3: "With the e-bike surcharge enabled" names ebike_surcharge and
    its state; "disabled" there is the opposite state."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    f007 = truth.facts["F-007"].statement
    enabled = (
        "With the e-bike surcharge enabled, every charged minute of an e-bike ride costs an "
        "extra $0.10."
    )
    disabled = enabled.replace("enabled", "disabled")
    assert _statement_matches(enabled, f007, mention_index)
    assert _flag_state_conflict(disabled, f007, mention_index)
    assert not _statement_matches(disabled, f007, mention_index, strict=False)


@pytest.mark.fixture
def test_a_winner_stating_both_facts_through_its_clauses_is_not_credited():
    """F4, the deep lens's probe: a winner whose clauses state F-042 (up to
    3) and F-019 (at most 2) picks neither, so the X-005 winner is not
    credited; the pair itself still is."""
    truth = load_truth(SPIKE_ROOT / "truth")
    alias_index, mention_index = build_alias_index(truth), build_mention_index(truth)
    code = ["code/dockyard/services/checkout.py", "code/tests/e2e/test_checkout.py"]
    rc = _resolve_contradiction_entities(
        {
            "a": _side(
                "A rider can hold up to 3 bikes at once.",
                ["rule:checkout-limit"],
                ["wiki/checkout-rules"],
            ),
            "b": _side(_F019, ["rule:checkout-limit"], code),
            "winner": _side(
                "A rider can hold up to 3 bikes at once; the code's limit of 2 bikes at once is a "
                "regression and a third check-out is refused only by mistake.",
                ["rule:checkout-limit"],
                ["wiki/checkout-rules", *code],
            ),
        },
        alias_index,
        truth.entities,
    )
    xc = {"X-005": truth.contradictions["X-005"]}
    report = score_contradictions([rc], xc, truth.facts, mention_index)
    assert (report["matched"], report["winner_checked"], report["winner_correct"]) == (1, 1, 0)
    f019, f042 = truth.facts["F-019"], truth.facts["F-042"]
    assert _side_matches(rc["winner"], f019, mention_index)  # a clause, with no opposing fact
    assert not _side_matches(rc["winner"], f019, mention_index, f042)


@pytest.mark.fixture
def test_distinct_executed_targets_follow_the_runs_step():
    """F5: F-007's test proves it from c5, so a run through c4 returning it
    as executed is wrong; through c6 it is right; with no step, the static
    tier decides as before. F-002, proven at c2 and c3, stays a target
    through c6: the run holds the history."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    order, at_c4 = _run_step_rank("c4", _step_dates(SPIKE_ROOT), {})
    _, at_c6 = _run_step_rank("c6", _step_dates(SPIKE_ROOT), {})
    ebike = {
        "statement": truth.facts["F-007"].statement,
        "entities": ["E-rule-ebike-surcharge"],
        "tier": "executed",
        "citations": [{"document": "code/tests/unit/test_pricing.py"}],
    }
    forty_five = {
        "statement": truth.facts["F-002"].statement,
        "entities": ["E-rule-member-free-minutes"],
        "tier": "executed",
        "citations": [{"document": "code/tests/e2e/test_pricing.py"}],
    }

    def tp(facts, rank):
        return distinct_executed(facts, truth.facts, mention_index, order, rank)["strict"]["tp"]

    assert tp([ebike], at_c4) == 0
    assert tp([ebike], at_c6) == 1
    assert distinct_executed([ebike], truth.facts, mention_index)["strict"]["tp"] == 1
    assert tp([forty_five], at_c6) == 1


def test_a_unit_word_heading_a_hyphenated_modifier_does_not_merge():
    """F6: "forty five-minute rides" are 40 rides of 5 minutes; the
    hyphenated "forty-five-minute" and the closed "fortyfive-minute" are
    still 45."""
    assert _number_tokens("forty five-minute rides") == {"40", "5"}
    assert _number_tokens("thirty one-hour slots") == {"30", "1"}
    assert _number_tokens("a forty-five-minute ride") == {"45"}
    assert _number_tokens("a fortyfive-minute ride") == {"45"}
    assert _number_tokens("forty five minutes") == {"45"}


# --------------------------------------------------------------------------
# konyklabs/asbuilt#38: executed-tier precision per backend fidelity, and the
# fake-versus-real contradiction (D-014). tests/fixtures/fidelity-results.json
# is a hand-made run through c7 against the real truth, one fact per case.
# --------------------------------------------------------------------------

FIDELITY_RESULTS = SPIKE_ROOT / "tests" / "fixtures" / "fidelity-results.json"


@functools.cache
def _fidelity_report() -> dict:
    results = json.loads(FIDELITY_RESULTS.read_text())
    return score({**results, "fixture": str(SPIKE_ROOT)}, SPIKE_ROOT / "truth")


def _explain_fidelity() -> dict:
    return _fidelity_report()["surfaces"]["explain"]["tier"]["fidelity"]


@pytest.mark.fixture
def test_fidelity_case_right_fidelity_is_a_true_positive_at_its_fidelity():
    """F-124 claimed `real`, citing the real project's run: a hit at `real`,
    on explain and in the distinct measure (a Playwright run carrier counts
    at its project's fidelity)."""
    real = _explain_fidelity()["by_fidelity"]["real"]
    assert (real["tp"], real["expected"]) == (1, 2)
    assert _explain_fidelity()["confusion"]["real"]["real"] == 1
    distinct_real = _fidelity_report()["distinct_executed_by_fidelity"]["by_fidelity"]["real"]
    assert (distinct_real["strict"]["tp"], distinct_real["strict"]["n"]) == (1, 2)


@pytest.mark.fixture
def test_fidelity_case_claimed_real_but_proven_only_at_fake_is_a_miss_at_real():
    """F-123's $25 cap claimed `real`, citing its fake run and its real run:
    the truth has it passing only against the fake and the mocked routes,
    demoted by the real run, so it is no executed target at all. Its real
    test failed, so that citation counts at no fidelity: a hard error at
    `real` too (lens round G2)."""
    real = _explain_fidelity()["by_fidelity"]["real"]
    assert (real["tp"], real["returned"], real["precision"]) == (1, 2, 0.5)
    assert real["hard_errors"] == 1
    assert _explain_fidelity()["confusion"]["none"] == {"real": 1}
    distinct = _fidelity_report()["distinct_executed"]["strict"]
    assert (distinct["tp"], distinct["n"]) == (3, 4)
    assert distinct["wrong"] == ["The fare preview page caps a casual ride at $25.00."]


@pytest.mark.fixture
def test_fidelity_case_executed_without_fidelity_is_unqualified_not_an_error():
    """F-121 claimed `executed` with no fidelity: its own bucket, credited
    against an executed target of any fidelity, and no hard error."""
    fidelity = _explain_fidelity()
    assert fidelity["unqualified"] == {"returned": 1, "tp": 1, "precision": 1.0}
    assert fidelity["confusion"]["real"]["unqualified"] == 1
    assert {f: row["hard_errors"] for f, row in fidelity["by_fidelity"].items()} == {
        "real": 1,
        "in-process": 0,
        "fake": 1,
        "mocked": 0,
    }
    unqualified = _fidelity_report()["distinct_executed_by_fidelity"]["unqualified"]
    assert (unqualified["strict"]["tp"], unqualified["strict"]["n"]) == (1, 1)


@pytest.mark.fixture
def test_fidelity_case_a_fidelity_with_no_run_at_it_is_a_hard_error():
    """F-122 claimed `fake`, citing only the mocked project's run: a hard
    error at `fake`, whatever the fact says of itself; and a miss, since the
    truth proves it at `mocked`."""
    fake = _explain_fidelity()["by_fidelity"]["fake"]
    assert (fake["hard_errors"], fake["returned"], fake["tp"]) == (1, 1, 0)
    assert _explain_fidelity()["confusion"]["mocked"] == {"fake": 1}
    assert _explain_fidelity()["bands"]["below"]["hard_errors"] == 1


@pytest.mark.fixture
def test_fidelity_case_fake_vs_real_contradiction_winner_checked():
    """X-022 returned twice, by two queries: once won by F-124 (the real
    run's fact, right) and once by F-123 (wrong)."""
    contradictions = _fidelity_report()["surfaces"]["contradictions"]
    assert contradictions["by_kind"]["fake-vs-real"] == {
        "matched": 2,
        "expected": 2,
        "winner_checked": 2,
        "winner_correct": 1,
    }


@pytest.mark.fixture
def test_fidelity_lines_print_in_bands(capsys):
    print_report(_fidelity_report())
    out = capsys.readouterr().out
    assert (
        "      at or above the real backend (outranks code): precision=0.500 (1/2) "
        "recall=0.500 (1/2) hard_errors=1\n"
        "        real: precision=0.500 (1/2) recall=0.500 (1/2) hard_errors=1\n"
        "        in-process: precision=n/a (0/0) recall=n/a (0/0) hard_errors=0\n"
        "      below the real backend (code outranks): precision=0.000 (0/1) "
        "recall=0.000 (0/1) hard_errors=1\n"
    ) in out
    assert "    kind fake-vs-real: matched=2 vs expected=2 recall=1.000 winner=1/2" in out


def test_fidelity_bands_follow_the_vocabulary_not_hard_coded_names():
    """The bands come from `fidelities.yaml`'s order and real backend: here
    an invented vocabulary whose real backend is its second name."""
    fidelities = Fidelities(ranked=("gold", "silver", "tin"), real_backend="silver")
    merged = _merge_fidelity_counts([], fidelities)
    assert merged["bands"]["at_or_above"]["fidelities"] == ["gold", "silver"]
    assert merged["bands"]["below"]["fidelities"] == ["tin"]
    assert list(merged["by_fidelity"]) == ["gold", "silver", "tin"]


@pytest.mark.fixture
def test_step_tier_at_c7_knows_playwright_and_the_demotion():
    """The deep lens on #37: at c7 F-121 and F-124 are executed at `real`,
    F-122 at `mocked`; F-123, passing only below the real run that demoted
    it, is `documented`, not executed and not `code` through its test file.
    F-011 (demoted at c5 by a pytest run) is still executed at c1."""
    truth = load_truth(SPIKE_ROOT / "truth")
    commits = {step: {"date": d.isoformat()} for step, d in _step_dates(SPIKE_ROOT).items()}
    order = _step_order(commits)
    fidelities = truth.fidelities

    def tier(fid: str, step: str = "c7") -> str:
        return _expected_tier_at_step(truth.facts[fid], step, fidelities, order)

    def fidelity(fid: str) -> str | None:
        return _expected_fidelity_at_step(truth.facts[fid], "c7", fidelities)

    assert [tier(f) for f in ("F-121", "F-122", "F-123", "F-124")] == [
        "executed",
        "executed",
        "documented",
        "executed",
    ]
    assert [fidelity(f) for f in ("F-121", "F-122", "F-123", "F-124")] == [
        "real",
        "mocked",
        None,
        "real",
    ]
    assert (tier("F-011", "c1"), tier("F-011", "c5")) == ("executed", "code")


@pytest.mark.fixture
def test_facts_at_c7_score_per_fidelity_on_a_hand_made_bag():
    """`--facts` at c7 on the hand-made file's four facts, under the default
    `tests` filter, which holds the portal's Playwright specs: the same
    counts as explain, and F-123 matched but expected `documented`. A spec
    file is a test carrier, so F-123, carried in code only by its spec, is
    out of the `code` filter."""
    commits = {step: {"date": d.isoformat()} for step, d in _step_dates(SPIKE_ROOT).items()}
    bag = json.loads(FIDELITY_RESULTS.read_text())["queries"][0]["result"]
    report = score_test_connector(bag, SPIKE_ROOT / "truth", "c7", commits)
    assert report["tp"] == 4
    assert report["tier_confusion"]["confusion"]["documented"] == {"executed": 1}
    code = score_test_connector(bag, SPIKE_ROOT / "truth", "c7", commits, "code")
    assert code["tp"] == 3
    fidelity = report["fidelity"]
    assert {f: (r["tp"], r["returned"]) for f, r in fidelity["by_fidelity"].items()} == {
        "real": (1, 2),
        "in-process": (0, 0),
        "fake": (0, 1),
        "mocked": (0, 0),
    }
    assert fidelity["by_fidelity"]["fake"]["hard_errors"] == 1
    assert fidelity["unqualified"]["tp"] == 1
    assert report["fake_vs_real_candidates"]["expected"] == 1


@pytest.mark.fixture
def test_a_demotion_applies_from_the_demoting_runs_step_on():
    """A synthetic fact passing at `fake` at c6 and failing at `real` only at
    c7: before the real failure exists the fake pass lifts it, so it is an
    executed target at `fake` through c6; through c7 it is not."""
    truth = load_truth(SPIKE_ROOT / "truth")
    fidelities = truth.fidelities
    commits = {step: {"date": d.isoformat()} for step, d in _step_dates(SPIKE_ROOT).items()}
    order = _step_order(commits)
    title = "fare preview › shows an invented cap"
    tf = TruthFact(
        id="F-X",
        statement="The fare preview page shows an invented cap.",
        category="business-logic",
        entities=("E-page-fare-preview",),
        tier="documented",
        carriers=(Carrier(document="run/playwright-c6", location=title, project="fake"),),
        demoted_by=Carrier(document="run/playwright-c7", location=title, project="real"),
    )
    assert _executed_by_step(tf, order, order["c6"], fidelities)
    assert _fidelity_by_step(tf, order, order["c6"], fidelities) == "fake"
    assert not _executed_by_step(tf, order, order["c7"], fidelities)
    assert _expected_tier_at_step(tf, "c6", fidelities, order) == "executed"
    assert _expected_tier_at_step(tf, "c7", fidelities, order) == "documented"


# The #38 lens round (G1-G4), on hand-made runs over the same portal facts.

_FAREBOX_CAP = "fare preview › shows the farebox cap for a 200-minute casual ride"
_SHEET_CAP = "fare preview › shows the price-sheet cap for a 200-minute casual ride"
_REFUND_15 = "refund request › refuses a ride that ended 15 days ago"
_LIMIT_BANNER = "check-out › shows a banner when the rider is at the bike limit"


def _portal_fact(case: int, **changes) -> dict:
    """One of the hand-made file's four explain facts (0: F-124, 1: F-123,
    2: F-121, 3: F-122), with `changes` applied."""
    fact = json.loads(FIDELITY_RESULTS.read_text())["queries"][0]["result"][case]
    return {**fact, **changes}


def _portal_report(facts: list[dict], through_step: str = "c7") -> dict:
    """`score()` on one explain query for the rider portal returning `facts`."""
    results = json.loads(FIDELITY_RESULTS.read_text())
    query = {
        "id": "q-explain-portal",
        "surface": "explain",
        "latency_ms": 1.0,
        "params": {"entity": "rider-portal"},
        "result": facts,
    }
    run = {**results, "fixture": str(SPIKE_ROOT), "through_step": through_step, "queries": [query]}
    return score(run, SPIKE_ROOT / "truth")


def _run(location: str, project: str | None, document: str = "run/playwright-c7") -> dict:
    citation = {"document": document, "location": location, "project": project}
    return {k: v for k, v in citation.items() if v is not None}


@pytest.mark.fixture
def test_g1_one_fact_claimed_at_two_fidelities_is_two_claims_in_either_order():
    """G1: F-121 claimed `real` (citing the real run) and `mocked` (citing
    the mocked run) is judged once per claimed fidelity, whichever comes
    first: real 1/1, mocked 0/1. #35's overall line still counts it once."""
    right = _portal_fact(2, fidelity="real")
    wrong = _portal_fact(2, fidelity="mocked", citations=[_run(_REFUND_15, "mocked")])
    for facts in ([right, wrong], [wrong, right]):
        report = _portal_report(facts)
        by_fidelity = report["distinct_executed_by_fidelity"]["by_fidelity"]
        assert {
            f: (by_fidelity[f]["strict"]["tp"], by_fidelity[f]["strict"]["n"])
            for f in (
                "real",
                "mocked",
            )
        } == {"real": (1, 1), "mocked": (0, 1)}
        assert report["distinct_executed"]["strict"]["n"] == 1


@pytest.mark.fixture
def test_g2_a_citation_counts_only_for_a_passing_truth_run_by_the_step():
    """G2: a failed run (F-123's real run), a run that does not exist
    (`run/playwright-c3`, `run/pytest-c99`) and a run after the result's
    step count at no fidelity, so a claim resting on one is a hard error.
    A passing truth run by the step, with or without its test, counts."""
    truth = load_truth(SPIKE_ROOT / "truth")
    order, at_c7 = _run_step_rank("c7", _step_dates(SPIKE_ROOT), {})
    _, at_c6 = _run_step_rank("c6", _step_dates(SPIKE_ROOT), {})
    fidelities = truth.fidelities

    def cited(citation: dict, rank: int) -> set:
        runs = truth_runs(truth.facts, order, rank)
        return _citation_fidelities({"citations": [citation]}, fidelities, runs)

    assert cited(_run(_SHEET_CAP, "real"), at_c7) == set()
    assert cited(_run(_FAREBOX_CAP, "real", "run/playwright-c3"), at_c7) == set()
    assert cited({"document": "run/pytest-c99"}, at_c7) == set()
    assert cited(_run(_FAREBOX_CAP, "real"), at_c6) == set()
    assert cited(_run(_FAREBOX_CAP, "real"), at_c7) == {"real"}
    assert cited({"document": "run/playwright-c7", "project": "real"}, at_c7) == {"real"}
    assert cited({"document": "run/pytest-c6"}, at_c6) == {"in-process"}

    claims = [
        _portal_fact(0, citations=[_run(_SHEET_CAP, "real")]),
        _portal_fact(0, citations=[_run(_FAREBOX_CAP, "real", "run/playwright-c3")]),
        _portal_fact(0, fidelity="in-process", citations=[{"document": "run/pytest-c99"}]),
    ]
    by_fidelity = _portal_report(claims)["surfaces"]["explain"]["tier"]["fidelity"]["by_fidelity"]
    assert (by_fidelity["real"]["hard_errors"], by_fidelity["in-process"]["hard_errors"]) == (2, 1)
    after_the_step = _portal_report([_portal_fact(0)], through_step="c6")
    assert (
        after_the_step["surfaces"]["explain"]["tier"]["fidelity"]["by_fidelity"]["real"][
            "hard_errors"
        ]
        == 1
    )
    assert (
        _portal_report([_portal_fact(0)])["surfaces"]["explain"]["tier"]["fidelity"]["by_fidelity"][
            "real"
        ]["hard_errors"]
        == 0
    )


@pytest.mark.fixture
def test_g3_an_over_claim_above_the_proven_fidelity_is_a_miss():
    """G3: F-122, proven at `mocked`, claimed `real`. Citing its own test at
    the real project, where it was skipped, it is a miss at `real` and a
    hard error; citing the real run with no test, it is a miss and no hard
    error: a real run at c7 exists, but not one that proves F-122."""
    at_its_test = _portal_fact(3, fidelity="real", citations=[_run(_LIMIT_BANNER, "real")])
    fidelity = _portal_report([at_its_test])["surfaces"]["explain"]["tier"]["fidelity"]
    real = fidelity["by_fidelity"]["real"]
    assert (real["tp"], real["returned"], real["hard_errors"]) == (0, 1, 1)
    assert fidelity["confusion"] == {"mocked": {"real": 1}}
    at_the_run = _portal_fact(
        3, fidelity="real", citations=[{"document": "run/playwright-c7", "project": "real"}]
    )
    real = _portal_report([at_the_run])["surfaces"]["explain"]["tier"]["fidelity"]["by_fidelity"][
        "real"
    ]
    assert (real["tp"], real["returned"], real["hard_errors"]) == (0, 1, 0)


@pytest.mark.fixture
def test_g4_a_non_string_fidelity_or_project_is_absent_not_a_crash():
    """G4: a list-valued `fidelity` is unqualified; a list-valued `project`
    is no project, so the claim it carries has no run at its fidelity; a
    non-string `location` is no location, so the real run alone counts."""
    listed_fidelity = _portal_fact(0, fidelity=["real"])
    listed_project = _portal_fact(
        0,
        citations=[
            {"document": "run/playwright-c7", "location": _FAREBOX_CAP, "project": ["real"]}
        ],
    )
    report = _portal_report([listed_fidelity])
    assert report["surfaces"]["explain"]["tier"]["fidelity"]["unqualified"]["returned"] == 1
    assert report["distinct_executed_by_fidelity"]["unqualified"]["strict"]["n"] == 1
    fidelity = _portal_report([listed_project])["surfaces"]["explain"]["tier"]["fidelity"]
    assert fidelity["by_fidelity"]["real"]["hard_errors"] == 1
    odd_location = _portal_fact(
        0,
        citations=[{"document": "run/playwright-c7", "location": {"line": 12}, "project": "real"}],
    )
    fidelity = _portal_report([odd_location])["surfaces"]["explain"]["tier"]["fidelity"]
    assert fidelity["by_fidelity"]["real"]["hard_errors"] == 0


# --------------------------------------------------------------------------
# konyklabs/asbuilt#63: the marking corrections #36's measurement found
# --------------------------------------------------------------------------


@pytest.mark.fixture
def test_a_complement_bound_against_a_negated_bound_is_refused_as_the_vetos_known_cost():
    """Decided in the asbuilt#63 lens round (conductor): the negation veto
    stays as it is. "Ride open past 24 hours closed as lost." states F-010
    ("A ride whose bike is not docked within 24 hours of check-out is
    closed as lost.") from the bound's other side, and is refused: a known
    false negative, accepted. Two designs that read a negated `within`
    bound as its complement each credited a wrong statement. The first,
    counting an unread negated bound as `beyond`, credited "A ride whose
    bike is not docked past 24 hours is closed as lost."; the second, with
    an unknown direction for it, credited "Every ride is closed as lost
    after 24 hours." This scorer keeps precision at 1.0 and reports
    recall; the two designs' 22 calibration pairs are asbuilt#66's
    evidence. asbuilt#66 only refuses, so the four complement paraphrases
    among them stay refused, here rather than in the calibration set, and
    its bound rule now refuses them on their direction too ("past" against
    the raw "within")."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    f010 = truth.facts["F-010"]
    for complement in (
        "Ride open past 24 hours closed as lost.",
        "A ride whose bike is still undocked more than 24 hours after check-out is closed as lost.",
    ):
        for strict in (True, False):
            assert not _statement_matches(
                complement, f010.statement, mention_index, None, f010.claim, strict
            )
    invented = {
        "A bike still out past 24 hours costs the rider a $100.00 lost-bike fee.": (
            "A bike that is not docked within 24 hours costs the rider a $100.00 lost-bike fee."
        ),
        "Each Tollbooth Pay call times out when it does not answer within 5 seconds.": (
            "Each Tollbooth Pay call times out after 5 seconds."
        ),
    }
    for candidate, statement in invented.items():
        for strict in (True, False):
            assert not _statement_matches(candidate, statement, mention_index, strict=strict)


@pytest.mark.fixture
def test_f051_states_its_flag_condition():
    """Item 2: F-051's 409 holds only while the overflow_parking flag is off
    (F-017, F-018), so the truth says so: a statement carrying the
    condition is credited under the strict reading, one naming the other
    state is not, and one dropping it no longer is."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    f051 = truth.facts["F-051"]
    assert f051.statement.endswith("when the overflow_parking flag is off.")

    def matches(candidate: str) -> bool:
        return _statement_matches(candidate, f051.statement, mention_index, None, f051.claim)

    assert matches(
        "A check-in at a full station gets HTTP 409 station_full while the overflow_parking "
        "flag is off."
    )
    assert not matches(
        "POST /rides/{id}/checkin at a full station returns HTTP 409 with error code "
        "station_full when the overflow_parking flag is on."
    )
    assert not matches(
        "POST /rides/{id}/checkin at a full station returns HTTP 409 with error code station_full."
    )


@pytest.mark.fixture
def test_step_tier_follows_the_distinct_target_rule():
    """Item 3: under `--facts` a fact is executed at a step when a run at or
    before it lifts it and no demotion applies by then. F-050's flaky c6
    cites no run, so it stays executed on c1 to c5; F-007, proven from c5,
    is code before; F-011 is code from its c5 demotion; F-012 is executed
    from c6; F-123 is documented at c7. A run lifts a fact only before its
    `valid_to` (lens round): F-001, F-015, F-002 and F-008 are `code` at
    their `valid_to` step, as on main (and since asbuilt#66 out of the
    `--facts` scope there, `_current_at_step`)."""
    truth = load_truth(SPIKE_ROOT / "truth")
    commits = {step: {"date": d.isoformat()} for step, d in _step_dates(SPIKE_ROOT).items()}
    order = _step_order(commits)

    def tier(fid: str, step: str) -> str:
        return _expected_tier_at_step(truth.facts[fid], step, truth.fidelities, order)

    assert [tier("F-011", s) for s in ("c1", "c4", "c5", "c6")] == [
        "executed",
        "executed",
        "code",
        "code",
    ]
    assert [tier("F-007", s) for s in ("c1", "c2", "c3", "c4", "c5", "c6")] == [
        "code",
        "code",
        "code",
        "code",
        "executed",
        "executed",
    ]
    assert tier("F-050", "c6") == "executed"
    assert _expected_fidelity_at_step(truth.facts["F-050"], "c6", truth.fidelities, order) == (
        "in-process"
    )
    assert [tier("F-012", s) for s in ("c6", "c7")] == ["executed", "executed"]
    assert tier("F-123", "c7") == "documented"
    assert (tier("F-001", "c1"), tier("F-001", "c2")) == ("executed", "code")
    assert [tier(f, s) for f, s in (("F-015", "c3"), ("F-002", "c4"), ("F-008", "c5"))] == [
        "code",
        "code",
        "code",
    ]


# --------------------------------------------------------------------------
# konyklabs/asbuilt#66: the scorer's refusals and its validity window
# --------------------------------------------------------------------------


@pytest.mark.fixture
def test_facts_holds_a_fact_current_only_before_its_valid_to():
    """`--facts` expects a fact at S when `valid_from` <= S < `valid_to`,
    the fixture's own window (`truth/validate.py`'s `steps_between`): every
    retired fact is in scope at the step before its `valid_to` and out of it
    there. The cost: at c5 the bag still states the failing test's $100
    (F-011, superseded by F-012's $150 at c5), which now matches nothing and
    is a hard false positive, where the closed window credited it."""
    truth = load_truth(SPIKE_ROOT / "truth")
    commits = {step: {"date": d.isoformat()} for step, d in _step_dates(SPIKE_ROOT).items()}
    order = _step_order(commits)
    steps = sorted(order, key=order.__getitem__)
    retired = {fid: tf for fid, tf in truth.facts.items() if tf.valid_to is not None}
    assert len(retired) == 14
    for tf in retired.values():
        before = steps[order[tf.valid_to] - 1]
        assert _current_at_step(tf, order, order[before]), tf.id
        assert not _current_at_step(tf, order, order[tf.valid_to]), tf.id

    def fee_100(step: str) -> dict:
        return {
            "statement": "Lost bike fee $100.00.",
            "category": "business-logic",
            "entities": ["farebox", "lost bike fee"],
            "tier": "code",
            "citations": [
                {
                    "document": "code/tests/unit/test_lost_bikes.py",
                    "location": "test_lost_bike_fee_100",
                    "version": step,
                }
            ],
        }

    at_c4 = score_test_connector([fee_100("c4")], SPIKE_ROOT / "truth", "c4", commits)
    at_c5 = score_test_connector([fee_100("c5")], SPIKE_ROOT / "truth", "c5", commits)
    assert (at_c4["tp"], at_c4["hard_false_positives"]) == (1, 0)
    assert (at_c5["tp"], at_c5["hard_false_positives"]) == (0, 1)
    assert "F-011" not in {m["id"] for m in at_c5["missed"]}


@pytest.mark.fixture
def test_a_flipped_duration_bound_is_refused_negated_or_not():
    """Item 1: where both statements state a duration bound on the same
    number and unit, the directions must agree. Each candidate keeps the
    truth fact's words and flips only the direction word; each was credited
    before the rule, so the polarity and negation rules alone let a wrong
    statement through. Refused in both readings, with the fact's own claim.
    The same direction in another word, and a duration with no direction
    word ("older than"), are still credited."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)

    def matches(candidate: str, fid: str, strict: bool) -> bool:
        tf = truth.facts[fid]
        return _statement_matches(candidate, tf.statement, mention_index, None, tf.claim, strict)

    flipped = {
        "F-013": "A refund requested within 14 days after the ride ended is rejected.",
        "F-020": (
            "A bike with 3 fault reports after 7 days is locked and gets a maintenance ticket."
        ),
        "F-048": "Support may waive the lost-bike fee when the bike is found after 72 hours.",
        "F-091": (
            "When the latest Skyglass reading is less than 60 minutes old, the storm pause "
            "does not pause rebalancing."
        ),
        "F-060": "Each Tollbooth Pay call times out within 5 seconds.",
    }
    same_direction = {
        "F-013": "A refund requested over 14 days after the ride ended is rejected.",
        "F-020": (
            "A bike with 3 fault reports in the past 7 days is locked and gets a maintenance "
            "ticket."
        ),
        "F-048": "If the bike is found within 72 hours, support may waive the lost-bike fee.",
        "F-091": (
            "When the latest Skyglass reading is older than 60 minutes, the storm pause "
            "does not pause rebalancing."
        ),
        "F-060": "A Tollbooth Pay call times out past 5 seconds.",
    }
    for strict in (True, False):
        for fid, candidate in flipped.items():
            assert not matches(candidate, fid, strict), (fid, strict)
        for fid, candidate in same_direction.items():
            assert matches(candidate, fid, strict), (fid, strict)
    assert _bound_direction_conflict("within 24 hours", "not within 24 hours past 24 hours")
    assert not _bound_direction_conflict("open for 24 hours", "past 24 hours")
    assert not _bound_direction_conflict("within 24 minutes", "past 24 hours")
    assert not _bound_direction_conflict("in the past 7 days", "within 7 days")


@pytest.mark.fixture
def test_a_negation_moved_onto_a_word_the_truth_asserts_is_refused():
    """Item 3: the plain veto asks only whether each side is negated, so it
    credited one negation for another against F-010. A word one statement
    negates that the other asserts unnegated refuses the pair, in both
    readings ("closed" here; "docked" in the last). Statements negating the
    same word, or words the other side does not use ("does not get
    automatic approval" against "is not approved automatically", a
    calibration positive), are still credited, and so is a negated word
    its own sentence also states unnegated (F-091's "storm pause does not
    pause"; an elliptical "never after"). The rule's known cost, credited
    before: "No refund" against "A refund is not"."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    f010 = truth.facts["F-010"]

    def matches(candidate: str, statement: str, claim=None, strict: bool = True) -> bool:
        return _statement_matches(candidate, statement, mention_index, None, claim, strict)

    moved = (
        "A ride is not closed as lost within 24 hours.",
        "A ride whose bike is not docked within 24 hours is not closed as lost.",
        "A ride whose bike is docked within 24 hours of check-out is not closed as lost.",
    )
    kept = (
        "A ride whose bike isn't docked within 24 hours is closed as lost.",
        "A ride is closed as lost when it is not docked within 24 hours.",
    )
    for strict in (True, False):
        for candidate in moved:
            assert not matches(candidate, f010.statement, f010.claim, strict), candidate
        for candidate in kept:
            assert matches(candidate, f010.statement, f010.claim, strict), candidate
        assert matches(
            "Unless the flag is on, a refund does not get automatic approval.",
            "A refund is not approved automatically unless the flag is on.",
            strict=strict,
        )
        assert not matches(
            "No refund is approved automatically unless the flag is on.",
            "A refund is not approved automatically unless the flag is on.",
            strict=strict,
        )
        assert matches(
            "The Tollbooth Pay client retries after a timeout or a 5xx response and never "
            "retries after a 4xx response.",
            "The Tollbooth Pay client retries only after a timeout or a 5xx response, never "
            "after a 4xx response.",
            strict=strict,
        )
        f091 = truth.facts["F-091"]
        assert matches(
            "When the latest Skyglass reading is more than 60 minutes old, the storm pause is "
            "not applied to rebalancing.",
            f091.statement,
            f091.claim,
            strict,
        )


@pytest.mark.fixture
def test_a_bound_in_another_unit_is_credited_as_a_known_false_positive():
    """The one hard negative of asbuilt#66's 22 that neither new rule
    refuses: "A ride not docked within 24 minutes is closed as lost."
    against F-010's 24 hours. Both negate "docked" and both bounds are
    `within`; the bound rule compares directions on the same number AND
    unit, and the statement path compares numbers, not their time units. A
    unit rule is a separate change (#63's withdrawn reader had one), so the
    pair is credited, a known false positive, and kept out of the
    calibration set, which holds 1.0/1.0."""
    truth = load_truth(SPIKE_ROOT / "truth")
    mention_index = build_mention_index(truth)
    f010 = truth.facts["F-010"]
    candidate = "A ride not docked within 24 minutes is closed as lost."
    for strict in (True, False):
        assert _statement_matches(
            candidate, f010.statement, mention_index, None, f010.claim, strict
        )
