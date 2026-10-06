#!/usr/bin/env bash
# The one definition of green. `just check`, `just ci` and the workflow in
# .github/workflows/ci.yml all run this file, so a change passes or fails the
# same way natively and in the container.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
ok()  { printf 'ok    %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*"; fail=1; }
# The container's checkout is owned by another user; without this git refuses it.
g()   { git -c safe.directory="$PWD" "$@"; }

# What was checked. Output pasted into a pull request has to name its commit,
# and a tree with uncommitted paths is not the commit it names.
if sha=$(g rev-parse --short=12 HEAD 2>/dev/null); then
  dirty=$(g status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [ "$dirty" -eq 0 ]; then tree="tree clean"; else tree="tree has $dirty uncommitted path(s)"; fi
  printf 'check %s, %s, %s %s\n' "$sha" "$tree" "$(uname -s)" "$(uname -m)"
else
  printf 'check: commit unknown (not a git checkout), %s %s\n' "$(uname -s)" "$(uname -m)"
fi

# 1. The workflows are valid Actions syntax.
if command -v actionlint >/dev/null 2>&1; then
  # actionlint also runs shellcheck over `run:` blocks when shellcheck is on
  # PATH. The runner image has none, so say which mode this run was in.
  sc=off; command -v shellcheck >/dev/null 2>&1 && sc=on
  if actionlint -no-color; then
    ok "workflows lint (actionlint $(actionlint --version | head -1), shellcheck $sc)"
  else
    bad "actionlint reported problems"
  fi
else
  bad "actionlint is not installed (brew install actionlint)"
fi

# 2. Every tracked shell script parses.
n=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  head -1 "$f" | grep -q -E '^#!.*\b(ba)?sh\b' || continue
  n=$((n + 1))
  bash -n "$f" || bad "shell syntax: $f"
done < <(g ls-files 2>/dev/null)
if [ "$n" -gt 0 ]; then ok "shell syntax ($n scripts)"; else bad "shell syntax: found no scripts to check, not even this one"; fi

# 3 and 4. The spike: lint, format, tests. --locked fails on a stale uv.lock
# instead of quietly resolving a different set of packages.
if command -v uv >/dev/null 2>&1; then
  if (cd spike && uv run --locked ruff check .); then ok "ruff check"; else bad "ruff check"; fi
  if (cd spike && uv run --locked ruff format --check .); then ok "ruff format"; else bad "ruff format --check"; fi
  # Tests marked `postgres` start a throwaway container and skip themselves,
  # with the reason printed, where Docker does not answer.
  if (cd spike && uv run --locked pytest -q -p no:cacheprovider); then ok "pytest"; else bad "pytest"; fi
else
  bad "uv is not installed (brew install uv)"
fi

if [ "$fail" -ne 0 ]; then echo "check: FAILED"; exit 1; fi
echo "check: green"
