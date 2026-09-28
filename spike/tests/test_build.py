from __future__ import annotations

import subprocess
from pathlib import Path

from bench.build import Timeline, _isolated_git_env, build
from tests._support import MINI_ROOT, git_show


def test_isolated_git_env_drops_git_vars_and_isolates_config(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Should Be Dropped")
    monkeypatch.setenv("GIT_SOME_OTHER_VAR", "also dropped")
    monkeypatch.setenv("PATH", "/usr/bin")  # a non-GIT var must survive

    env = _isolated_git_env()

    assert "GIT_AUTHOR_NAME" not in env
    assert "GIT_SOME_OTHER_VAR" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_build_is_reproducible(tmp_path: Path):
    commits_a = build(MINI_ROOT, tmp_path / "out-a")
    commits_b = build(MINI_ROOT, tmp_path / "out-b")

    assert commits_a == commits_b
    assert set(commits_a) == {"c1", "c2", "c3", "c4"}
    assert len({info["sha"] for info in commits_a.values()}) == 4


def test_overlay_rule_two_overlays_plus_final(tmp_path: Path):
    """farebox/pricing.py: overlay at c1 (15, a one-step run), overlay at c3
    (25, covering c2-c3 — content at step k is the overlay at the smallest
    step >= k), then final content (15) from c4 onward."""
    commits = build(MINI_ROOT, tmp_path / "out")
    repo = tmp_path / "out" / "repo"

    def pricing_at(step_id: str) -> str:
        return git_show(repo, commits[step_id]["sha"], "farebox/pricing.py").decode()

    assert "FREE_MINUTES = 15" in pricing_at("c1")
    assert "FREE_MINUTES = 25" in pricing_at("c2")  # smallest j>=k with an entry is c3
    assert "FREE_MINUTES = 25" in pricing_at("c3")  # its own overlay
    assert "FREE_MINUTES = 15" in pricing_at("c4")  # no entry at/after c4 -> final

    # A file with no overlay at all (pyproject.toml) is identical at every step.
    c1_pyproject = git_show(repo, commits["c1"]["sha"], "pyproject.toml")
    c4_pyproject = git_show(repo, commits["c4"]["sha"], "pyproject.toml")
    assert c1_pyproject == c4_pyproject

    assert commits["c1"]["date"] == "2026-01-01T09:00:00-05:00"
    assert commits["c4"]["message"] == "End the trial promotion: member free minutes back to 15"


def test_absent_marker(tmp_path: Path):
    """farebox/refunds.py: history/c2/farebox/refunds.py.absent means the path
    does not exist through c2 (so not at c1 or c2 either); it first appears
    at c3, taking final content (no overlay of its own)."""
    commits = build(MINI_ROOT, tmp_path / "out")
    repo = tmp_path / "out" / "repo"

    for step_id in ("c1", "c2"):
        result = subprocess.run(
            ["git", "show", f"{commits[step_id]['sha']}:farebox/refunds.py"],
            cwd=repo,
            capture_output=True,
        )
        assert result.returncode != 0

    c3_refunds = git_show(repo, commits["c3"]["sha"], "farebox/refunds.py").decode()
    c4_refunds = git_show(repo, commits["c4"]["sha"], "farebox/refunds.py").decode()
    assert "REFUND_FEE = 5" in c3_refunds
    assert c3_refunds == c4_refunds


def test_timeline_content_at_matches_build(tmp_path: Path):
    """Timeline.content_at (used directly by check_consistency, without a
    build) agrees with what actually gets committed."""
    commits = build(MINI_ROOT, tmp_path / "out")
    repo = tmp_path / "out" / "repo"
    timeline = Timeline(MINI_ROOT)

    for step_id in ("c1", "c2", "c3", "c4"):
        expected = git_show(repo, commits[step_id]["sha"], "farebox/pricing.py")
        assert timeline.content_at("farebox/pricing.py", step_id) == expected

    assert timeline.content_at("farebox/refunds.py", "c1") is None
    assert timeline.content_at("farebox/refunds.py", "c2") is None
    assert timeline.content_at("farebox/refunds.py", "c3") is not None


def test_excluded_dirs_never_become_fixture_content(tmp_path: Path):
    """node_modules/, .ruff_cache/ and friends can show up under system/ from
    running the fixture's own code locally; they must never be committed."""
    fixture = tmp_path / "fixture"
    system = fixture / "system"
    (system / "farebox").mkdir(parents=True)
    (system / "farebox" / "pricing.py").write_text("FREE_MINUTES = 1\n")
    (system / "node_modules" / "left-over").mkdir(parents=True)
    (system / "node_modules" / "left-over" / "index.js").write_text("module.exports = 1;\n")
    (system / ".ruff_cache").mkdir(parents=True)
    (system / ".ruff_cache" / "cache-entry").write_text("junk\n")
    history = system / "history"
    history.mkdir()
    (history / "steps.yaml").write_text(
        '- id: c1\n  date: "2026-01-01T00:00:00-05:00"\n  message: "only commit"\n'
    )

    commits = build(fixture, tmp_path / "out")
    repo = tmp_path / "out" / "repo"
    tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commits["c1"]["sha"]],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert tracked == ["farebox/pricing.py"]
