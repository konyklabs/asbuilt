from __future__ import annotations

import difflib
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
    _boundary_numbers_ok,
    _claim_metrics,
    _claim_value_as_number_token,
    _claim_values_match,
    _claims_match,
    _current_at_step,
    _duplicate_count,
    _entity_mention_conflict,
    _expected_tier_at_step,
    _first_step,
    _flag_states,
    _has_negation,
    _has_test_carrier_by_step,
    _mentioned_entities,
    _normalise_unit,
    _resolve_step_or_sha,
    _resolve_temporal_value_to_step,
    _shares_matching_version,
    _split_camel,
    _statement_matches,
    _step_order,
    _temporal_field_matches,
    aggregate_reports,
    align_entities,
    bootstrap_compare,
    build_alias_index,
    build_mention_index,
    calibrate,
    classify_unmatched,
    facts_match,
    load_calibration,
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
)
from bench.truth import (
    Carrier,
    Entity,
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


def test_current_at_step_closed_interval_overlaps_at_the_boundary():
    """[valid_from, valid_to], closed on both ends (konyklabs/asbuilt#8
    review — this was half-open until the reviewer's own reproduction:
    "F-011 must be expected... at c5", exactly its own valid_to): AT the
    boundary step, BOTH the retiring and the introduced fact are in scope
    at once — deliberately, since a demotion's own step is exactly when
    the old (now-failing) test and the new (not-yet-proven) code both
    remain legitimate connector targets."""
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
    assert _current_at_step(retired_at_c2, order, order["c2"])  # still in scope AT its own valid_to
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
    # F-002, F-003, F-012: F-002's validity window is [c2, c4] (closed —
    # konyklabs/asbuilt#8 review), so it is STILL in scope exactly at its
    # own valid_to=c4, alongside F-003 (valid_from=c4) — deliberately
    # overlapping, not a bug (see _current_at_step's docstring). F-002 has
    # no run/pytest-c4 carrier of its own, so its PER-STEP tier here is
    # "code", not its eventual "executed" — nothing in this payload targets
    # it, so it is simply missed.
    assert report["expected"] == 3
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
    assert [m["id"] for m in report["missed"]] == ["F-002"]
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
    assert "missed truth facts: 3" in out  # F-002, F-003, F-012 (see the perfect/wrong-tier test)


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
    # returned names extra numbers but contains everything truth's own
    # statement names, and the claim's own value is among them.
    assert _boundary_numbers_ok({"30", "31", "$0.15"}, {"30"}, None, truth_claim)
    # returned is missing one of truth's own numbers -> not a superset.
    assert not _boundary_numbers_ok({"31", "$0.15"}, {"30", "99"}, None, truth_claim)
    # the claim's value never appears in the other side's numbers at all.
    assert not _boundary_numbers_ok({"31", "$0.15"}, {"31"}, None, truth_claim)
    # neither/both sides carry a claim -> never relaxed.
    assert not _boundary_numbers_ok({"30"}, {"30", "31"}, None, None)


def test_facts_match_claim_first_overrides_dissimilar_statement_text():
    """Both sides carry a claim: the match is decided by the claim alone —
    a completely different statement text is irrelevant once the claim
    agrees, and a matching statement doesn't save a disagreeing claim."""
    truth_fact = TruthFact(
        id="F-1",
        statement="A member's first 30 minutes of every ride are free.",
        category="business-logic",
        entities=("E-x",),
        tier="executed",
        carriers=(Carrier(document="wiki/x"),),
        claim={"entity": "E-x", "attribute": "free_minutes", "value": 30, "unit": "minute"},
    )
    returned_matching_claim = {
        "statement": "Totally different phrasing sharing hardly any vocabulary.",
        "entities": ["E-x"],
        "citations": [{"document": "wiki/x"}],
        "claim": {
            "attribute": "free_minutes",
            "value": 30,
            "unit": "minute",
            "_resolved_entities": ["E-x"],
        },
    }
    assert facts_match(returned_matching_claim, truth_fact)

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
    test carrier is version c6); F-011 must be in scope at "code" tier at
    c5 (demoted) and "executed" at c1..c4 (a run/pytest-<step> carrier at
    each of those steps)."""
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
    assert _current_at_step(f011, order, order["c5"])
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
    pair per model statement. Precision must be perfect (no candidate is
    credited with a fact it does not state) and recall is pinned at the
    measured floor, not at 1.0: the remaining misses are narratives of the
    test scenario, a negated side clause, a missing number and two close
    paraphrases under the similarity threshold, all listed on #17. Raising
    this floor by changing the matcher needs a judged pair in each
    direction, never the model's output alone."""
    pairs = load_calibration(SPIKE_ROOT / "tests/fixtures/calibration-model-run.yaml")
    assert len(pairs) == 72
    truth = load_truth(SPIKE_ROOT / "truth")
    report = calibrate(pairs, build_mention_index(truth), build_alias_index(truth), truth.entities)
    assert report["fp"] == 0, report["misclassified"]
    assert report["precision"] == 1.0
    assert report["recall"] >= 0.68, report["misclassified"]
    assert report["recall"] < 0.9  # an honest floor: see the docstring


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
    a candidate naming no state matches, one naming the opposite state
    does not (the polarity-flip test above still holds through this)."""
    truth = _wiki_truth(
        "A check-in at a full station is refused when the overflow_parking flag is off."
    )
    assert facts_match(_wiki_fact("Check-in at a full station is refused."), truth)
    assert facts_match(
        _wiki_fact("With the overflow parking flag off, a check-in at a full station is refused."),
        truth,
    )
    assert not facts_match(
        _wiki_fact("With the overflow parking flag on, a check-in at a full station is refused."),
        truth,
    )
    assert not _has_negation("The dynamic_pricing flag is off by default.")
    assert _flag_states("enabled by the feature flag") == {"on"}
    assert _flag_states("switched off") == {"off"}
    assert _flag_states("depends on the station") == set()


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


def test_claim_in_the_candidates_own_vocabulary_lets_the_statement_decide():
    """A comparable claim that agrees on the value but names the attribute
    its own way (`severityThresholdToPause` against `min_severity`) no
    longer vetoes: the statement decides. A claim on the same entity and
    value whose attribute is about something else entirely (`retries`)
    still vetoes, and a value conflict on the same attribute always does."""
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

    def fact(attribute: str, value, unit="minute", statement="A member's free minutes are 15."):
        return resolve_fact_entities(
            {
                "statement": statement,
                "entities": ["Farebox", "member-free-minutes"],
                "category": "business-logic",
                "citations": [{"document": "wiki/x"}],
                "claim": {
                    "entity": "member-free-minutes",
                    "attribute": attribute,
                    "value": value,
                    "unit": unit,
                },
            },
            index,
            truth.entities,
        )

    # camelCase with the same words; a different attribute about minutes (the
    # statement decides); an attribute about something else; the same quantity
    # with another value. A related-but-different attribute with another value
    # (`minutesBeforeBilling`, 30) is not a conflict: it may be another quantity
    # of the same rule, and the statement decides.
    assert facts_match(fact("memberFreeMinuteAllowance", 15), truth_fact)
    assert facts_match(fact("minutesBeforeBilling", 15), truth_fact)
    assert not facts_match(fact("retries", 15), truth_fact)
    assert not facts_match(fact("free_minutes", 30), truth_fact)
    assert facts_match(fact("minutesBeforeBilling", 30), truth_fact)


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
