"""The built git repository as the test connector's timeline.

The ingest root holds the repository's content at one step (``repo/``) and
the run reports through it, but the connector's tier rule needs history: a
passing run at an earlier commit still proves a test only if nothing it
exercises changed since (``git diff``). A real connector reads that from the
repository itself (GitHub SHAs, D-013), so the arm does too: ``ensure_built``
builds the invented system's repository with ``bench.build.build`` (the same
reproducible SHAs the harness cites) into ``build/<arm>/`` by default, or
reads an already-built one from ``ASBUILT_B_BUILT`` (a directory holding
``repo/`` and ``commits.json``). The arm never reads ``system/history/
steps.yaml`` itself: ``bench.build`` turns it into commits (sha, date,
message) and that is all that leaves it.

``GitHistory`` implements what ``connectors.tests.__main__.build_step_output``
and ``lift.build_contradiction_payload`` read from a timeline
(``content_at``, ``active_paths_at``), from ``git ls-tree``/``git cat-file``;
``step_of_checkout`` finds which commit an ingest root's ``repo/`` is, by
blob hash; ``last_change`` gives a file's last-changing commit at a step (a
``code/`` document's version and lastmodified).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent.parent
_NOT_SERVICES = {"tests", "test", "docs", "scripts", "node_modules"}


@dataclass(frozen=True)
class Step:
    id: str
    sha: str
    date: datetime
    message: str


def ensure_built(arm: str, spike_root: Path = SPIKE_ROOT) -> tuple[Path, dict[str, dict]]:
    """(repo, commits) — from ``ASBUILT_B_BUILT`` when set, else built fresh
    into ``build/<arm>/`` (deterministic, under a second)."""
    override = os.environ.get("ASBUILT_B_BUILT")
    if override:
        built = Path(override)
        return built / "repo", json.loads((built / "commits.json").read_text())
    from bench.build import build  # noqa: PLC0415 - only when building

    out = spike_root / "build" / arm
    commits = build(spike_root, out)
    return out / "repo", commits


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True, check=True)
    return result.stdout


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class GitHistory:
    def __init__(self, repo: Path, commits: dict[str, dict]) -> None:
        self.repo = repo
        self.commits = commits
        self.steps = [
            Step(id=k, sha=v["sha"], date=datetime.fromisoformat(v["date"]), message=v["message"])
            for k, v in commits.items()
        ]
        self.step_ids = [s.id for s in self.steps]
        self._by_id = {s.id: s for s in self.steps}
        self._trees: dict[str, dict[str, str]] = {}
        self._blobs: dict[str, bytes] = {}

    def step(self, step_id: str) -> Step:
        return self._by_id[step_id]

    def date(self, step_id: str) -> datetime:
        return self._by_id[step_id].date

    def tree(self, step_id: str) -> dict[str, str]:
        """path -> blob sha at the step's commit."""
        if step_id not in self._trees:
            raw = _git(self.repo, "ls-tree", "-r", "-z", self.step(step_id).sha)
            tree: dict[str, str] = {}
            for entry in raw.split(b"\0"):
                if not entry:
                    continue
                meta, path = entry.split(b"\t", 1)
                _mode, kind, sha = meta.split()
                if kind == b"blob":
                    tree[path.decode()] = sha.decode()
            self._trees[step_id] = tree
            self._fetch(set(tree.values()) - set(self._blobs))
        return self._trees[step_id]

    def _fetch(self, shas: set[str]) -> None:
        if not shas:
            return
        ordered = sorted(shas)
        out = _git(self.repo, "cat-file", "--batch", stdin="\n".join(ordered).encode() + b"\n")
        pos = 0
        for _ in ordered:
            header_end = out.index(b"\n", pos)
            sha, _kind, size = out[pos:header_end].split()
            start = header_end + 1
            self._blobs[sha.decode()] = out[start : start + int(size)]
            pos = start + int(size) + 1

    def content_at(self, path: str, step_id: str) -> bytes | None:
        sha = self.tree(step_id).get(path)
        return None if sha is None else self._blobs[sha]

    def active_paths_at(self, step_id: str) -> set[str]:
        return set(self.tree(step_id))

    def step_of_checkout(self, checkout: Path) -> str | None:
        """The latest step whose tree equals `checkout`'s files exactly."""
        files = {
            p.relative_to(checkout).as_posix(): blob_sha(p.read_bytes())
            for p in checkout.rglob("*")
            if p.is_file()
        }
        for step in reversed(self.steps):
            if self.tree(step.id) == files:
                return step.id
        return None

    def last_change(self, path: str, step_id: str) -> Step | None:
        """The last step at or before `step_id` where `path`'s blob changed."""
        index = self.step_ids.index(step_id)
        current = self.tree(step_id).get(path)
        if current is None:
            return None
        found = self.steps[index]
        for earlier in reversed(self.steps[:index]):
            if self.tree(earlier.id).get(path) != current:
                break
            found = earlier
        return found

    def services(self, step_id: str) -> list[str]:
        """Top-level directories holding code, minus test and docs trees."""
        tops = {p.split("/", 1)[0] for p in self.tree(step_id) if "/" in p}
        return sorted(t for t in tops if t not in _NOT_SERVICES and not t.startswith("."))
