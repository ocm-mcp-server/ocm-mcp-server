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
