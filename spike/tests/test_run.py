from __future__ import annotations

import json
from pathlib import Path

from bench.run import main
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
