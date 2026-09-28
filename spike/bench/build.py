"""Builds the invented system's git repository with reproducible history.

Reads ``<fixture>/system/`` (the final content of every file, everything
except the ``history/`` directory) and ``<fixture>/system/history/steps.yaml``
(the ordered commit steps) and produces ``<out>/repo/`` — a real git
repository, one commit per step, oldest first — plus ``<out>/commits.json``,
mapping each step id to its SHA, date and message.

Content rule ("content through that step"): ``system/history/<step>/<path>``
is that file's content *up to and including* that step. Content at step k is
the overlay at the SMALLEST step j >= k that has one (for this path); if
none, the final ``system/<path>``. So an overlay records the value that held
from just after the *previous* overlay step through this one — the overlay
for a value's last step, not its first. A run of N steps sharing one value
needs exactly one overlay file, at the run's last step; the final run (up to
the fixture's last step) needs none — it's just ``system/<path>``.

An empty marker ``system/history/<step>/<path>.absent`` means the path does
not exist through that step (so a file first appearing at c6 needs exactly
one marker, ``history/c5/<path>.absent`` — every step at or before c5 then
resolves to that marker via the same "smallest j >= k" rule, and c6 itself,
having no entry at or after it, falls through to final content).

Both kinds of entry are discovered by scanning ``history/<step>/**`` (every
file under each step directory, skipping ``steps.yaml`` itself); the
``files:`` key some steps carry in ``steps.yaml`` is informational only and
does not drive this — it is never read here.

Any path with a component in ``EXCLUDED_DIRNAMES`` (``node_modules``,
``.ruff_cache``, ``__pycache__``, ``.git``, ``.venv``, and similar) is never
treated as fixture content, in ``system/`` or under a ``history/<step>/``
overlay — these are generated/tooling output that can appear if a fixture's
code was run or linted locally while it was being authored, never something
meant to enter the built repository's own history.

Reproducibility: GIT_AUTHOR_NAME/EMAIL and GIT_COMMITTER_NAME/EMAIL are fixed
("Gearwell Fixture" / "fixture@gearwell.invalid"), both dates are the step's
date, and every git invocation passes ``-c commit.gpgsign=false``. No
third-party git library is used, only subprocess.

CLI: ``uv run python bench/build.py [--fixture .] [--out build]``. The
``--fixture`` flag is not in the original spec text (which shows only
``[--out build]``); it was added so the harness's own tests can build the
mini fixture into a tmp dir without relying on the working directory. It
defaults to ``.``, so the documented invocation from ``spike/`` is unchanged.

``Timeline`` (below) wraps the same content rule for reuse outside a git
build — ``bench/truth.py``'s ``check_consistency`` materialises a ``code/``
carrier's content at its declared version this way, not via git, so it works
even when nothing has been built yet.
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

AUTHOR_NAME = "Gearwell Fixture"
AUTHOR_EMAIL = "fixture@gearwell.invalid"

HISTORY_DIRNAME = "history"
STEPS_FILENAME = "steps.yaml"
ABSENT_SUFFIX = ".absent"

# Generated/tooling directories that are never hand-authored fixture content,
# even if they show up under system/ (e.g. from running npm/ruff locally
# against the fixture code while authoring it). Never part of a commit.
EXCLUDED_DIRNAMES = {
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
}


def _is_excluded(rel_parts: tuple[str, ...]) -> bool:
    return any(part in EXCLUDED_DIRNAMES for part in rel_parts)


@dataclass(frozen=True)
class Step:
    id: str
    date: str
    message: str


class BuildError(RuntimeError):
    """Raised when the fixture's steps.yaml or file layout cannot be built."""


def load_steps(steps_path: Path) -> list[Step]:
    if not steps_path.is_file():
        raise BuildError(f"no steps file at {steps_path}")
    raw_steps = yaml.safe_load(steps_path.read_text()) or []
    steps: list[Step] = []
    seen_ids: set[str] = set()
    for raw in raw_steps:
        step_id = raw["id"]
        if step_id in seen_ids:
            raise BuildError(f"duplicate step id {step_id!r} in {steps_path}")
        seen_ids.add(step_id)
        steps.append(Step(id=step_id, date=raw["date"], message=raw["message"]))
    if not steps:
        raise BuildError(f"no steps found in {steps_path}")
    return steps


def _final_paths(system_root: Path) -> set[str]:
    """Every file under system/, excluding history/ and EXCLUDED_DIRNAMES, as
    posix-relative paths."""
    paths: set[str] = set()
    if not system_root.is_dir():
        return paths
    for candidate in system_root.rglob("*"):
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(system_root)
        if rel.parts and rel.parts[0] == HISTORY_DIRNAME:
            continue
        if _is_excluded(rel.parts):
            continue
        paths.add(rel.as_posix())
    return paths


# An entry is ("content", absolute Path) or ("absent", None).
Entry = tuple[str, Path | None]


