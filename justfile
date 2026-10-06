# asbuilt: while the repository is a spike, its pipeline runs on this machine.
# AGENTS.md says what a green run permits.

default:
    @just --list --unsorted

# One-time per machine: confirm the tools and the shared git hooks are present
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    for tool in uv act actionlint docker; do
      command -v "$tool" >/dev/null || { echo "missing: $tool (brew install $tool)"; exit 1; }
    done
    docker info >/dev/null 2>&1 || { echo "Docker is not reachable; start it first"; exit 1; }
    hooks=$(git config --get core.hooksPath || true)
    [ -n "$hooks" ] && [ -x "$hooks/pre-commit" ] || { echo "the shared git hooks are not wired: run hooks/install.sh in the konyklabs workspace"; exit 1; }
    echo "tools present: $(uv --version), $(act --version), actionlint $(actionlint --version | head -1); hooks at $hooks"

# The check, natively: workflow lint, shell syntax, ruff, the spike's tests
check:
    @scripts/check.sh

# The merge evidence: the check natively, then again as a workflow in a clean container
ci *args: check
    @scripts/act.sh workflow_dispatch -W .github/workflows/ci.yml {{args}}
