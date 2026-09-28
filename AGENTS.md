# AGENTS.md

For an agent working in this repository. The org's rules, the workspace
`CLAUDE.md` and `.claude/rules/agentic-sdlc.md` in `konyklabs/workspace`,
apply here unchanged; this file adds only what is specific to `asbuilt`.

## State

Spike. There is no product code yet. The driving idea is
[konyklabs/roadmap#153](https://github.com/konyklabs/roadmap/issues/153); the
spike is [konyklabs/roadmap#154](https://github.com/konyklabs/roadmap/issues/154),
recorded in D-013 (build, Python, benchmark two stacks). The harness and the
invented system live under `spike/` (#2); the prototypes are #3 and #4; the
benchmark report and the pipeline-and-schema ADR are #5 (with #7, #8 and #9
in between: hardening, the test connector, the baseline arm). Nothing lands
under `src/` before that ADR exists. `spike/` is its own `uv` project: `cd spike && uv run pytest`.

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
