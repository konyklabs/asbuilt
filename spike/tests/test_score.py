from __future__ import annotations

import difflib
from datetime import datetime

from bench.run import run
from bench.score import facts_match, match_facts, norm, score, score_contradictions, score_stale
from bench.truth import Carrier, StaleEntry, TruthContradiction, TruthFact, load_facts
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
                "params": {"entity": "E-x"},
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
