"""Stack B's dry run (D-013: "a dry-run token count before any full run").

``uv run python -m prototypes.b_postgres --dry-run [--fixture .]
[--through-step c6]`` assembles the ingest root the harness would hand the
arm, builds every document-extraction prompt as ``ingest`` would on an empty
store, and prints the token and dollar estimate from the connector's stated
price table. It makes no model call and needs no database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

from bench.build import Timeline  # noqa: E402
from bench.run import ENTITY_KINDS, assemble_ingest_root  # noqa: E402
from pipeline.sources import read_text_sources  # noqa: E402
from prototypes.b_postgres.extract import dry_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--fixture", default=".")
    parser.add_argument("--through-step", default=None)
    args = parser.parse_args(argv)

    fixture = Path(args.fixture).resolve()
    step = args.through_step or Timeline(fixture).steps[-1].id
    root = assemble_ingest_root(fixture, step, SPIKE_ROOT / "build" / "b_postgres-dryrun")
    result = dry_run(read_text_sources(root), ENTITY_KINDS)
    print(
        f"b_postgres dry run through {step}: documents={result.documents} "
        f"input_tokens~{result.estimated_input_tokens} "
        f"output_tokens~{result.estimated_output_tokens} (assumed per document) "
        f"model={result.model} dollars~${result.estimated_dollars:.2f} "
        "(token-priced estimate; the claude-code provider bills the subscription)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
