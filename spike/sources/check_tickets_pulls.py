"""Verify sources/tickets/*.json and sources/pulls/*.json against PLAN.yaml
and truth/facts.yaml.

For every PLAN ticket and pull:
  - the fixture file exists and is valid JSON
  - its metadata fields match PLAN (key/summary/status/created/updated/reporter
    for tickets; number/title/state/author/opened/closed/merged_step for pulls)
  - every location PLAN references (description, body, comment-<k>) exists
  - for every fact stated at a location, the location's text contains every
    number/money/time token from that fact's canonical statement in
    truth/facts.yaml

Then, across every ticket/pull text, flags any money/percent/colon-time token
drawn from truth/facts.yaml that shows up somewhere it is not supposed to
(noise leakage) -- for review, not necessarily all real errors.

Asserts that no location, anywhere in the corpus, contains any fact's
canonical statement verbatim (case-insensitive, whitespace-normalised) --
facts must be paraphrased into the surrounding prose, never pasted.

Finally confirms each PR-only fact's distinctive rationale phrase (hand-picked
per fact, since the statement itself is never quoted verbatim) appears in
exactly one location across the whole tickets/ + pulls/ corpus.

Run: cd spike && uv run --with pyyaml python sources/check_tickets_pulls.py
"""

import json
import re
import sys
from pathlib import Path

import yaml

SOURCES = Path(__file__).resolve().parent
SPIKE = SOURCES.parent
TICKETS_DIR = SOURCES / "tickets"
PULLS_DIR = SOURCES / "pulls"

PLAN = yaml.safe_load((SOURCES / "PLAN.yaml").read_text())
FACTS = yaml.safe_load((SPIKE / "truth" / "facts.yaml").read_text())
FACTS_BY_ID = {f["id"]: f for f in FACTS}

errors = []
noise_hits = []

# ---- token extraction -------------------------------------------------

# every number/money/time token in a fact statement: must be present verbatim
# wherever that fact is stated.
ALL_NUM_RE = re.compile(r"\$\d+(?:\.\d+)?|\d{1,2}:\d{2}|\d+(?:\.\d+)?%|\d+(?:\.\d+)?")

# the narrower set used for the cross-document noise scan: money, percent and
# colon-time values specifically (per the authoring brief), which are the
# tokens unlikely to appear by coincidence.
DOLLAR_RE = re.compile(r"\$\d+(?:\.\d+)?")
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def all_number_tokens(statement):
    return set(ALL_NUM_RE.findall(statement))


def sensitive_tokens(statement):
    toks = set()
    toks |= set(DOLLAR_RE.findall(statement))
    toks |= set(PERCENT_RE.findall(statement))
    toks |= set(TIME_RE.findall(statement))
    return toks


# token -> set of fact ids in facts.yaml that state it
SENSITIVE_INDEX = {}
for f in FACTS:
    for tok in sensitive_tokens(f["statement"]):
        SENSITIVE_INDEX.setdefault(tok, set()).add(f["id"])


def normalize(s):
    return re.sub(r"\s+", " ", s.strip().lower())


# Hand-picked distinctive phrases for the 5 PR-only rationale facts: since the
# fixture never quotes a fact's statement verbatim, uniqueness has to be
# checked against a phrase the author actually wrote, not the statement text.
DISTINCTIVE_PHRASES = {
    "F-113": "empty by noon",
    "F-114": "before this pause existed",
    "F-115": "legal still needs to sign off on rain surge pricing",
    "F-116": "starts rate-limiting a merchant",
    "F-117": "taking over ownership of the skyglass integration from fleet",
}


def pr_only_fact_ids(plan):
    ids = set()
    for p in plan["pulls"]:
        buckets = [p["body"].get("facts", [])] + [c.get("facts", []) for c in p.get("comments", [])]
        for facts in buckets:
            for fi in facts:
                if str(fi.get("role", "")).startswith("PR-only"):
                    ids.add(fi["id"])
    return ids


