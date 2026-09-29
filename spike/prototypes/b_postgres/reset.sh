#!/usr/bin/env bash
# Resets stack B: `docker compose down -v` (the stack and its named volume),
# then starts it again empty and waits for the health check, so
# `bench/run.py --reset --prototype b_postgres` can ingest straight after.
# `reset.sh --down` stops at the first half. Uses the `docker compose`
# plugin when the CLI has it, else the standalone `docker-compose`.
set -euo pipefail
cd "$(dirname "$0")"
if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
else
  compose=(docker-compose)
fi
"${compose[@]}" down -v
if [[ "${1:-}" != "--down" ]]; then
  "${compose[@]}" up -d --wait
fi
