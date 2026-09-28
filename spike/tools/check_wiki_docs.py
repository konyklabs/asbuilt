"""Verify sources/wiki/*.md and sources/docs/*.md against truth/PLAN.yaml + facts.yaml.

For every PLAN wiki/doc entry: the file exists, its front matter matches PLAN,
every anchor resolves to a `## Heading`, and the body under that heading states
every number/money value that appears in each of its facts' statements (a
cheap check that the value was actually written, not that the prose is good).

Also enforces that no anchored section contains a fact's statement verbatim,
and that no page -- anywhere in its body, not just an anchored section --
contains the first eight normalised words (lower-case, punctuation stripped,
whitespace collapsed) of any fact's statement.

Also scans each page for $/%/HH:MM values that belong to OTHER facts the page
is not supposed to state, and lists any hits for review (informational, not a
hard failure -- a genuine leak needs a human to confirm it isn't a coincidence).

Run: cd spike && uv run --with pyyaml python tools/check_wiki_docs.py
"""

import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
PLAN = yaml.safe_load((SPIKE / "truth/PLAN.yaml").read_text())
FACTS = yaml.safe_load((SPIKE / "truth/facts.yaml").read_text())
FACTS_BY_ID = {f["id"]: f for f in FACTS}

WIKI_DIR = SPIKE / "sources/wiki"
DOCS_DIR = SPIKE / "sources/docs"

VALUE_RE = re.compile(r"\$\d+(?:\.\d+)?|\d{1,2}:\d{2}|\d+(?:\.\d+)?%|\d+(?:\.\d+)?")


def is_dollar_percent_or_time(token: str) -> bool:
    return token.startswith("$") or token.endswith("%") or ":" in token


def slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def split_front_matter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "missing front matter opening ---"
    end = text.index("\n---\n", 4)
    fm_text = text[4:end]
    body = text[end + 5 :]
    return yaml.safe_load(fm_text), body


def heading_chunks(body: str) -> dict[str, str]:
    """Map the slug of every heading line to the text following it, up to
    the next heading line of any level (or EOF)."""
    lines = body.splitlines()
    heading_idxs = [i for i, ln in enumerate(lines) if ln.startswith("#")]
    chunks = {}
    for pos, i in enumerate(heading_idxs):
        line = lines[i]
        if not line.startswith("## "):
            continue
        heading_text = line[3:].strip()
        end = heading_idxs[pos + 1] if pos + 1 < len(heading_idxs) else len(lines)
        chunk = "\n".join(lines[i + 1 : end])
        chunks[slugify(heading_text)] = chunk
    return chunks


