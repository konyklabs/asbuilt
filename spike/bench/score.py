"""Scores a prototype's raw results (from bench/run.py) against ground truth.

CLI: ``uv run python bench/score.py build/results-null.json [--truth truth]
[--json build/score-null.json]``. ``--truth`` defaults to ``truth`` (relative
to the current directory, matching a run from ``spike/``); the fixture root
used to resolve history-step dates for staleness is read from the results
file itself (``results["fixture"]``, written by ``bench/run.py``), not
re-specified here.

Interpretation calls made where the spec leaves a choice (stated, not just
assumed, per the task's ambiguity rule):

* Per-category breakdowns bucket strictly by the *truth* fact's category
  (never the returned fact's), for both explain/search/ask and for
  contradictions where relevant. For explain/search/ask, the per-category
  ``tp`` is a partition of the overall ``tp`` — categories' true-positive
  counts sum to the surface's overall true-positive count — while the
  precision denominator (total returned) is shared across categories, so a
  category's precision is its *contribution* to the surface's precision, not
  an independent ratio. This was chosen because the spec ties categorisation
  to "category of the truth fact" as a single scheme, not two different
  denominators for precision and recall.
* Aggregation across multiple queries on the same surface is by summing raw
  counts (tp, returned, expected, ...) before computing ratios — i.e.
  micro-averaged, not a mean of per-query ratios — so the printed
  denominators are the true totals.
* For ``ask``, "recall = expected facts covered" is evaluated per query by
  summing distinct covered-fact counts; aggregating across queries sums
  those per-query counts rather than re-deduplicating globally (a fact
  "covered" by two different ask queries counts twice), consistent with
  summing raw counts everywhere else.
* ``contradictions`` never has a precision figure (the spec only asks for
  recall and winner agreement), so it always takes the "recall where
  precision is undefined" branch of the headline formula.
* Version disambiguation (when a returned fact could match more than one
  expected truth fact — e.g. two facts share a statement and a code document
  at different versions) is applied in ``match_facts``, used by explain and
  search. It is not applied inside ``score_contradictions`` (a different,
  pairwise matching loop) or ``score_ask_query`` (which matches by cited
  document, not by ``facts_match``, so the ambiguity doesn't arise there).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

import yaml  # noqa: E402

from bench.truth import StaleEntry, TruthFact, load_truth  # noqa: E402

_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")

SURFACES = ("explain", "search", "ask", "contradictions", "stale")


def norm(text: str) -> str:
    text = text.lower()
    text = _PUNCTUATION.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def facts_match(returned: dict[str, Any], truth_fact: TruthFact) -> bool:
    """(a) shared entity, (b) shared cited document, (c) statement similarity >= 0.6."""
    citations = returned.get("citations") or []
    if not citations:
        return False
    returned_entities = set(returned.get("entities") or [])
    if not returned_entities & set(truth_fact.entities):
        return False
    returned_docs = {c["document"] for c in citations}
    truth_docs = {c.document for c in truth_fact.carriers}
    if not returned_docs & truth_docs:
        return False
    ratio = difflib.SequenceMatcher(
        None, norm(returned.get("statement", "")), norm(truth_fact.statement)
    ).ratio()
    return ratio >= 0.6


def _version_matches(returned_version: Any, truth_version: str, commits: dict[str, Any]) -> bool:
    """String-equal, or the truth version is a step id that commits.json maps
    to the SHA the returned citation carries."""
    if returned_version == truth_version:
        return True
    info = commits.get(truth_version)
    return bool(info) and info.get("sha") == returned_version


def _shares_matching_version(
    returned: dict[str, Any], truth_fact: TruthFact, commits: dict[str, Any]
) -> bool:
    """True if some document cited by `returned` is also a carrier of
    `truth_fact`, with the same version (see _version_matches)."""
    citation_versions = {c["document"]: c.get("version") for c in (returned.get("citations") or [])}
    for carrier in truth_fact.carriers:
        returned_version = citation_versions.get(carrier.document)
        if returned_version is not None and carrier.version is not None:
            if _version_matches(returned_version, carrier.version, commits):
                return True
    return False


def match_facts(
    returned_facts: list[dict[str, Any]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any] | None = None,
) -> tuple[list[tuple[dict[str, Any], str]], int]:
    """One-to-one match; each expected fact matches at most once. When a
    returned fact could match more than one still-unmatched expected fact,
    prefer one whose carrier version agrees with the returned citation's
    version (see _shares_matching_version); otherwise take candidates in
    `expected`'s order (greedy first-match). Returns (matches, uncited_count).
    """
    commits = commits or {}
    matched_ids: set[str] = set()
    matches: list[tuple[dict[str, Any], str]] = []
    uncited = 0
    for rf in returned_facts:
        if not rf.get("citations"):
            uncited += 1
            continue
        candidates = [
            fid for fid, tf in expected.items() if fid not in matched_ids and facts_match(rf, tf)
        ]
        if not candidates:
            continue
        preferred = [
            fid for fid in candidates if _shares_matching_version(rf, expected[fid], commits)
        ]
        chosen = preferred[0] if preferred else candidates[0]
        matches.append((rf, chosen))
        matched_ids.add(chosen)
    return matches, uncited


def _by_category_counts(
    matched_ids: set[str], expected: dict[str, TruthFact]
) -> dict[str, dict[str, int]]:
    by_category: dict[str, dict[str, int]] = {}
    for cat in {f.category for f in expected.values()}:
        cat_ids = {fid for fid, f in expected.items() if f.category == cat}
        by_category[cat] = {"tp": len(matched_ids & cat_ids), "expected": len(cat_ids)}
    return by_category


def score_fact_query(
    returned: list[dict[str, Any]],
    expected: dict[str, TruthFact],
    commits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matches, uncited = match_facts(returned, expected, commits)
    matched_ids = {fid for _, fid in matches}
    return {
        "tp": len(matches),
        "returned": len(returned),
        "expected": len(expected),
        "uncited": uncited,
        "by_category": _by_category_counts(matched_ids, expected),
    }


def score_ask_query(answer: dict[str, Any], expected: dict[str, TruthFact]) -> dict[str, Any]:
    sentences = answer.get("sentences") or []
    doc_to_fact_ids: dict[str, set[str]] = {}
    for fid, fact in expected.items():
        for carrier in fact.carriers:
            doc_to_fact_ids.setdefault(carrier.document, set()).add(fid)

    correct_sentences = 0
    covered_ids: set[str] = set()
    for sentence in sentences:
        citations = sentence.get("citations") or []
        if not citations:
            continue
        hit_ids: set[str] = set()
        for citation in citations:
            hit_ids |= doc_to_fact_ids.get(citation["document"], set())
        if hit_ids:
            correct_sentences += 1
            covered_ids |= hit_ids

    return {
        "sentences": len(sentences),
        "correct_sentences": correct_sentences,
        "covered_facts": len(covered_ids),
        "expected": len(expected),
        "by_category": _by_category_counts(covered_ids, expected),
    }


def score_contradictions(
    returned: list[dict[str, Any]],
    expected: dict[str, Any],
    truth_facts: dict[str, TruthFact],
) -> dict[str, Any]:
    matched_ids: set[str] = set()
    winner_checked = 0
    winner_correct = 0
    for rc in returned:
        rc_a, rc_b = rc.get("a"), rc.get("b")
        if rc_a is None or rc_b is None:
            continue
        for xid, xc in expected.items():
            if xid in matched_ids:
                continue
            fa_id, fb_id = xc.facts
            truth_a, truth_b = truth_facts.get(fa_id), truth_facts.get(fb_id)
            if truth_a is None or truth_b is None:
                continue
            order1 = facts_match(rc_a, truth_a) and facts_match(rc_b, truth_b)
            order2 = facts_match(rc_a, truth_b) and facts_match(rc_b, truth_a)
            if not (order1 or order2):
                continue
            matched_ids.add(xid)
            if xc.winner is not None:
                winner_checked += 1
                expected_winner = truth_facts.get(xc.winner)
                returned_winner = rc.get("winner")
                if (
                    expected_winner is not None
                    and returned_winner is not None
                    and facts_match(returned_winner, expected_winner)
                ):
                    winner_correct += 1
            break
    return {
        "matched": len(matched_ids),
        "expected": len(expected),
        "winner_checked": winner_checked,
        "winner_correct": winner_correct,
    }


def _step_dates(fixture_root: Path) -> dict[str, datetime]:
    steps_path = fixture_root / "system" / "history" / "steps.yaml"
    if not steps_path.is_file():
        return {}
    raw = yaml.safe_load(steps_path.read_text()) or []
    return {r["id"]: datetime.fromisoformat(r["date"]) for r in raw}


def _comparable(a: datetime, b: datetime) -> tuple[datetime, datetime]:
    """Drop tzinfo from both sides if only one is aware, so a date-only
    ``since`` (naive) can still be compared against an offset-aware step
    date; mixed naive/aware comparison otherwise raises TypeError."""
    if (a.tzinfo is None) != (b.tzinfo is None):
        return a.replace(tzinfo=None), b.replace(tzinfo=None)
    return a, b


def score_stale(
    returned: list[dict[str, Any]],
    since: datetime,
    stale_entries: dict[str, StaleEntry],
    step_dates: dict[str, datetime],
) -> dict[str, Any]:
    expected: dict[str, StaleEntry] = {}
    for sid, entry in stale_entries.items():
        step_date = step_dates.get(entry.changed_by)
        if step_date is None:
            continue
        step_date_cmp, since_cmp = _comparable(step_date, since)
        if step_date_cmp > since_cmp:
            expected[sid] = entry
    matched_ids: set[str] = set()
    tp = 0
    for rf in returned:
        citations = rf.get("citations") or []
        if not citations:
            continue
        cited_docs = {c["document"] for c in citations}
        for sid, entry in expected.items():
            if sid in matched_ids:
                continue
            if entry.document in cited_docs:
                matched_ids.add(sid)
                tp += 1
                break
    return {"tp": tp, "returned": len(returned), "expected": len(expected)}


def _merge(outcomes: list[dict[str, Any]], numeric_keys: tuple[str, ...]) -> dict[str, Any]:
    merged: dict[str, Any] = dict.fromkeys(numeric_keys, 0)
    by_category: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        for key in numeric_keys:
            merged[key] += outcome.get(key, 0)
        for cat, counts in outcome.get("by_category", {}).items():
            bucket = by_category.setdefault(cat, {"tp": 0, "expected": 0})
            bucket["tp"] += counts.get("tp", 0)
            bucket["expected"] += counts.get("expected", 0)
    merged["by_category"] = by_category
    return merged


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def f1_score(precision: float | None, recall: float | None) -> float | None:
    if precision is None and recall is None:
        return None
    if precision is None:
        return recall
    if recall is None:
        return precision
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def headline_contribution(precision: float | None, recall: float | None) -> float:
    """weight * F1, or weight * recall when precision is undefined (spec)."""
    if precision is None:
        return recall or 0.0
    score = f1_score(precision, recall)
    return score or 0.0


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def latency_percentiles(queries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_surface: dict[str, list[float]] = {}
    for q in queries:
        by_surface.setdefault(q["surface"], []).append(q["latency_ms"])
    out: dict[str, dict[str, float]] = {}
    for surface, values in by_surface.items():
        values_sorted = sorted(values)
        out[surface] = {
            "p50_ms": _percentile(values_sorted, 50),
            "p95_ms": _percentile(values_sorted, 95),
            "n": len(values_sorted),
        }
    return out


def score(
    results: dict[str, Any], truth_root: Path, commits: dict[str, Any] | None = None
) -> dict[str, Any]:
    truth = load_truth(truth_root)
    fixture_root = Path(results["fixture"])
    step_dates = _step_dates(fixture_root)
    weights = results.get("weights", {})
    commits = commits or {}

    per_query: dict[str, list[dict[str, Any]]] = {s: [] for s in SURFACES}
    for q in results["queries"]:
        surface = q["surface"]
        params = q.get("params", {})
        if surface == "explain":
            entity = params["entity"]
            expected = {fid: f for fid, f in truth.facts.items() if entity in f.entities}
            per_query["explain"].append(score_fact_query(q["result"], expected, commits))
        elif surface == "search":
            expects = params.get("expects") or []
            expected = {fid: truth.facts[fid] for fid in expects if fid in truth.facts}
            per_query["search"].append(score_fact_query(q["result"], expected, commits))
        elif surface == "ask":
            expects = params.get("expects") or []
            expected = {fid: truth.facts[fid] for fid in expects if fid in truth.facts}
            per_query["ask"].append(score_ask_query(q["result"], expected))
        elif surface == "contradictions":
            entity = params.get("entity")
            if entity:
                expected_x = {
                    xid: xc
                    for xid, xc in truth.contradictions.items()
                    if entity
                    in (truth.facts[xc.facts[0]].entities + truth.facts[xc.facts[1]].entities)
                }
            else:
                expected_x = dict(truth.contradictions)
            per_query["contradictions"].append(
                score_contradictions(q["result"], expected_x, truth.facts)
            )
        elif surface == "stale":
            since = datetime.fromisoformat(params["since"])
            per_query["stale"].append(score_stale(q["result"], since, truth.stale, step_dates))
        else:
            raise ValueError(f"unknown surface {surface!r} in results")

    surfaces: dict[str, Any] = {}

    for name in ("explain", "search"):
        m = _merge(per_query[name], ("tp", "returned", "expected", "uncited"))
        precision, recall = _ratio(m["tp"], m["returned"]), _ratio(m["tp"], m["expected"])
        surfaces[name] = {
            **m,
            "precision": precision,
            "recall": recall,
            "f1": f1_score(precision, recall),
        }

    ask_keys = ("sentences", "correct_sentences", "covered_facts", "expected")
    m = _merge(per_query["ask"], ask_keys)
    precision = _ratio(m["correct_sentences"], m["sentences"])
    recall = _ratio(m["covered_facts"], m["expected"])
    surfaces["ask"] = {
        **m,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
    }

    contradiction_keys = ("matched", "expected", "winner_checked", "winner_correct")
    m = _merge(per_query["contradictions"], contradiction_keys)
    recall = _ratio(m["matched"], m["expected"])
    winner_accuracy = _ratio(m["winner_correct"], m["winner_checked"])
    surfaces["contradictions"] = {
        **m,
        "precision": None,
        "recall": recall,
        "f1": f1_score(None, recall),
        "winner_accuracy": winner_accuracy,
    }

    m = _merge(per_query["stale"], ("tp", "returned", "expected"))
    precision, recall = _ratio(m["tp"], m["returned"]), _ratio(m["tp"], m["expected"])
    surfaces["stale"] = {
        **m,
        "precision": precision,
        "recall": recall,
        "f1": f1_score(precision, recall),
    }

    headline = sum(
        weights.get(name, 0)
        * headline_contribution(surfaces[name]["precision"], surfaces[name]["recall"])
        for name in SURFACES
    )

    return {
        "prototype": results.get("prototype"),
        "ingest": results.get("ingest"),
        "weights": weights,
        "surfaces": surfaces,
        "latency": latency_percentiles(results["queries"]),
        "headline": headline,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def print_report(report: dict[str, Any]) -> None:
    ingest = report.get("ingest") or {}
    print(f"prototype: {report.get('prototype')}")
    print("ingest:")
    print(
        f"  seconds={_fmt(ingest.get('seconds'))} input_tokens={_fmt(ingest.get('input_tokens'))} "
        f"output_tokens={_fmt(ingest.get('output_tokens'))} dollars={_fmt(ingest.get('dollars'))} "
        f"services={ingest.get('services')} documents={_fmt(ingest.get('documents'))}"
    )
    print()
    print(f"{'surface':<15}{'precision':<12}{'recall':<12}{'f1':<10}denominators")
    for name in SURFACES:
        s = report["surfaces"][name]
        if name == "ask":
            denom = (
                f"tp={s['correct_sentences']}/{s['sentences']} "
                f"covered={s['covered_facts']}/{s['expected']}"
            )
        elif name == "contradictions":
            denom = (
                f"matched={s['matched']}/{s['expected']} "
                f"winner={s['winner_correct']}/{s['winner_checked']} "
                f"(winner_accuracy={_fmt(s['winner_accuracy'])})"
            )
        elif name in ("explain", "search"):
            denom = (
                f"tp={s['tp']}/{s['returned']} vs expected={s['expected']} uncited={s['uncited']}"
            )
        else:
            denom = f"tp={s['tp']}/{s['returned']} vs expected={s['expected']}"
        line = f"{name:<15}{_fmt(s['precision']):<12}{_fmt(s['recall']):<12}{_fmt(s['f1']):<10}"
        print(line + denom)
        for cat, counts in sorted(s.get("by_category", {}).items()):
            print(f"    {cat:<20} tp={counts['tp']} expected={counts['expected']}")

    print()
    print(f"{'surface':<15}{'p50 (ms)':<12}{'p95 (ms)':<12}n")
    for name, lat in report["latency"].items():
        print(f"{name:<15}{lat['p50_ms']:<12.3f}{lat['p95_ms']:<12.3f}{lat['n']}")

    print()
    print(
        "headline (weighted sum of F1 / recall-where-precision-undefined): "
        f"{report['headline']:.4f}"
    )
    print(f"weights: {report['weights']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", help="results JSON file from bench/run.py")
    parser.add_argument("--truth", default="truth", help="truth directory (default: truth)")
    parser.add_argument("--json", default=None, help="also write the score report as JSON")
    parser.add_argument(
        "--commits",
        default="build/commits.json",
        help=(
            "commits.json from bench/build.py, for step->SHA lookups when a "
            "returned code citation carries a SHA rather than a step id "
            "(default: build/commits.json; missing file is fine, disambiguation "
            "then falls back to plain string comparison)"
        ),
    )
    args = parser.parse_args(argv)

    results_path = Path(args.results)
    results = json.loads(results_path.read_text())
    truth_root = Path(args.truth)

    commits_path = Path(args.commits)
    commits = json.loads(commits_path.read_text()) if commits_path.is_file() else {}

    report = score(results, truth_root, commits)
    print_report(report)

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
