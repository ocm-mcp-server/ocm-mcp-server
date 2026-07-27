#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# Cut a release in one command:
#   ./hack/release.sh 0.2.3        (or: make release VERSION=0.2.3)
#
# Bumps the version everywhere it lives (pyproject.toml + server.json), checks the
# CHANGELOG has a section for it, runs the CI-identical local gate, then commits,
# tags v<version>, and pushes. The tag triggers the release pipeline: GitHub
# Release -> PyPI (trusted publishing) -> official MCP Registry -> signed GHCR image.
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

v="${1:-}"
[[ -n "$v" ]] || die "usage: release.sh <version>, e.g. release.sh 0.2.3"
[[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be MAJOR.MINOR.PATCH, got '$v'"

cd "$(git rev-parse --show-toplevel)"

say "Preflight"
[[ "$(git branch --show-current)" == "main" ]] || die "releases are cut from main"
[[ -z "$(git status --porcelain)" ]] || die "working tree is not clean"
git fetch origin --quiet
[[ "$(git rev-parse main)" == "$(git rev-parse origin/main)" ]] \
  || die "main is not in sync with origin/main (pull or push first)"
git rev-parse -q --verify "refs/tags/v$v" >/dev/null && die "tag v$v already exists"
grep -q "^## \[$v\]" CHANGELOG.md \
  || die "CHANGELOG.md has no '## [$v]' section - write the changelog first"

say "Bumping version to $v (pyproject.toml + server.json)"
python3 - "$v" <<'PY'
import json, re, sys

v = sys.argv[1]

p = open("pyproject.toml").read()
p, n = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{v}"', p, count=1)
assert n == 1, "did not find exactly one version line in pyproject.toml"
open("pyproject.toml", "w").write(p)

s = json.load(open("server.json"))
s["version"] = v
for pkg in s["packages"]:
    pkg["version"] = v
open("server.json", "w").write(json.dumps(s, indent=2) + "\n")
PY

say "Running the CI-identical gate"
./hack/ci-local.sh

say "Committing, tagging v$v, pushing"
git add pyproject.toml server.json
git commit -m "release: v$v"
git tag -a "v$v" -m "v$v"
git push origin main "v$v"

say "Done - the tag pipeline now publishes: GitHub Release, PyPI, MCP Registry, signed image"
echo "watch: https://github.com/sandeepbazar/ocm-mcp-server/actions"