def _entry_index(history_root: Path, steps: list[Step]) -> dict[str, dict[str, Entry]]:
    """path -> {step_id: entry}, discovered by scanning history/<step>/** for
    both regular files (content) and *.absent markers (absence)."""
    entries: dict[str, dict[str, Entry]] = {}
    for step in steps:
        step_dir = history_root / step.id
        if not step_dir.is_dir():
            continue
        for candidate in step_dir.rglob("*"):
            if not candidate.is_file():
                continue
            rel_path = candidate.relative_to(step_dir)
            if _is_excluded(rel_path.parts):
                continue
            rel = rel_path.as_posix()
            if rel.endswith(ABSENT_SUFFIX):
                target = rel[: -len(ABSENT_SUFFIX)]
                entries.setdefault(target, {})[step.id] = ("absent", None)
            else:
                entries.setdefault(rel, {})[step.id] = ("content", candidate)
    return entries


class Timeline:
    """The content-through-each-step rule, precomputed once and reusable for
    repeated lookups (by build() to write commits, and by check_consistency
    to materialise a code/ carrier's content at its declared version)."""

    def __init__(self, fixture_root: Path):
        self.system_root = fixture_root / "system"
        self.history_root = self.system_root / HISTORY_DIRNAME
        self.steps = load_steps(self.history_root / STEPS_FILENAME)
        self._index_of = {step.id: idx for idx, step in enumerate(self.steps)}
        self._entries = _entry_index(self.history_root, self.steps)
        # Per path, entries sorted by step index, for a bisect lookup.
        self._sorted: dict[str, list[tuple[int, Entry]]] = {
            path: sorted((self._index_of[sid], entry) for sid, entry in chain.items())
            for path, chain in self._entries.items()
        }
        self.final_paths = _final_paths(self.system_root)
        self.all_paths = self.final_paths | set(self._entries)

    def content_at(self, path: str, step_id: str) -> bytes | None:
        """Content of `path` through `step_id`, or None if it doesn't exist then."""
        if step_id not in self._index_of:
            raise BuildError(f"unknown step {step_id!r}")
        step_index = self._index_of[step_id]
        chain = self._sorted.get(path)
        if chain:
            positions = [pos for pos, _entry in chain]
            i = bisect.bisect_left(positions, step_index)
            if i < len(chain):
                kind, source = chain[i][1]
                if kind == "absent":
                    return None
                return source.read_bytes()
        final_path = self.system_root / path
        if final_path.is_file():
            return final_path.read_bytes()
        return None

    def active_paths_at(self, step_id: str) -> set[str]:
        return {p for p in self.all_paths if self.content_at(p, step_id) is not None}


def _run_git(repo: Path, args: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_working_tree(repo: Path, timeline: Timeline, step_id: str) -> None:
    for entry in repo.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    for path in timeline.active_paths_at(step_id):
        content = timeline.content_at(path, step_id)
        if content is None:
            continue
        dest = repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)


def build(fixture_root: Path, out_root: Path) -> dict[str, dict[str, str]]:
    timeline = Timeline(fixture_root)

    repo = out_root / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)

    base_env = dict(os.environ)
    base_env["GIT_AUTHOR_NAME"] = AUTHOR_NAME
    base_env["GIT_AUTHOR_EMAIL"] = AUTHOR_EMAIL
    base_env["GIT_COMMITTER_NAME"] = AUTHOR_NAME
    base_env["GIT_COMMITTER_EMAIL"] = AUTHOR_EMAIL

    _run_git(repo, ["init", "--initial-branch=main", "-q"], base_env)

    commits: dict[str, dict[str, str]] = {}
    for step in timeline.steps:
        _write_working_tree(repo, timeline, step.id)

        env = dict(base_env)
        env["GIT_AUTHOR_DATE"] = step.date
        env["GIT_COMMITTER_DATE"] = step.date

        _run_git(repo, ["add", "-A"], env)
        # Allow-empty: a step that only changes metadata (no files/history)
        # still gets a commit, so step ids always map 1:1 to a SHA.
        _run_git(repo, ["commit", "--allow-empty", "-q", "-m", step.message], env)
        sha = _run_git(repo, ["rev-parse", "HEAD"], env)
        commits[step.id] = {"sha": sha, "date": step.date, "message": step.message}

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "commits.json").write_text(json.dumps(commits, indent=2) + "\n")
    return commits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", default=".", help="fixture root containing system/ (default: .)"
    )
    parser.add_argument(
        "--out", default="build", help="output directory for repo/ and commits.json"
    )
    args = parser.parse_args(argv)

    fixture_root = Path(args.fixture).resolve()
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = Path.cwd() / out_root

    commits = build(fixture_root, out_root)

    width = max((len(sid) for sid in commits), default=2)
    print(f"{'step':<{width}}  sha                                       date")
    for step_id, info in commits.items():
        print(f"{step_id:<{width}}  {info['sha']}  {info['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
