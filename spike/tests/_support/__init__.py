"""Shared test helpers. A package (not conftest.py) per the layout convention."""

from __future__ import annotations

import subprocess
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent.parent.parent
MINI_ROOT = SPIKE_ROOT / "tests" / "fixtures" / "mini"


def git_show(repo: Path, sha: str, path: str) -> bytes:
    """Content of `path` at `sha`, read via `git show` (no working-tree checkout)."""
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return result.stdout