PR_ONLY_IDS = pr_only_fact_ids(PLAN)


# ---- location helpers ---------------------------------------------------


def load_json(path):
    return json.loads(path.read_text())


def location_text(doc, location, body_field):
    if location == body_field:
        return doc.get(body_field, "")
    if location.startswith("comment-"):
        for c in doc.get("comments", []):
            if c.get("id") == location:
                return c.get("body", "")
        return None
    return None


# corpus of every (kind, id, location, text) for the noise scan and the
# pr-only uniqueness check
CORPUS = []

ticket_count = 0
pull_count = 0

# ---- tickets --------------------------------------------------------------

for t in PLAN["tickets"]:
    ticket_count += 1
    key = t["key"]
    path = TICKETS_DIR / f"{key}.json"
    if not path.exists():
        errors.append(f"MISSING ticket file {path}")
        continue
    try:
        data = load_json(path)
    except Exception as e:  # noqa: BLE001
        errors.append(f"INVALID JSON {path}: {e}")
        continue

    if data.get("id") != f"ticket/{key}":
        errors.append(f"{key}: id mismatch: {data.get('id')!r}")
    for field in ["key", "summary", "status", "created", "updated", "reporter"]:
        if data.get(field) != t.get(field):
            errors.append(f"{key}: field {field} mismatch: {data.get(field)!r} != {t.get(field)!r}")

    plan_comments = t.get("comments", [])
    fixture_comments = data.get("comments", [])
    if len(fixture_comments) != len(plan_comments):
        errors.append(
            f"{key}: comment count mismatch: {len(fixture_comments)} != {len(plan_comments)}"
        )

    locations = [("description", t["description"].get("facts", []))]
    for pc in plan_comments:
        locations.append((pc["id"], pc.get("facts", [])))
        match = next((c for c in fixture_comments if c.get("id") == pc["id"]), None)
        if not match:
            errors.append(f"{key}: missing comment {pc['id']}")
            continue
        if match.get("author") != pc["author"]:
            errors.append(
                f"{key}:{pc['id']} author mismatch: {match.get('author')!r} != {pc['author']!r}"
            )
        if match.get("created") != pc["created"]:
            errors.append(f"{key}:{pc['id']} created mismatch")

    for loc, facts in locations:
        text = location_text(data, loc, "description")
        if text is None:
            errors.append(f"{key}: location {loc} not found")
            continue
        CORPUS.append(("ticket", key, loc, text, {fi["id"] for fi in facts}))
        for fitem in facts:
            fid = fitem["id"]
            statement = FACTS_BY_ID[fid]["statement"]
            for tok in all_number_tokens(statement):
                if tok not in text:
                    errors.append(f"{key}:{loc} missing token {tok!r} for {fid}")

# ---- pulls ------------------------------------------------------------

for p in PLAN["pulls"]:
    pull_count += 1
    number = p["number"]
    path = PULLS_DIR / f"{number}.json"
    if not path.exists():
        errors.append(f"MISSING pull file {path}")
        continue
    try:
        data = load_json(path)
    except Exception as e:  # noqa: BLE001
        errors.append(f"INVALID JSON {path}: {e}")
        continue

    if data.get("id") != f"pull/{number}":
        errors.append(f"PR{number}: id mismatch: {data.get('id')!r}")
    for field in ["number", "title", "state", "author", "opened", "closed", "merged_step"]:
        if data.get(field) != p.get(field):
            errors.append(
                f"PR{number}: field {field} mismatch: {data.get(field)!r} != {p.get(field)!r}"
            )

    plan_comments = p.get("comments", [])
    fixture_comments = data.get("comments", [])
    if len(fixture_comments) != len(plan_comments):
        errors.append(
            f"PR{number}: comment count mismatch: {len(fixture_comments)} != {len(plan_comments)}"
        )

    locations = [("body", p["body"].get("facts", []))]
    for pc in plan_comments:
        locations.append((pc["id"], pc.get("facts", [])))
        match = next((c for c in fixture_comments if c.get("id") == pc["id"]), None)
        if not match:
            errors.append(f"PR{number}: missing comment {pc['id']}")
            continue
        if match.get("author") != pc["author"]:
            errors.append(f"PR{number}:{pc['id']} author mismatch")
        if match.get("created") != pc["created"]:
            errors.append(f"PR{number}:{pc['id']} created mismatch")

    for loc, facts in locations:
        text = location_text(data, loc, "body")
        if text is None:
            errors.append(f"PR{number}: location {loc} not found")
            continue
        CORPUS.append(("pull", str(number), loc, text, {fi["id"] for fi in facts}))
        for fitem in facts:
            fid = fitem["id"]
            statement = FACTS_BY_ID[fid]["statement"]
            for tok in all_number_tokens(statement):
                if tok not in text:
                    errors.append(f"PR{number}:{loc} missing token {tok!r} for {fid}")

