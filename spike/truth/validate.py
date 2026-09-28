"""Check the spike's ground truth, query mix and authoring plan against each other.

Run from anywhere:

    uv run --with pyyaml python spike/truth/validate.py

Reads truth/{entities,facts,contradictions,stale,aliases,planted-runs,PLAN}.yaml,
truth/executed-audit.md, system/history/steps.yaml and queries/mix.yaml. Prints
the counts and every failed check, and exits 1 if any check fails.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

SPIKE = Path(__file__).resolve().parent.parent
CATEGORIES = ("business-logic", "technical-implementation", "operations", "history")
TIERS = ("executed", "code", "documented")
TIER_RANK = {"executed": 3, "code": 2, "documented": 1}
KINDS = ("wiki-vs-test", "ticket-vs-code", "page-vs-page", "doc-vs-code", "run-vs-code")
DOC_KINDS = ("wiki", "ticket", "doc", "pull")
SURFACES = ("explain", "search", "ask", "contradictions", "stale")

# Target counts from the brief; the ranges are the tolerance for "about".
EXPECT_TOTAL = (110, 130)
EXPECT_CATEGORY = {
    "business-logic": (40, 50),
    "technical-implementation": (35, 45),
    "operations": (20, 30),
    "history": (8, 12),
}
EXPECT_TIER = {"executed": (25, 31), "code": (36, 44), "documented": (45, 60)}
EXACT = {"contradictions": 21, "stale": 10, "pr_only": 5, "wiki": 40, "tickets": 80, "docs": 10}
MIX_COUNTS = {"explain": 25, "search": 17, "ask": 13, "contradictions": 4, "stale": 3}
EXPLAIN_BY_ALIAS, IMPACT_QUERIES = 5, 5
AUDITED = 28
UNITS = ("usd", "minute", "day", "hour", "second", "percent", "count", "clock", None)
NUMBER_WORDS = {
    w: n
    for n, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve".split()
    )
}
NUMERIC_WORD = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b", re.I)
EVERY_UNIT = re.compile(r"\bevery (minute|hour|day|week|month)\b")

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load(rel: str):
    return yaml.safe_load((SPIKE / rel).read_text())


def when(s) -> datetime:
    return datetime.fromisoformat(str(s))


def is_test(path: str) -> bool:
    return path.startswith("tests/") or path.startswith("dispatch/test/")


entities = {e["id"]: e for e in load("truth/entities.yaml")}
steps_list = load("system/history/steps.yaml")
STEPS = [s["id"] for s in steps_list]
STEP = {s["id"]: s for s in steps_list}
STEP_DATE = {s["id"]: when(s["date"]) for s in steps_list}
facts_list = load("truth/facts.yaml")
contradictions = load("truth/contradictions.yaml")
stale = load("truth/stale.yaml")
mix = load("queries/mix.yaml")
plan = load("truth/PLAN.yaml")
aliases = load("truth/aliases.yaml")
planted = load("truth/planted-runs.yaml")
audit_text = (SPIKE / "truth/executed-audit.md").read_text()
plan_tests = {t["id"]: t for t in plan.get("tests", [])}
plan_runs = {r["id"]: r for r in plan.get("runs", [])}
RUN_ID = re.compile(r"run/(pytest|vitest)-(c\d+)(-rerun)?")


def run_step(doc: str) -> str:
    m = RUN_ID.fullmatch(doc)
    if not m:
        raise ValueError(f"not a run document: {doc}")
    return m.group(2)


def outcome_steps(test: dict, field: str) -> list[str]:
    return list(test.get(field, []))


def steps_between(start: str | None, end: str | None) -> list[str]:
    i = STEPS.index(start) if start else 0
    j = STEPS.index(end) if end else len(STEPS)
    return STEPS[i:j]


# ---------------------------------------------------------------- facts
facts: dict[str, dict] = {}
for f in facts_list:
    fid = f.get("id", "?")
    if not re.fullmatch(r"F-\d{3}", fid):
        fail(f"{fid}: id is not F-NNN")
    if fid in facts:
        fail(f"{fid}: duplicate id")
    facts[fid] = f
    s = f.get("statement", "")
    if not s or "\n" in s or not s.endswith("."):
        fail(f"{fid}: statement must be one line ending in a period")
    if re.search(r"[.!?]\s+[A-Z]", s[:-1]):
        fail(f"{fid}: statement looks like more than one sentence")
    for m in re.finditer(r"\$(\d+(?:\.\d+)?)", s):
        if not re.fullmatch(r"\d+\.\d{2}", m.group(1)):
            fail(f"{fid}: money must have two decimals: ${m.group(1)}")
    if f.get("category") not in CATEGORIES:
        fail(f"{fid}: bad category {f.get('category')}")
    if f.get("tier") not in TIERS:
        fail(f"{fid}: bad tier {f.get('tier')}")
    ents = f.get("entities") or []
    if not ents:
        fail(f"{fid}: no entities")
    if len(set(ents)) != len(ents):
        fail(f"{fid}: duplicate entity")
    for e in ents:
        if e not in entities:
            fail(f"{fid}: unknown entity {e}")
    vf, vt = f.get("valid_from"), f.get("valid_to")
    for v in (vf, vt):
        if v is not None and v not in STEPS:
            fail(f"{fid}: unknown step {v}")
    if vf == "c1":
        fail(f"{fid}: omit valid_from when true from c1")
    if vf in STEPS and vt in STEPS and STEPS.index(vf) >= STEPS.index(vt):
        fail(f"{fid}: valid_from {vf} is not before valid_to {vt}")
    carriers = f.get("carriers") or []
    if not carriers:
        fail(f"{fid}: no carriers")
    seen = set()
    for c in carriers:
        key = (c.get("document"), c.get("location"))
        if key in seen:
            fail(f"{fid}: carrier listed twice: {key}")
        seen.add(key)
        kind = str(c.get("document", "")).split("/", 1)[0]
        if kind not in ("code", "run", *DOC_KINDS):
            fail(f"{fid}: unknown document kind in {c.get('document')}")
        if not c.get("location"):
            fail(f"{fid}: carrier {c.get('document')} has no location")

# tier rules
for fid, f in facts.items():
    cs = f["carriers"]
    kinds = [c["document"].split("/", 1)[0] for c in cs]
    code_src = [
        c for c in cs if c["document"].startswith("code/") and not is_test(c["document"][5:])
    ]
    code_tests = [c for c in cs if c["document"].startswith("code/") and is_test(c["document"][5:])]
    runs = [c for c in cs if c["document"].startswith("run/")]
    tier = f["tier"]
    validity = steps_between(f.get("valid_from"), f.get("valid_to"))
    if tier == "executed":
        if not (runs and code_tests and code_src):
            fail(f"{fid}: executed needs a run, a test and the code it exercises")
        test_locs = {c["location"] for c in code_tests}
        for r in runs:
            if r["location"] not in test_locs:
                fail(f"{fid}: run {r['document']} location is not one of the fact's tests")
            if not RUN_ID.fullmatch(r["document"]):
                fail(f"{fid}: {r['document']} is not a run document id")
                continue
            if r["document"].endswith("-rerun"):
                fail(f"{fid}: {r['document']} is a rerun; cite attempt 1 of a conclusive step")
            step = run_step(r["document"])
            if step not in validity:
                fail(f"{fid}: run {r['document']} is outside the fact's validity {validity}")
            fw = r["document"].split("/")[1].split("-", 1)[0]
            test_doc = next(c["document"] for c in code_tests if c["location"] == r["location"])
            if (fw == "vitest") != test_doc.endswith(".ts"):
                fail(f"{fid}: run framework {fw} does not match test {test_doc}")
        for loc in test_locs:
            pt = plan_tests.get(loc)
            if not pt:
                continue  # reported with the PLAN resolution below
            want = set(validity) & set(pt["passes_in"])
            got = {run_step(r["document"]) for r in runs if r["location"] == loc}
            if got != want:
                fail(
                    f"{fid}: runs of {loc} at {sorted(got)}, "
                    f"but it passes within the validity at {sorted(want)}"
                )
            if not got:
                fail(f"{fid}: executed, but {loc} never passes within the validity")
    elif tier == "code":
        if not code_src:
            fail(f"{fid}: code tier needs a code/ carrier")
        demoted = f.get("demoted_by")
        if runs and not demoted:
            fail(f"{fid}: has a run and no demoted_by, so its tier should be executed")
        if demoted:
            dr = plan_runs.get(demoted.get("document", ""))
            if not dr:
                fail(f"{fid}: demoted_by {demoted.get('document')} is not in PLAN runs")
            elif demoted.get("location") not in dr.get("failed", []):
                fail(f"{fid}: demoted_by run does not list {demoted.get('location')} as failed")
            else:
                later = STEPS.index(dr["step"])
                if any(STEPS.index(run_step(r["document"])) >= later for r in runs):
                    fail(f"{fid}: a passing run is cited at or after the demoting run")
                if demoted.get("location") not in {c["location"] for c in code_tests}:
                    fail(f"{fid}: demoted_by names a test that is not one of its carriers")
        elif code_tests:
            for c in code_tests:
                pt = plan_tests.get(c["location"])
                if pt and set(pt["passes_in"]) & set(validity):
                    fail(
                        f"{fid}: code tier, but its test {c['location']} passes within the validity"
                    )
    elif f.get("demoted_by"):
        fail(f"{fid}: demoted_by is only valid on a code-tier fact")
    elif tier == "documented":
        bad = [k for k in kinds if k not in DOC_KINDS]
        if bad:
            fail(f"{fid}: documented fact carries {bad}")
    first = cs[0]["document"] if cs else ""
    if tier in ("executed", "code") and not first.startswith("code/"):
        fail(f"{fid}: primary carrier of a {tier} fact should be code, got {first}")
    for c in code_src + code_tests:
        if c.get("version") not in STEPS:
            fail(
                f"{fid}: code carrier {c['document']} has version {c.get('version')!r}, not a step"
            )
    for c in code_src:
        if c.get("version") != (f.get("valid_from") or "c1"):
            fail(f"{fid}: code carrier {c['document']} version {c.get('version')} != valid_from")

pr_only = [
    fid for fid, f in facts.items() if all(c["document"].startswith("pull/") for c in f["carriers"])
]
for fid in pr_only:
    if len(facts[fid]["carriers"]) != 1:
        fail(f"{fid}: a PR-only fact must have exactly one carrier")
    if facts[fid]["tier"] != "documented":
        fail(f"{fid}: a PR-only fact must be documented")

# ---------------------------------------------------------------- plan index
wiki = {p["slug"]: p for p in plan.get("wiki", [])}
docs = {d["id"]: d for d in plan.get("docs", [])}
tickets = {t["key"]: t for t in plan.get("tickets", [])}
pulls = {p["number"]: p for p in plan.get("pulls", [])}
code = {c["path"]: c for c in plan.get("code", [])}
tests = {(t["document"], t["id"]): t for t in plan.get("tests", [])}
runs_plan = {r["id"]: r for r in plan.get("runs", [])}

for name, coll, key in (
    ("wiki", plan.get("wiki", []), "slug"),
    ("docs", plan.get("docs", []), "id"),
    ("tickets", plan.get("tickets", []), "key"),
    ("pulls", plan.get("pulls", []), "number"),
    ("code", plan.get("code", []), "path"),
):
    ids = [x[key] for x in coll]
    for k, n in Counter(ids).items():
        if n > 1:
            fail(f"PLAN {name}: {k} listed {n} times")


def fact_ids(entries) -> list[str]:
    return [e["id"] for e in entries or []]


# every (document, location, fact) the PLAN promises
plan_triples: set[tuple[str, str, str]] = set()
doc_dates: dict[tuple[str, str], datetime] = {}
for slug, p in wiki.items():
    for a in p.get("anchors", []):
        for fid in fact_ids(a["facts"]):
            plan_triples.add((f"wiki/{slug}", a["anchor"], fid))
        doc_dates[(f"wiki/{slug}", a["anchor"])] = when(p["lastmodified"])
for did, d in docs.items():
    for a in d.get("anchors", []):
        for fid in fact_ids(a["facts"]):
            plan_triples.add((f"doc/{did}", a["anchor"], fid))
        doc_dates[(f"doc/{did}", a["anchor"])] = when(d["modifiedTime"])
for key, t in tickets.items():
    for fid in fact_ids(t["description"]["facts"]):
        plan_triples.add((f"ticket/{key}", "description", fid))
    doc_dates[(f"ticket/{key}", "description")] = when(t["created"])
    for c in t.get("comments", []):
        for fid in fact_ids(c["facts"]):
            plan_triples.add((f"ticket/{key}", c["id"], fid))
        doc_dates[(f"ticket/{key}", c["id"])] = when(c["created"])
for n, p in pulls.items():
    for fid in fact_ids(p["body"]["facts"]):
        plan_triples.add((f"pull/{n}", "body", fid))
    doc_dates[(f"pull/{n}", "body")] = when(p["opened"])
    for c in p.get("comments", []):
        for fid in fact_ids(c["facts"]):
            plan_triples.add((f"pull/{n}", c["id"], fid))
        doc_dates[(f"pull/{n}", c["id"])] = when(c["created"])
for path, c in code.items():
    names = [s["name"] for s in c.get("symbols", [])]
    for k, n in Counter(names).items():
        if n > 1:
            fail(f"PLAN code {path}: symbol {k} listed twice")
    if c.get("added_in") not in STEPS:
        fail(f"PLAN code {path}: added_in {c.get('added_in')} is not a step")
    for s in c.get("symbols", []):
        for e in s.get("facts", []):
            plan_triples.add((f"code/{path}", s["name"], e["fact"]))
for (doc, loc), t in tests.items():
    for e in t.get("asserts", []):
        plan_triples.add((doc, loc, e["fact"]))
for rid, r in runs_plan.items():
    for loc in r.get("passes", []):
        for (_, tloc), t in tests.items():
            if tloc == loc:
                for e in t["asserts"]:
                    if r["step"] in e["steps"]:
                        plan_triples.add((rid, loc, e["fact"]))

fact_triples: set[tuple[str, str, str]] = set()
for fid, f in facts.items():
    for c in f["carriers"]:
        doc, loc = c["document"], c["location"]
        fact_triples.add((doc, loc, fid))
        kind, rest = doc.split("/", 1)
        if kind == "wiki":
            p = wiki.get(rest)
            if not p:
                fail(f"{fid}: wiki/{rest} is not in PLAN")
            elif c.get("version") != p["version"]:
                fail(f"{fid}: wiki/{rest} version {c.get('version')} != PLAN {p['version']}")
        elif kind == "doc":
            d = docs.get(rest)
            if not d:
                fail(f"{fid}: doc/{rest} is not in PLAN")
            elif c.get("version") != d["headRevisionId"]:
                fail(f"{fid}: doc/{rest} version {c.get('version')} != PLAN {d['headRevisionId']}")
        elif kind == "ticket":
            if rest not in tickets:
                fail(f"{fid}: ticket/{rest} is not in PLAN")
        elif kind == "pull":
            if int(rest) not in pulls:
                fail(f"{fid}: pull/{rest} is not in PLAN")
        elif kind == "code":
            if is_test(rest):
                t = tests.get((doc, loc))
                if not t:
                    fail(f"{fid}: test {loc} in {doc} is not in PLAN tests")
                elif c.get("version") not in [
                    s
                    for fld in ("passes_in", "fails_in", "skipped_in", "flaky_in")
                    for s in t.get(fld, [])
                ]:
                    fail(
                        f"{fid}: test {loc} carrier version {c.get('version')} "
                        "is not a step the test exists at"
                    )
            else:
                m = code.get(rest)
                if not m:
                    fail(f"{fid}: code/{rest} is not in PLAN code")
                    continue
                sym = next((s for s in m["symbols"] if s["name"] == loc), None)
                if not sym:
                    fail(f"{fid}: symbol {loc} is not declared in PLAN code/{rest}")
                    continue
                entry = next((e for e in sym.get("facts", []) if e["fact"] == fid), None)
                if not entry:
                    fail(f"{fid}: PLAN code/{rest}:{loc} does not list the fact")
                else:
                    want = steps_between(c.get("version"), f.get("valid_to"))
                    if entry["steps"] != want:
                        fail(f"{fid}: PLAN code/{rest}:{loc} steps {entry['steps']} != {want}")
                if STEPS.index(m["added_in"]) > STEPS.index(c.get("version", "c1")):
                    fail(
                        f"{fid}: code/{rest} is added in {m['added_in']}, "
                        f"after carrier version {c.get('version')}"
                    )
        elif kind == "run":
            r = runs_plan.get(doc)
            if not r:
                fail(f"{fid}: {doc} is not in PLAN runs")
            elif loc not in r["passes"]:
                fail(f"{fid}: {doc} does not list {loc} as passing")

for t in sorted(fact_triples - plan_triples):
    fail(f"carrier not in PLAN: {t}")
for t in sorted(plan_triples - fact_triples):
    fail(f"PLAN promises a carrier facts.yaml lacks: {t}")

# plan-level checks
for slug, p in wiki.items():
    if not any(a["facts"] for a in p.get("anchors", [])):
        fail(f"PLAN wiki/{slug} carries no fact")
    when(p["lastmodified"])
    if not isinstance(p.get("version"), int):
        fail(f"PLAN wiki/{slug} version is not an integer")
    for a in p.get("anchors", []):
        if not re.fullmatch(r"#[a-z0-9-]+", a["anchor"]):
            fail(f"PLAN wiki/{slug} anchor {a['anchor']} is not #kebab-case")
for did, d in docs.items():
    if not any(a["facts"] for a in d.get("anchors", [])):
        fail(f"PLAN doc/{did} carries no fact")
prev_created = None
for key in sorted(tickets, key=lambda k: int(k.split("-")[1])):
    t = tickets[key]
    if not re.fullmatch(r"GW-\d+", key):
        fail(f"PLAN ticket {key}: key is not GW-<n>")
    created, updated = when(t["created"]), when(t["updated"])
    if updated < created:
        fail(f"PLAN ticket {key}: updated before created")
    if prev_created and created < prev_created:
        fail(f"PLAN ticket {key}: created before the previous key")
    prev_created = created
    carries = bool(t["description"]["facts"]) or any(c["facts"] for c in t.get("comments", []))
    if t.get("noise") and carries:
        fail(f"PLAN ticket {key}: marked noise but carries facts")
    if not t.get("noise") and not carries:
        fail(f"PLAN ticket {key}: not noise but carries no fact")
    for c in t.get("comments", []):
        if when(c["created"]) < created:
            fail(f"PLAN ticket {key} {c['id']}: comment before the ticket")
for n, p in pulls.items():
    ms = p.get("merged_step")
    if (p["state"] == "merged") != (ms is not None):
        fail(f"PLAN pull/{n}: state {p['state']} disagrees with merged_step {ms}")
    if ms is not None:
        if ms not in STEPS:
            fail(f"PLAN pull/{n}: merged_step {ms} is not a step")
        elif STEP[ms].get("pull") != n:
            fail(
                f"PLAN pull/{n}: merged at {ms}, "
                f"but steps.yaml gives that step pull {STEP[ms].get('pull')}"
            )
        elif when(p["closed"]) != STEP_DATE[ms]:
            fail(f"PLAN pull/{n}: merge time {p['closed']} != step {ms} date")
    carries = bool(p["body"]["facts"]) or any(c["facts"] for c in p.get("comments", []))
    if not p.get("noise") and not carries:
        fail(f"PLAN pull/{n}: not noise but carries no fact")
for s in steps_list:
    if s.get("pull") is not None and s["pull"] not in pulls:
        fail(f"steps.yaml {s['id']}: pull {s['pull']} is not in PLAN")
for n in (9, 14, 19, 21):
    if n not in pulls:
        fail(f"PLAN: pull/{n} is required")
for fw in ("pytest", "vitest"):
    for st in STEPS:
        if f"run/{fw}-{st}" not in runs_plan:
            fail(f"PLAN: run/{fw}-{st} missing")
for (doc, loc), t in tests.items():
    path = doc[5:]
    if not is_test(path):
        fail(f"PLAN test {doc} is not under tests/ or dispatch/test/")
    if path.endswith(".py") and not loc.startswith(f"{path}::"):
        fail(f"PLAN test {loc}: node id does not start with its file")
    fields = ("passes_in", "fails_in", "skipped_in", "flaky_in")
    seen_steps = [s for fld in fields for s in outcome_steps(t, fld)]
    for s, n in Counter(seen_steps).items():
        if n > 1:
            fail(f"PLAN test {loc}: step {s} has more than one outcome")
    for s in seen_steps:
        if s not in STEPS:
            fail(f"PLAN test {loc}: unknown step {s}")
    for r in runs_plan.values():
        if (r["framework"] == "vitest") != path.endswith(".ts"):
            continue
        s, attempt = r["step"], r.get("attempt", 1)
        passes, failed, skipped = (
            loc in r.get("passes", []),
            loc in r.get("failed", []),
            loc in r.get("skipped", []),
        )
        if attempt == 1:
            want = (
                s in t["passes_in"],
                s in outcome_steps(t, "fails_in") + outcome_steps(t, "flaky_in"),
                s in outcome_steps(t, "skipped_in"),
            )
        else:
            want = (s in outcome_steps(t, "flaky_in"), s in outcome_steps(t, "fails_in"), False)
        if (passes, failed, skipped) != want:
            fail(
                f"PLAN run {r['id']} and test {loc} disagree: got pass/fail/skip "
                f"{(passes, failed, skipped)}, want {want}"
            )
for rid, r in runs_plan.items():
    m = RUN_ID.fullmatch(rid)
    if not m or m.group(1) != r.get("framework") or m.group(2) != r.get("step"):
        fail(f"PLAN run {rid}: id disagrees with its framework or step")
    elif m.group(3):
        first = runs_plan.get(rid.removesuffix("-rerun"))
        if r.get("attempt") != 2 or r.get("reruns") != rid.removesuffix("-rerun") or not first:
            fail(f"PLAN run {rid}: a rerun needs attempt 2 and the attempt-1 run it reruns")
        elif set(r.get("passes", [])) | set(r.get("failed", [])) != set(first.get("failed", [])):
            fail(f"PLAN run {rid}: reruns exactly the tests attempt 1 failed")
    elif r.get("failed") and f"{rid}-rerun" not in runs_plan:
        fail(f"PLAN run {rid}: has failures but no rerun")
py_modules = [p for p in code if p.endswith(".py") and p.split("/")[0] in ("dockyard", "farebox")]
ts_files = [p for p in code if p.endswith(".ts") and p.startswith("dispatch/src/")]
if not 45 <= len(py_modules) <= 60:
    fail(f"PLAN code: {len(py_modules)} Python modules, expected about 50")
if not 12 <= len(ts_files) <= 20:
    fail(f"PLAN code: {len(ts_files)} TypeScript files, expected about 15")

# PR-only facts appear in exactly one place, which is a pull
for fid in pr_only:
    where = [t for t in plan_triples if t[2] == fid]
    if len(where) != 1 or not where[0][0].startswith("pull/"):
        fail(f"{fid}: PR-only fact appears in {where}")


def carrier_date(fid: str, c: dict) -> datetime:
    doc = c["document"]
    kind = doc.split("/", 1)[0]
    if kind == "code":
        return STEP_DATE[c["version"]]
    if kind == "run":
        return STEP_DATE[run_step(doc)]
    return doc_dates[(doc, c["location"])]


def recency(fid: str) -> datetime:
    return max(carrier_date(fid, c) for c in facts[fid]["carriers"])


# dates of documents against the facts they state
stale_pairs = {(s["document"], s["states"]) for s in stale}
for fid, f in facts.items():
    for c in f["carriers"]:
        kind = c["document"].split("/", 1)[0]
        if kind not in ("wiki", "doc"):
            continue
        d = doc_dates[(c["document"], c["location"])]
        vf, vt = f.get("valid_from"), f.get("valid_to")
        if vf and d < STEP_DATE[vf]:
            fail(
                f"{fid}: {c['document']} ({d.date()}) states it before "
                f"{vf} ({STEP_DATE[vf].date()}) made it true"
            )
        if vt:
            if d >= STEP_DATE[vt]:
                fail(f"{fid}: {c['document']} ({d.date()}) states it after {vt} ended it")
            if (c["document"], fid) not in stale_pairs:
                fail(
                    f"{fid}: {c['document']} still states a value {vt} changed, "
                    "but is not in stale.yaml"
                )


# ---------------------------------------------------------------- claims
def is_numeric(statement: str) -> bool:
    return bool(
        re.search(r"\d", statement)
        or NUMERIC_WORD.search(statement)
        or EVERY_UNIT.search(statement)
    )


def value_in_statement(value, unit, statement: str) -> bool:
    if isinstance(value, str):
        return value in statement
    numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", statement)}
    numbers |= {float(NUMBER_WORDS[w.lower()]) for w in NUMERIC_WORD.findall(statement)}
    if float(value) in numbers:
        return True
    every = EVERY_UNIT.search(statement)
    return float(value) == 1 and every is not None and every.group(1) == unit


claims = {fid: f["claim"] for fid, f in facts.items() if "claim" in f}
for fid, f in facts.items():
    c = f.get("claim")
    if is_numeric(f["statement"]) != (c is not None):
        why = "numeric statement has no claim" if c is None else "claim on a non-numeric statement"
        fail(f"{fid}: {why}")
    if c is None:
        continue
    if set(c) != {"entity", "attribute", "value", "unit"}:
        fail(f"{fid}: claim needs exactly entity, attribute, value and unit")
        continue
    if c["entity"] not in f["entities"]:
        fail(f"{fid}: claim entity {c['entity']} is not one of the fact's entities")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(c["attribute"])):
        fail(f"{fid}: claim attribute {c['attribute']!r} is not snake_case")
    if c["unit"] not in UNITS:
        fail(f"{fid}: claim unit {c['unit']!r} is not one of {UNITS}")
    v = c["value"]
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        fail(f"{fid}: claim value {v!r} is not a number or a string")
    elif c["unit"] == "clock" and not (isinstance(v, str) and re.fullmatch(r"\d{2}:\d{2}", v)):
        fail(f"{fid}: a clock claim is an HH:MM string, got {v!r}")
    elif not value_in_statement(v, c["unit"], f["statement"]):
        fail(f"{fid}: claim value {v!r} does not appear in the statement")


def check_claim_pair(where: str, a: str, b: str) -> None:
    ca, cb = claims.get(a), claims.get(b)
    if ca is None or cb is None:
        return
    if (ca["entity"], ca["attribute"]) != (cb["entity"], cb["attribute"]):
        fail(
            f"{where}: {a} and {b} claim different things: "
            f"{ca['entity']}.{ca['attribute']} vs {cb['entity']}.{cb['attribute']}"
        )
    elif (ca["value"], ca["unit"]) == (cb["value"], cb["unit"]):
        fail(f"{where}: {a} and {b} claim the same value, so they do not disagree")


for x in contradictions:
    if len(x.get("facts", [])) == 2:
        check_claim_pair(x.get("id"), *x["facts"])
for s in stale:
    check_claim_pair(s.get("id"), s.get("states"), s.get("superseded_by"))
claim_pairs = sum(1 for x in contradictions if all(fid in claims for fid in x["facts"])) + sum(
    1 for s in stale if s.get("states") in claims and s.get("superseded_by") in claims
)

# ---------------------------------------------------------------- rule history
rules = [e for e, v in entities.items() if v["kind"] == "rule"]
for r in rules:
    if not any(r in f["entities"] and f["tier"] in ("code", "executed") for f in facts.values()):
        fail(f"{r}: no code or executed fact")
for s in steps_list:
    for e in s.get("changes", []):
        if e not in entities:
            fail(f"steps.yaml {s['id']}: unknown entity {e}")
            continue
        tagged = [
            f for f in facts.values() if e in f["entities"] and f["tier"] in ("code", "executed")
        ]
        if not any(f.get("valid_from") == s["id"] for f in tagged):
            fail(f"{e}: no code/executed fact with valid_from {s['id']}")
        if entities[e]["kind"] == "rule" and not any(f.get("valid_to") == s["id"] for f in tagged):
            fail(
                f"{e}: no code/executed fact with valid_to {s['id']} (the value before the change)"
            )

# ---------------------------------------------------------------- contradictions
losers = set()
seen_pairs = set()
for x in contradictions:
    xid = x.get("id")
    a, b = x.get("facts", [None, None])
    if a not in facts or b not in facts or a == b:
        fail(f"{xid}: bad facts {x.get('facts')}")
        continue
    pair = frozenset((a, b))
    if pair in seen_pairs:
        fail(f"{xid}: duplicate pair")
    seen_pairs.add(pair)
    if x.get("kind") not in KINDS:
        fail(f"{xid}: bad kind {x.get('kind')}")
    if x.get("label") != "refutes":
        fail(f"{xid}: label must be refutes")
    fa, fb = facts[a], facts[b]
    if not set(fa["entities"]) & set(fb["entities"]):
        fail(f"{xid}: {a} and {b} share no entity")
    ka, kb = (TIER_RANK[fa["tier"]], recency(a)), (TIER_RANK[fb["tier"]], recency(b))
    if ka == kb:
        fail(f"{xid}: no winner by tier then recency")
    expected = a if ka > kb else b
    if x.get("winner") != expected:
        fail(f"{xid}: winner {x.get('winner')} but tier/recency picks {expected}")
    loser = b if expected == a else a
    losers.add(loser)
    kinds_of = {
        fid: {c["document"].split("/", 1)[0] for c in facts[fid]["carriers"]} for fid in (a, b)
    }
    k = x.get("kind")
    if k == "wiki-vs-test":
        ok = "wiki" in kinds_of[loser] and facts[expected]["tier"] == "executed"
    elif k == "ticket-vs-code":
        ok = "ticket" in kinds_of[loser] and facts[expected]["tier"] in ("code", "executed")
    elif k == "doc-vs-code":
        ok = "doc" in kinds_of[loser] and facts[expected]["tier"] in ("code", "executed")
    elif k == "run-vs-code":
        ok = bool(facts[loser].get("demoted_by")) and facts[expected]["tier"] in (
            "code",
            "executed",
        )
    else:
        ok = all(kinds_of[fid] & set(DOC_KINDS) for fid in (a, b))
    if not ok:
        fail(f"{xid}: kind {k} does not match the carriers of {a} and {b}")

# ---------------------------------------------------------------- stale
for s in stale:
    sid, doc, fid, step, sup = (
        s.get("id"),
        s.get("document"),
        s.get("states"),
        s.get("changed_by"),
        s.get("superseded_by"),
    )
    if fid not in facts or sup not in facts:
        fail(f"{sid}: unknown fact {fid} or {sup}")
        continue
    if step not in STEPS:
        fail(f"{sid}: unknown step {step}")
        continue
    if doc.split("/", 1)[0] not in ("wiki", "doc"):
        fail(f"{sid}: {doc} is not a page")
    locs = [c["location"] for c in facts[fid]["carriers"] if c["document"] == doc]
    if not locs:
        fail(f"{sid}: {doc} is not a carrier of {fid}")
        continue
    if facts[fid]["tier"] != "documented":
        fail(f"{sid}: {fid} is not a documented fact")
    if facts[fid].get("valid_to") != step:
        fail(f"{sid}: {fid} valid_to {facts[fid].get('valid_to')} != changed_by {step}")
    if facts[sup].get("valid_from") != step:
        fail(f"{sid}: {sup} valid_from {facts[sup].get('valid_from')} != changed_by {step}")
    if not set(facts[sup]["entities"]) & set(STEP[step].get("changes", [])):
        fail(f"{sid}: {sup} is not about anything {step} changed")
    if not set(facts[fid]["entities"]) & set(facts[sup]["entities"]):
        fail(f"{sid}: {fid} and {sup} share no entity")
    d = doc_dates[(doc, locs[0])]
    if d >= STEP_DATE[step]:
        fail(f"{sid}: {doc} was edited {d.date()}, not before {step} ({STEP_DATE[step].date()})")
for k, n in Counter((s["document"], s["states"]) for s in stale).items():
    if n > 1:
        fail(f"stale: {k} listed {n} times")

# ---------------------------------------------------------------- aliases
alias_owner: dict[str, str] = {}
alias_ids = [a.get("id") for a in aliases]
if sorted(alias_ids) != sorted(entities) or len(set(alias_ids)) != len(alias_ids):
    fail("aliases: must list every entity in entities.yaml exactly once")
for a in aliases:
    eid = a.get("id")
    if eid not in entities:
        fail(f"aliases: unknown entity {eid}")
        continue
    if a.get("name") != entities[eid]["name"]:
        fail(f"aliases {eid}: name {a.get('name')!r} != entities.yaml {entities[eid]['name']!r}")
    al = a.get("aliases") or []
    if not 2 <= len(al) <= 6:
        fail(f"aliases {eid}: {len(al)} aliases, expected 2 to 6")
    for s in [a.get("name"), *al]:
        key = str(s).strip().casefold()
        if not key:
            fail(f"aliases {eid}: empty alias")
        elif key in alias_owner and alias_owner[key] != eid:
            fail(f"aliases: {s!r} belongs to both {alias_owner[key]} and {eid}")
        elif key in alias_owner and s != a.get("name"):
            fail(f"aliases {eid}: {s!r} repeats its own name or another alias")
        alias_owner[key] = eid


def normalised(s: str) -> str:
    return " ".join(re.sub(r"[-_./{}]+", " ", s.casefold()).split())


norm_owner: dict[str, set[str]] = {}
for key, eid in alias_owner.items():
    norm_owner.setdefault(normalised(key), set()).add(eid)
norm_collisions = {k: sorted(v) for k, v in norm_owner.items() if len(v) > 1}


def resolve(s) -> str | None:
    eid = alias_owner.get(str(s).strip().casefold()) if s is not None else None
    if eid is None:
        fail(f"mix: {s!r} resolves to no entity through names and aliases")
    return eid


# ---------------------------------------------------------------- mix
w = mix.get("weights", {})
if set(w) != set(SURFACES) or sum(w.values()) != 100:
    fail(f"mix: weights must cover {SURFACES} and sum to 100, got {w}")
stale_facts = {s["states"] for s in stale}
untrue = losers | stale_facts


def check_expects(where: str, ids: list, category: str | None = None) -> None:
    if not ids:
        fail(f"{where}: no expected facts")
    for fid in ids:
        if fid not in facts:
            fail(f"{where}: unknown fact {fid}")
        elif fid in untrue:
            fail(f"{where}: expects {fid}, which a source states wrongly or stalely")
        elif category and facts[fid]["category"] != category:
            fail(f"{where}: {fid} is {facts[fid]['category']}, not {category}")


queries = mix.get("queries", [])
by_surface: dict[str, list[dict]] = {s: [] for s in SURFACES}
for k, n in Counter(q.get("id") for q in queries).items():
    if n > 1 or not k:
        fail(f"mix: query id {k!r} used {n} times")
for q in queries:
    if q.get("surface") not in SURFACES:
        fail(f"mix {q.get('id')}: unknown surface {q.get('surface')!r}")
    else:
        by_surface[q["surface"]].append(q)
for s, want in MIX_COUNTS.items():
    if len(by_surface[s]) != want:
        fail(f"mix: {s} needs {want} queries, has {len(by_surface[s])}")
explain = by_surface["explain"]
if len({str(q.get("entity")).casefold() for q in explain}) != len(explain):
    fail("mix: explain entity strings must be distinct")
by_name = [q for q in explain if not q["id"].startswith("q-explain-alias-")]
by_alias = [q for q in explain if q["id"].startswith("q-explain-alias-")]
if len(by_alias) != EXPLAIN_BY_ALIAS:
    fail(f"mix: {len(by_alias)} explain-by-alias queries, expected {EXPLAIN_BY_ALIAS}")
explained_ids = set()
for q in explain:
    s = q.get("entity")
    if isinstance(s, str) and s.startswith("E-"):
        fail(f"mix {q['id']}: names the entity by id {s}; use its name or an alias")
    eid = resolve(s)
    if eid is None:
        continue
    if q in by_name and s != entities[eid]["name"]:
        fail(f"mix {q['id']}: {s!r} is not the canonical name of {eid}")
    if q in by_alias and s.casefold() == entities[eid]["name"].casefold():
        fail(f"mix {q['id']}: {s!r} is a canonical name, not an alias")
    if not any(eid in f["entities"] for f in facts.values()):
        fail(f"mix {q['id']}: {eid} has no fact")
    if q in by_name:
        explained_ids.add(eid)
for q in by_alias:
    eid = resolve(q.get("entity"))
    if eid and eid not in explained_ids:
        fail(f"mix {q['id']}: alias target {eid} is not also explained by name (no pairing)")
impact = [q for q in queries if q["id"].startswith("q-impact-")]
if len(impact) != IMPACT_QUERIES:
    fail(f"mix: {len(impact)} impact queries, expected {IMPACT_QUERIES}")
for q in impact:
    ids = [fid for fid in q.get("expects", []) if fid in facts]
    if len(ids) < 2 or len({e for fid in ids for e in facts[fid]["entities"]}) < 3:
        fail(f"mix {q['id']}: an impact query needs 2+ expected facts spanning 3+ entities")
for q in by_surface["search"]:
    if q.get("category") is not None and q["category"] not in CATEGORIES:
        fail(f"mix {q['id']}: bad category")
    if not q.get("query"):
        fail(f"mix {q['id']}: empty query")
    check_expects(f"mix {q['id']}", q.get("expects", []), q.get("category"))
for q in by_surface["ask"]:
    if not q.get("question"):
        fail(f"mix {q['id']}: empty question")
    check_expects(f"mix {q['id']}", q.get("expects", []))
cq = by_surface["contradictions"]
if sum(1 for q in cq if q.get("entity") is None) != 1:
    fail("mix: exactly one contradictions query must have entity null")
for q in cq:
    e = q.get("entity")
    if e is None:
        continue
    if isinstance(e, str) and e.startswith("E-"):
        fail(f"mix {q['id']}: names the entity by id {e}; use its name")
    e = resolve(e)
    if e is None:
        continue
    if not any(
        e in facts[a]["entities"] or e in facts[b]["entities"]
        for a, b in (x["facts"] for x in contradictions)
    ):
        fail(f"mix {q['id']}: {e} has no contradiction")
stale_counts = {}
for q in by_surface["stale"]:
    try:
        since = datetime.fromisoformat(str(q.get("since")))
    except ValueError:
        fail(f"mix {q['id']}: since {q.get('since')!r} is not ISO 8601")
        continue
    if since.tzinfo is None:
        fail(
            f"mix {q['id']}: since must carry a UTC offset "
            "(bench/score.py compares it with dated steps)"
        )
        continue
    n = sum(1 for s in stale if STEP_DATE[s["changed_by"]] > since)
    stale_counts[q["since"]] = n
    if n == 0:
        fail(f"mix {q['id']}: expects no stale page")

# ---------------------------------------------------------------- executed audit
audit_rows = {}
for line in audit_text.splitlines():
    if not line.startswith("| F-"):
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != 6:
        fail(f"audit: row does not have 6 cells: {line[:60]}")
        continue
    fid, test_cell, verdict, now_cell, change, _steps = cells
    if fid in audit_rows:
        fail(f"audit: {fid} listed twice")
    audit_rows[fid] = (test_cell.strip("`"), verdict, now_cell, change)
must_audit = {fid for fid, f in facts.items() if f["tier"] == "executed" or f.get("demoted_by")}
if set(audit_rows) != must_audit or len(audit_rows) != AUDITED:
    fail(
        f"audit: covers {len(audit_rows)} facts; missing {sorted(must_audit - set(audit_rows))}, "
        f"extra {sorted(set(audit_rows) - must_audit)}; expected {AUDITED}"
    )
audit_counts = Counter(v[1] for v in audit_rows.values())
for fid, (loc, verdict, now_cell, change) in audit_rows.items():
    if fid not in facts:
        continue
    locs = {
        c["location"]
        for c in facts[fid]["carriers"]
        if c["document"].startswith("code/") and is_test(c["document"][5:])
    }
    if loc not in locs:
        fail(f"audit {fid}: test {loc} is not the fact's test carrier")
    if verdict not in ("a", "b", "c"):
        fail(f"audit {fid}: verdict {verdict!r} is not a, b or c")
    if not now_cell:
        fail(f"audit {fid}: says nothing about what the test asserts now")
    if verdict == "b" and change != facts[fid]["statement"]:
        fail(f"audit {fid}: narrowed statement differs from facts.yaml")
    if verdict == "c" and not change.startswith("add: "):
        fail(f"audit {fid}: a (c) row must say what to add")

# ---------------------------------------------------------------- planted runs
kinds_planted = Counter(pl.get("kind") for pl in planted.get("planted", []))
if kinds_planted != Counter({"failing": 1, "skipped": 1, "flaky": 1}):
    fail(
        f"planted: expected one failing, one skipped and one flaky test, got {dict(kinds_planted)}"
    )
if not planted.get("rules") or not planted.get("runner", {}).get("env"):
    fail("planted: rules and runner.env are required")
x_ids = {x["id"]: x for x in contradictions}
for pl in planted.get("planted", []):
    pid, kind, loc = pl.get("id"), pl.get("kind"), pl.get("test")
    pt = plan_tests.get(loc)
    if not pt:
        fail(f"planted {pid}: test {loc} is not in PLAN tests")
        continue
    if not loc.startswith(f"{pl.get('file')}::"):
        fail(f"planted {pid}: test {loc} is not in file {pl.get('file')}")
    outcomes = pl.get("outcomes", {})
    if set(outcomes) != set(STEPS):
        fail(f"planted {pid}: outcomes must name every step")
    by = {
        o: sorted((s for s, v in outcomes.items() if v == o), key=STEPS.index)
        for o in ("passed", "failed", "skipped")
    }
    reruns = pl.get("reruns") or {}
    flaky = sorted((s for s, v in reruns.items() if v == "passed"), key=STEPS.index)
    fails = sorted((s for s in by["failed"] if s not in flaky), key=STEPS.index)
    want = {
        "passes_in": by["passed"],
        "fails_in": fails,
        "skipped_in": by["skipped"],
        "flaky_in": flaky,
    }
    for fld, steps in want.items():
        if outcome_steps(pt, fld) != steps:
            fail(f"planted {pid}: PLAN {fld} {outcome_steps(pt, fld)} != {steps}")
    for s in by["failed"]:
        if s not in reruns:
            fail(f"planted {pid}: a failure at {s} needs its rerun outcome")
    affected = pl.get("facts") or {}
    for fid in affected:
        if fid not in facts:
            fail(f"planted {pid}: unknown fact {fid}")
    if kind == "failing":
        demoted = [
            fid
            for fid in affected
            if facts.get(fid, {}).get("demoted_by", {}).get("location") == loc
        ]
        if len(demoted) != 1:
            fail(f"planted {pid}: exactly one affected fact must be demoted by {loc}")
        xid = str(pl.get("contradiction", "")).split(" ", 1)[0]
        x = x_ids.get(xid)
        if not x or x.get("kind") != "run-vs-code" or (demoted and demoted[0] not in x["facts"]):
            fail(
                f"planted {pid}: needs a run-vs-code contradiction on the demoted fact, got {xid!r}"
            )
    elif kind == "skipped":
        for fid in affected:
            if facts.get(fid, {}).get("tier") != "code":
                fail(f"planted {pid}: {fid} must stay at code (skipped tests never lift)")
            if loc not in {c["location"] for c in facts.get(fid, {}).get("carriers", [])}:
                fail(f"planted {pid}: the skipped test should be a code carrier of {fid}")
        if pt["passes_in"] or not pl.get("marker", "").startswith("@pytest.mark.skip"):
            fail(f"planted {pid}: a skipped test never passes and carries a skip marker")
    elif kind == "flaky":
        if not flaky:
            fail(f"planted {pid}: a flaky test needs a step whose rerun passes")
        for fid in affected:
            f = facts.get(fid, {})
            cited = {
                run_step(c["document"])
                for c in f.get("carriers", [])
                if c["document"].startswith("run/") and c["location"] == loc
            }
            if set(flaky) & cited:
                fail(f"planted {pid}: {fid} cites a run at a flaky step")
            if f.get("tier") != "executed" or f.get("demoted_by"):
                fail(f"planted {pid}: {fid} keeps its tier; a flaky step neither lifts nor demotes")

# ---------------------------------------------------------------- counts
cat = Counter(f["category"] for f in facts.values())
tier = Counter(f["tier"] for f in facts.values())
lo, hi = EXPECT_TOTAL
if not lo <= len(facts) <= hi:
    fail(f"facts: {len(facts)}, expected {lo}..{hi}")
for k, (lo, hi) in EXPECT_CATEGORY.items():
    if not lo <= cat[k] <= hi:
        fail(f"category {k}: {cat[k]}, expected {lo}..{hi}")
for k, (lo, hi) in EXPECT_TIER.items():
    if not lo <= tier[k] <= hi:
        fail(f"tier {k}: {tier[k]}, expected {lo}..{hi}")
actual = {
    "contradictions": len(contradictions),
    "stale": len(stale),
    "pr_only": len(pr_only),
    "wiki": len(wiki),
    "tickets": len(tickets),
    "docs": len(docs),
}
for k, n in EXACT.items():
    if actual[k] != n:
        fail(f"{k}: {actual[k]}, expected exactly {n}")
if len({x["id"] for x in contradictions}) != len(contradictions) or len(
    {s["id"] for s in stale}
) != len(stale):
    fail("duplicate X- or S- ids")

print(f"facts {len(facts)}")
print("  by category: " + ", ".join(f"{k} {cat[k]}" for k in CATEGORIES))
print("  by tier:     " + ", ".join(f"{k} {tier[k]}" for k in TIERS))
print(f"  PR-only:     {len(pr_only)} {pr_only}")
print(
    f"contradictions {len(contradictions)}: "
    + ", ".join(f"{k} {n}" for k, n in Counter(x["kind"] for x in contradictions).items())
)
print(f"stale {len(stale)}; mix stale expectations {stale_counts}")
print(
    f"claims: {len(claims)} of {sum(1 for f in facts.values() if is_numeric(f['statement']))} "
    f"numeric facts; {len({(c['entity'], c['attribute']) for c in claims.values()})} distinct "
    f"entity.attribute keys; {claim_pairs} contradiction/stale pairs join on the key"
)
print(
    f"mix: {len(queries)} queries ({', '.join(f'{s} {len(by_surface[s])}' for s in SURFACES)}); "
    f"explain by alias {len(by_alias)}, impact {len(impact)}"
)
print(f"aliases: {len(aliases)} entities, {len(alias_owner)} names and aliases, all unambiguous")
for k, v in sorted(norm_collisions.items()):
    print(f"  note: {k!r} is ambiguous once - _ . / are normalised: {', '.join(v)}")
print(
    f"executed audit: {len(audit_rows)} facts, "
    + ", ".join(f"{v} {audit_counts[v]}" for v in "abc")
)
print(
    "planted runs: "
    + ", ".join(
        f"{pl['id']} {pl['kind']} {pl['test'].split('::')[-1]}" for pl in planted["planted"]
    )
)
print(
    f"PLAN: wiki {len(wiki)}, docs {len(docs)}, tickets {len(tickets)} "
    f"({sum(1 for t in tickets.values() if t.get('noise'))} noise), "
    f"pulls {sorted(pulls)}, code {len(py_modules)} Python + {len(ts_files)} TypeScript, "
    f"tests {len(tests)}, runs {len(runs_plan)}"
)
print(
    f"carriers {len(fact_triples)}, all resolved in PLAN"
    if not any("PLAN" in e or "carrier" in e for e in errors)
    else f"carriers {len(fact_triples)}"
)
if errors:
    print(f"\nFAILED: {len(errors)} check(s)")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nOK: every check passed")
