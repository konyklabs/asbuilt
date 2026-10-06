from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from bench.run import RunError, assemble_ingest_root, main, pipeline_models_missing
from tests._support import MINI_ROOT


def test_run_null_on_mini_writes_results_file(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results-null.json"
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--prototype", "null", "--fixture", str(MINI_ROOT), "--out", str(out_path)])

    assert exit_code == 0
    assert out_path.is_file()

    data = json.loads(out_path.read_text())
    assert data["prototype"] == "null"
    assert {q["surface"] for q in data["queries"]} == {
        "explain",
        "search",
        "ask",
        "contradictions",
        "stale",
    }
    assert data["ingest"]["documents"] > 0
    assert all(q["result"] in ([], {"sentences": []}) for q in data["queries"])


def test_run_only_surfaces_restricts_the_query_mix(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results-null.json"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--prototype",
            "null",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(out_path),
            "--only-surfaces",
            "explain,stale",
        ]
    )

    assert exit_code == 0
    data = json.loads(out_path.read_text())
    assert {q["surface"] for q in data["queries"]} == {"explain", "stale"}


def test_run_transcript_writes_one_section_per_query(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results-null.json"
    transcript_path = tmp_path / "transcripts" / "null-c4.md"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--prototype",
            "null",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(out_path),
            "--transcript",
            str(transcript_path),
        ]
    )

    assert exit_code == 0
    assert transcript_path.is_file()
    text = transcript_path.read_text()
    assert text.startswith("# null @ c4")
    assert "## q-explain-1 — explain('member-free-minutes')" in text
    assert "## q-ask-1 — ask('How many free minutes does a member get?')" in text
    assert "(no facts)" in text  # the null prototype answers nothing
    assert "(no answer)" in text


def test_assemble_ingest_root_excludes_truth_and_queries(tmp_path: Path):
    ingest_root = tmp_path / "ingest"
    result = assemble_ingest_root(MINI_ROOT, "c2", ingest_root)
    assert result == ingest_root

    all_paths = {
        p.relative_to(ingest_root).as_posix() for p in ingest_root.rglob("*") if p.is_file()
    }
    assert not any("truth" in p for p in all_paths)
    assert not any(p.startswith("queries/") for p in all_paths)
    assert (ingest_root / "repo" / "farebox" / "pricing.py").is_file()
    assert (ingest_root / "sources" / "wiki" / "pricing-rules.md").is_file()


def test_assemble_ingest_root_content_matches_step_and_absent_files(tmp_path: Path):
    ingest_root = tmp_path / "ingest"
    assemble_ingest_root(MINI_ROOT, "c2", ingest_root)
    assert "FREE_MINUTES = 25" in (ingest_root / "repo" / "farebox" / "pricing.py").read_text()
    assert not (ingest_root / "repo" / "farebox" / "refunds.py").exists()  # .absent through c2


def test_assemble_ingest_root_only_includes_runs_through_step(tmp_path: Path):
    ingest_root = tmp_path / "ingest"
    assemble_ingest_root(MINI_ROOT, "c2", ingest_root)
    steps_present = {
        json.loads(p.read_text())["metadata"]["step"]
        for p in (ingest_root / "runs").glob("pytest-*.json")
    }
    assert steps_present == {"c1", "c2"}


def test_run_through_step_is_recorded_and_limits_ingest(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results.json"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--prototype",
            "null",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(out_path),
            "--through-step",
            "c1",
        ]
    )
    assert exit_code == 0
    data = json.loads(out_path.read_text())
    assert data["through_step"] == "c1"
    # c1 only: fewer runs/ + no refunds.py -> fewer documents than the default (through c4).
    exit_code_full = main(
        ["--prototype", "null", "--fixture", str(MINI_ROOT), "--out", str(tmp_path / "full.json")]
    )
    assert exit_code_full == 0
    full = json.loads((tmp_path / "full.json").read_text())
    assert data["ingest"]["documents"] < full["ingest"]["documents"]


def test_run_query_latency_fields_use_repeats(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results.json"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--prototype",
            "null",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(out_path),
            "--repeats",
            "3",
        ]
    )
    assert exit_code == 0
    data = json.loads(out_path.read_text())
    for q in data["queries"]:
        assert q["warm_repeats"] == 3
        assert q["cold_ms"] >= 0
        assert q["latency_ms"] == q["cold_ms"]
        assert q["p50_ms"] is not None
        assert q["p95_ms"] is not None


