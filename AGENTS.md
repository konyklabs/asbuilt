# AGENTS.md

For an agent working in this repository. The org's rules, the workspace
`CLAUDE.md` and `.claude/rules/agentic-sdlc.md` in `konyklabs/workspace`,
apply here, except where "Mode: rapid" below replaces them until the ADR of
#5 merges; beyond that this file adds only what is specific to `asbuilt`.

## State

Spike. There is no product code yet. The driving idea is
[konyklabs/roadmap#153](https://github.com/konyklabs/roadmap/issues/153); the
spike is [konyklabs/roadmap#154](https://github.com/konyklabs/roadmap/issues/154),
recorded in D-013 (build, Python, benchmark two stacks). The harness and the
invented system live under `spike/` (#2); the prototypes are #3 and #4; the
benchmark report and the pipeline-and-schema ADR are #5 (with #7, #8 and #9
in between: hardening, the test connector, the baseline arm). Nothing lands
under `src/` before that ADR exists. `spike/` is its own `uv` project: `cd spike && uv run pytest`.

## Mode: rapid, until the ADR of #5 merges

The spike's pull requests waited hours for a merge behind hosted checks that
take seconds (#25). Until the ADR of #5 is merged, this section replaces the
workspace's local review round and its merge bar for this repository. Oleg
approved it by merging the pull request that added it. Whatever it does not
name stays as the workspace has it, the Red list included.

- **Green is one script.** `scripts/check.sh` lints the workflows, parses the
  shell scripts and runs `ruff` and the spike's tests. `just check` runs it
  natively. `just ci` runs it natively and then again as
  `.github/workflows/ci.yml` in a clean container under
  [act](https://github.com/nektos/act), where the tests that need Docker or a
  built `spike/build/` skip and say so. The first line of each run names the
  commit, whether the tree was clean and whether `spike/build/` was present.
  That workflow is `workflow_dispatch` only: nothing in it runs on github.com
  unless someone dispatches it by hand.
- **One task.** A change confined to `spike/` needs no issue of its own. Its
  pull request title carries `konyklabs/roadmap#154`, and what it found goes
  in a comment there.
- **A session merges its own pull request**, by squash, when four things
  hold: `just ci` ended green on the commit being merged, with a clean tree;
  that output is in the pull request body; the two hosted checks, the title
  lint and the proprietary-terms scan, are green on that commit; and nothing
  is open on the pull request: every comment is answered, and if the `gate`
  label was added its verdict is an approval of that commit. The merge names
  the commit the evidence names:
  `gh pr merge --squash --match-head-commit <sha>`. No review round is needed.
- **The exam and the marking keep their review.** A change to the fixture
  (`spike/system/`, `spike/sources/`, `spike/truth/`, `spike/queries/`), to
  the scorer and what it loads (`spike/bench/score.py`, `spike/bench/truth.py`,
  `spike/bench/build.py`) or to the calibration sets under
  `spike/tests/fixtures/` gets the workspace's one local round first, with
  its findings and their disposition in the pull request body, and then
  merges under the four conditions above. A wrong scorer moves every arm's
  number and fails no test.
- **Two kinds of change wait for Oleg:** what green means (`scripts/`,
  `justfile`, `.actrc`, `.github/`, the pytest and ruff tables of
  `spike/pyproject.toml`, any `conftest.py`) and the rules and guard rails
  (this file, `CLAUDE.md`, anything under `.claude/`, the hooks, and whatever
  the workspace's Red list names). A pull request that touches one of these
  waits whatever else it touches.
- **It ends** when the ADR of #5 merges, whatever the State section still
  says; the pull request that records the merge removes this section.
  Nothing under `src/` is merged in this mode.

## What this repository must never contain

`asbuilt` is developed cleanroom. Nothing in here (code, tests, fixtures,
examples, docs, issues, commit messages, branch names) may describe, name or
resemble any real proprietary system. Fixtures are an invented system, written
to be obviously invented. The proprietary-terms scan runs on every PR and the
shared git hooks block commits locally; both are backstops, not the rule. If
you find yourself reaching for a real system's structure to make a fixture
realistic, stop and invent one instead.

## Conventions

- Python, per D-013 (`uv`, `src/` layout, pytest, ruff).
- Every fact the tool stores carries provenance. A change that lets a fact in
  without a citation is a bug, not a shortcut.
- The engine sits behind one interface in `store/`. Connector and query code
  never import a driver directly.
- Evidence: paste the command and its output. "Tests pass" is not evidence.

## Layout

See the README's "Repository layout, planned" until there is one to describe.
The pipeline is `scripts/check.sh` (the check), `scripts/act.sh` and `.actrc`
(act's wrapper and defaults), `.github/workflows/ci.yml` and the `justfile`.
