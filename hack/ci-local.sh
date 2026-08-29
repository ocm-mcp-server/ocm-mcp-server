#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# Run the exact checks the GitHub Actions `ci` test job runs, in the same order,
# with the same invocations (bare `pytest`, not `python -m pytest` — the two
# resolve imports differently, which is how green-local/red-CI drift happens).
#
# Usage:
#   ./hack/ci-local.sh          # run all checks
#
# Install as a pre-push gate:
#   git config core.hooksPath hack/githooks
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# Bare invocations above are deliberate — they match CI. But "bare" means
# "whatever is on PATH", and PATH can belong to a DIFFERENT project. That has
# happened: `ruff` resolved to another repository's tooling venv, a version
# behind this one, and failed on code this project's own ruff accepts. The
# result looks like a real lint error and is not.
#
# So: bare invocation, but assert first that each tool actually comes from
# this project. Fail loudly and name the intruder rather than reporting a
# confusing lint failure.
require_local_tool() {
  local tool="$1" resolved
  resolved="$(command -v "$tool" 2>/dev/null)" || {
    printf '\033[1;31m%s is not on PATH.\033[0m Activate this project'"'"'s venv first.\n' "$tool" >&2
    exit 1
  }
  resolved="$(cd "$(dirname "$resolved")" && pwd)/$(basename "$resolved")"

  # The tool must live inside this repository. A project venv at .venv/
  # satisfies that; another project's venv does not, even when it is the
  # ACTIVE one. An earlier version of this guard also accepted anything under
  # $VIRTUAL_ENV, which defeated the whole check the moment a sibling
  # project's venv happened to be activated -- exactly the case it exists to
  # catch.
  case "$resolved" in
    "$PWD"/*) return 0 ;;
  esac

  printf '\033[1;31m%s resolves outside this project:\033[0m %s\n' "$tool" "$resolved" >&2
  printf 'CI runs the version pinned in hack/requirements/, so a foreign %s produces\n' "$tool" >&2
  printf 'results CI will not reproduce. Use this project'"'"'s own environment:\n\n' >&2
  printf '  python3 -m venv .venv \\\n' >&2
  printf '    && .venv/bin/pip install -e ".[dev]" \\\n' >&2
  printf '    && source .venv/bin/activate\n\n' >&2
  printf 'If you genuinely mean to use an out-of-tree toolchain, say so explicitly:\n' >&2
  printf '  CI_LOCAL_ALLOW_FOREIGN_TOOLS=1 ./hack/ci-local.sh\n\n' >&2
  exit 1
}

if [[ "${CI_LOCAL_ALLOW_FOREIGN_TOOLS:-0}" != "1" ]]; then
  for tool in ruff mypy pytest; do require_local_tool "$tool"; done
fi

step "Lint (ruff check)"
ruff check src tests eval hack

step "Format check (ruff format --check)"
ruff format --check src tests eval

step "Type check (mypy)"
mypy

step "Unit tests + coverage gate (bare pytest, as CI runs it)"
pytest -q --cov=ocm_mcp_server --cov-report=term-missing --cov-fail-under=95

step "Shell syntax"
bash -n hack/*.sh chaos/inject.sh chaos/scenarios/*.sh

step "Docs stats drift check (quoted counts match reality)"
python3 hack/docs_stats.py --check

printf '\n\033[1;32mAll CI checks passed — safe to push.\033[0m\n'