# ---- noise scan: sensitive (money/percent/colon-time) tokens found where ---
# ---- they don't belong -----------------------------------------------------

for kind, ident, loc, text, assigned in CORPUS:
    for tok, fact_ids in SENSITIVE_INDEX.items():
        if tok in text and not (fact_ids & assigned):
            noise_hits.append(
                f"{kind}/{ident}:{loc} contains {tok!r} (belongs to {sorted(fact_ids)})"
            )

# ---- verbatim scan: no location may contain any fact's canonical statement -
# ---- text verbatim (case-insensitive, whitespace-normalised) --------------

verbatim_hits = []
NORM_STATEMENTS = [(f["id"], normalize(f["statement"])) for f in FACTS]
for kind, ident, loc, text, _assigned in CORPUS:
    norm_text = normalize(text)
    for fid, norm_stmt in NORM_STATEMENTS:
        if norm_stmt and norm_stmt in norm_text:
            verbatim_hits.append(f"{kind}/{ident}:{loc} states {fid} verbatim")
errors.extend(verbatim_hits)

# ---- PR-only facts: distinctive rationale phrase appears in exactly one ---
# ---- location (never the statement itself -- see verbatim scan above) -----

pr_only_report = []
for fid in sorted(PR_ONLY_IDS):
    phrase = DISTINCTIVE_PHRASES.get(fid)
    if phrase is None:
        errors.append(f"PR-only {fid}: no DISTINCTIVE_PHRASES entry to check against")
        continue
    hits = [
        f"{kind}/{ident}:{loc}" for kind, ident, loc, text, _ in CORPUS if phrase in normalize(text)
    ]
    pr_only_report.append((fid, hits))
    if len(hits) != 1:
        errors.append(
            f"PR-only {fid}: expected exactly 1 location for {phrase!r}, found {len(hits)}: {hits}"
        )

# ---- report -----------------------------------------------------------

print(f"PLAN tickets: {ticket_count}, PLAN pulls: {pull_count}")
print(f"fixture tickets on disk: {len(list(TICKETS_DIR.glob('*.json')))}")
print(f"fixture pulls on disk: {len(list(PULLS_DIR.glob('*.json')))}")
print()
print(f"PR-only facts ({len(PR_ONLY_IDS)}): {sorted(PR_ONLY_IDS)}")
for fid, hits in pr_only_report:
    print(f"  {fid}: {hits}")
print()

print(f"noise hits (sensitive tokens outside their assigned location): {len(noise_hits)}")
for h in noise_hits:
    print(f"  NOISE: {h}")
print()

print(f"verbatim hits (a fact's statement quoted whole, anywhere): {len(verbatim_hits)}")
for h in verbatim_hits:
    print(f"  VERBATIM: {h}")
print()

print(f"errors: {len(errors)}")
for e in errors:
    print(f"  ERROR: {e}")

if errors:
    sys.exit(1)
print("\nOK")
