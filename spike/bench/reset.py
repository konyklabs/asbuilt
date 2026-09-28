"""Resets a benchmark arm between runs (D-013).

Runs the arm's own documented reset — ``prototypes/<name>/reset.sh`` if
present, else ``docker compose down -v`` in that directory if it has a
``docker-compose.yml`` — then clears ``build/ingest/`` so the next run
starts from nothing. ``null`` has no store to reset; only ``build/ingest/``
is cleared. Operational convention (not enforced here): only one arm's
compose stack runs at a time.

CLI: ``uv run python bench/reset.py --arm <name>``. ``bench/run.py --reset``
calls ``reset_arm`` first, before assembling the ingest root.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent.parent


def _clear_ingest(spike_root: Path) -> None:
    ingest_dir = spike_root / "build" / "ingest"
    if ingest_dir.exists():
        shutil.rmtree(ingest_dir)


def reset_arm(name: str, spike_root: Path = SPIKE_ROOT) -> str:
    """Runs `name`'s documented reset, then clears build/ingest/. Returns a
    short description of what ran, for the caller to print."""
    if name == "null":
        _clear_ingest(spike_root)
        return "null: no store to reset; cleared build/ingest/"

    arm_dir = spike_root / "prototypes" / name
    reset_script = arm_dir / "reset.sh"
    compose_file = arm_dir / "docker-compose.yml"

    if reset_script.is_file():
        subprocess.run(["bash", str(reset_script)], cwd=arm_dir, check=True)
        action = f"ran {reset_script.relative_to(spike_root)}"
    elif compose_file.is_file():
        subprocess.run(["docker", "compose", "down", "-v"], cwd=arm_dir, check=True)
        action = f"ran docker compose down -v in {arm_dir.relative_to(spike_root)}"
    else:
        action = f"{name}: no reset.sh or docker-compose.yml under {arm_dir}; nothing to reset"

    _clear_ingest(spike_root)
    return f"{action}; cleared build/ingest/"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, help='"null" or a name under prototypes/')
    args = parser.parse_args(argv)

    print(reset_arm(args.arm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
