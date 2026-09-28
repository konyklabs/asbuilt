from __future__ import annotations

from bench.run import run
from bench.score import facts_match, match_facts, score
from bench.truth import Carrier, TruthFact, load_facts
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
    F-001, which shares its statement and code document), one search miss."""
    correct = {
        "statement": "A member's free minutes are 15.",
        "category": "business-logic",
        "entities": ["E-farebox", "E-rule-member-free-minutes"],
        "tier": "executed",
        "citations": [{"document": "code/farebox/pricing.py", "version": "c4"}],
        "valid_from": None,
        "valid_to": None,
        "confidence": None,
    }
    wrong = {
        "statement": "Totally unrelated statement about something else.",
        "category": "operations",
        "entities": ["E-farebox"],
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
                "params": {"entity": "E-rule-member-free-minutes"},
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
                "params": {"entity": "E-rule-member-free-minutes"},
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