def test_run_budget_tokens_sets_env(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASBUILT_BUDGET_TOKENS", raising=False)
    out_path = tmp_path / "results.json"

    exit_code = main(
        [
            "--prototype",
            "null",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(out_path),
            "--budget-tokens",
            "1000",
        ]
    )
    assert exit_code == 0
    assert os.environ["ASBUILT_BUDGET_TOKENS"] == "1000"


def test_run_reset_flag_only_touches_the_given_fixture_root(tmp_path: Path, monkeypatch, capsys):
    """--reset must reset scoped to --fixture, never the real spike/ tree —
    see run.py's comment on the reset_arm(spike_root=fixture_root) call."""
    import shutil

    fixture = tmp_path / "fixture"
    shutil.copytree(MINI_ROOT, fixture)
    (fixture / "build" / "ingest").mkdir(parents=True)
    (fixture / "build" / "ingest" / "leftover.txt").write_text("stale\n")

    monkeypatch.chdir(tmp_path)
    out_path = tmp_path / "results.json"
    exit_code = main(
        ["--prototype", "null", "--fixture", str(fixture), "--out", str(out_path), "--reset"]
    )
    assert exit_code == 0
    assert not (fixture / "build" / "ingest" / "leftover.txt").exists()
    captured = capsys.readouterr()
    assert "cleared build/ingest" in captured.out


def test_assemble_ingest_root_raises_on_invalid_json_run_report(tmp_path: Path):
    fixture = tmp_path / "fixture"
    shutil.copytree(MINI_ROOT, fixture)
    (fixture / "runs" / "broken.json").write_text("not json{")
    with pytest.raises(RunError):
        assemble_ingest_root(fixture, "c2", tmp_path / "ingest")


def test_assemble_ingest_root_raises_on_missing_metadata_step(tmp_path: Path):
    fixture = tmp_path / "fixture"
    shutil.copytree(MINI_ROOT, fixture)
    (fixture / "runs" / "no-step.json").write_text(json.dumps({"metadata": {}}))
    with pytest.raises(RunError):
        assemble_ingest_root(fixture, "c2", tmp_path / "ingest")


def test_run_incremental_records_both_reports_and_delta(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results.json"
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "--prototype",
            "null",
            "--fixture",
            str(MINI_ROOT),
            "--out",
            str(out_path),
            "--incremental",
            "--repeats",
            "1",
        ]
    )
    assert exit_code == 0
    data = json.loads(out_path.read_text())
    assert data["phase"] == "incremental"
    assert data["through_step"] == "c4"  # the mini fixture's last step

    inc = data["ingest_incremental"]
    assert inc["through_step_1"] == "c3"  # second-to-last
    assert inc["through_step_2"] == "c4"
    assert set(inc["delta"]) == {"seconds", "input_tokens", "output_tokens", "dollars", "calls"}
    assert inc["report_1"]["documents"] > 0
    assert inc["report_2"]["documents"] > 0


def test_run_full_phase_is_recorded_as_full(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "results.json"
    monkeypatch.chdir(tmp_path)
    exit_code = main(["--prototype", "null", "--fixture", str(MINI_ROOT), "--out", str(out_path)])
    assert exit_code == 0
    data = json.loads(out_path.read_text())
    assert data["phase"] == "full"
    assert "ingest_incremental" not in data


def test_a_pipeline_arm_refuses_the_fallback_models_unless_asked(monkeypatch, capsys):
    """konyklabs/roadmap#154, 2026-10-06: a 198-call stack-B run ingested with
    the hash embedder and no NLI because the `pipeline` extra was absent, and
    nothing said so until the results file. With sentence-transformers made
    unimportable here, the run exits 2 before any call; asking for both
    fallbacks explicitly lets it through; the null arm never needs them."""
    import sys

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import -> ImportError
    monkeypatch.delenv("ASBUILT_EMBED", raising=False)
    monkeypatch.delenv("ASBUILT_NLI", raising=False)

    reason = pipeline_models_missing("b_postgres")
    assert reason is not None and "uv run --extra pipeline" in reason
    assert pipeline_models_missing("null") is None
    assert pipeline_models_missing("baseline") is None

    assert main(["--prototype", "b_postgres", "--fixture", str(MINI_ROOT)]) == 2
    assert "sentence-transformers is not importable" in capsys.readouterr().err

    assert pipeline_models_missing("b_postgres", {"ASBUILT_EMBED": "fake"}) is not None
    assert (
        pipeline_models_missing("b_postgres", {"ASBUILT_EMBED": "fake", "ASBUILT_NLI": "off"})
        is None
    )
