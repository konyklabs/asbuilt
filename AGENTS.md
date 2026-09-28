# AGENTS.md

For an agent working in this repository. The org's rules, the workspace
`CLAUDE.md` and `.claude/rules/agentic-sdlc.md` in `konyklabs/workspace`,
apply here unchanged; this file adds only what is specific to `asbuilt`.

## State

Bootstrap. There is no code yet. The driving task is
[konyklabs/roadmap#153](https://github.com/konyklabs/roadmap/issues/153); the
next step is the storage-engine spike, which ends in an ADR in
`roadmap/decisions/`. The spike's synthetic system and benchmark harness live
under `spike/`; nothing lands under `src/` before that ADR exists.

## What this repository must never contain

`asbuilt` is developed cleanroom. Nothing in here (code, tests, fixtures,
examples, docs, issues, commit messages, branch names) may describe, name or
resemble any real proprietary system. Fixtures are an invented system, written
to be obviously invented. The proprietary-terms scan runs on every PR and the
shared git hooks block commits locally; both are backstops, not the rule. If
you find yourself reaching for a real system's structure to make a fixture
realistic, stop and invent one instead.

## Conventions

- Python by default (`uv`, `src/` layout, pytest, ruff); the engine ADR may
  override the language.
- Every fact the tool stores carries provenance. A change that lets a fact in
  without a citation is a bug, not a shortcut.
- The engine sits behind one interface in `store/`. Connector and query code
  never import a driver directly.
- Evidence: paste the command and its output. "Tests pass" is not evidence.

## Layout

See the README's "Repository layout, planned" until there is one to describe.