def fact_values(fid: str) -> set[str]:
    return set(VALUE_RE.findall(FACTS_BY_ID[fid]["statement"]))


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def normalize_words(s: str) -> list[str]:
    """Lower-case, punctuation stripped, whitespace collapsed -- word list."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return s.split()


def prose_word_count(body: str) -> int:
    """Word count of prose lines only -- skips heading markers and blank lines."""
    n = 0
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        n += len(re.findall(r"\S+", line))
    return n


ALL_STATEMENTS_NORM = {fid: normalize(f["statement"]) for fid, f in FACTS_BY_ID.items()}

# First eight normalised words of every fact's statement -- no page, anywhere
# in its body (not just an anchored section), may contain one of these runs.
PREFIX8_LEN = 8
PREFIX8_BY_FACT = {}
for fid, f in FACTS_BY_ID.items():
    words = normalize_words(f["statement"])
    if len(words) >= PREFIX8_LEN:
        PREFIX8_BY_FACT[fid] = " ".join(words[:PREFIX8_LEN])

WORD_RANGES = {"wiki": (150, 400), "doc": (300, 700)}

errors: list[str] = []
warnings: list[str] = []
word_counts: list[str] = []
n_wiki = n_docs = n_anchors = n_facts_checked = 0

# Global index: $/%/HH:MM token -> set of fact ids whose statement contains it.
global_tokens: dict[str, set[str]] = {}
for f in FACTS:
    for tok in VALUE_RE.findall(f["statement"]):
        if is_dollar_percent_or_time(tok):
            global_tokens.setdefault(tok, set()).add(f["id"])

pages: list[tuple[str, Path, dict]] = []  # (kind, path, plan_entry)


def check_page(kind: str, path: Path, entry: dict, expected_fm: dict) -> set[str]:
    global n_anchors, n_facts_checked
    assert path.exists(), f"{kind} missing file: {path}"
    text = path.read_text()
    fm, body = split_front_matter(text)
    for key, expected in expected_fm.items():
        actual = fm.get(key)
        assert actual == expected, (
            f"{path.name}: front matter {key!r} = {actual!r}, expected {expected!r}"
        )
    chunks = heading_chunks(body)
    page_fact_ids: set[str] = set()
    for anchor_entry in entry["anchors"]:
        n_anchors += 1
        anchor_slug = anchor_entry["anchor"].lstrip("#")
        assert anchor_slug in chunks, (
            f"{path.name}: anchor {anchor_entry['anchor']!r} has no matching heading"
        )
        chunk_text = chunks[anchor_slug]
        for f in anchor_entry["facts"]:
            n_facts_checked += 1
            page_fact_ids.add(f["id"])
            needed = fact_values(f["id"])
            missing = [v for v in needed if v not in chunk_text]
            if missing:
                errors.append(
                    f"{path.name} #{anchor_slug}: missing value(s) {missing} for {f['id']}"
                )
        # No fact's statement may appear verbatim (case/whitespace-insensitive)
        # under this heading -- pages must paraphrase, not paste ground truth.
        chunk_norm = normalize(chunk_text)
        for fid, stmt_norm in ALL_STATEMENTS_NORM.items():
            if stmt_norm and stmt_norm in chunk_norm:
                errors.append(f"{path.name} #{anchor_slug}: contains {fid} statement verbatim")
    # No eight-word prefix of any fact's statement may appear anywhere in the
    # page body -- whole-page scan, not scoped to the anchored sections.
    body_words_norm = " ".join(normalize_words(body))
    for fid, prefix in PREFIX8_BY_FACT.items():
        if prefix in body_words_norm:
            errors.append(
                f"{path.name}: contains the first {PREFIX8_LEN} words of {fid}'s "
                f"statement ({prefix!r}) somewhere in the page"
            )
    wc = prose_word_count(body)
    lo, hi = WORD_RANGES[kind]
    word_counts.append(f"{path.name}: {wc} words")
    if not (lo <= wc <= hi):
        errors.append(f"{path.name}: {wc} words, outside the {lo}-{hi} range for {kind}")
    return page_fact_ids


for entry in PLAN["wiki"]:
    n_wiki += 1
    path = WIKI_DIR / f"{entry['slug']}.md"
    expected_fm = {
        "id": f"wiki/{entry['slug']}",
        "title": entry["title"],
        "version": entry["version"],
        "lastmodified": entry["lastmodified"],
        "author": entry["author"],
        "space": "GW",
    }
    page_fact_ids = check_page("wiki", path, entry, expected_fm)
    pages.append(("wiki", path, page_fact_ids))

for entry in PLAN["docs"]:
    n_docs += 1
    path = DOCS_DIR / f"{entry['id']}.md"
    expected_fm = {
        "id": f"doc/{entry['id']}",
        "title": entry["title"],
        "headRevisionId": str(entry["headRevisionId"]),
        "modifiedTime": entry["modifiedTime"],
        "owner": entry["owner"],
        "mimeType": "application/vnd.google-apps.document",
    }
    page_fact_ids = check_page("doc", path, entry, expected_fm)
    pages.append(("doc", path, page_fact_ids))

# Cross-page scan: values from facts NOT stated on this page.
cross_hits: list[str] = []
for _kind, path, page_fact_ids in pages:
    text = path.read_text()
    _, body = split_front_matter(text)
    allowed = set()
    for fid in page_fact_ids:
        allowed |= {v for v in fact_values(fid) if is_dollar_percent_or_time(v)}
    for token, owner_facts in global_tokens.items():
        if token in allowed:
            continue
        if owner_facts <= page_fact_ids:
            continue
        # Digit-boundary match so "5%" inside "25%" isn't a false hit.
        pattern = r"(?<!\d)" + re.escape(token) + r"(?!\d)"
        if re.search(pattern, body):
            foreign = owner_facts - page_fact_ids
            cross_hits.append(
                f"{path.name}: contains {token!r} which belongs to {sorted(foreign)}, not this page"
            )

print("word counts:")
for wc in word_counts:
    print(f"  {wc}")
print(f"wiki pages checked: {n_wiki}")
print(f"docs checked: {n_docs}")
print(f"anchors checked: {n_anchors}")
print(f"fact-value checks: {n_facts_checked}")
print(f"errors: {len(errors)}")
for e in errors:
    print(f"  ERROR: {e}")
print(f"cross-page value hits for review: {len(cross_hits)}")
for h in cross_hits:
    print(f"  REVIEW: {h}")

if errors:
    sys.exit(1)
print("OK")
