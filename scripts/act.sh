#!/usr/bin/env bash
# Every act call goes through here. act does not read Docker contexts, so it
# is handed the active context's socket unless DOCKER_HOST already names one.
set -euo pipefail
cd "$(dirname "$0")/.."
export DOCKER_HOST="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}"
exec act "$@"
