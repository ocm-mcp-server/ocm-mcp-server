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

say "Bumping version to $v (pyproject.toml + server.json + __init__ + Helm chart)"
python3 - "$v" <<'PY'
import json, re, sys

v = sys.argv[1]


def sub_file(path, pattern, repl, count=1):
    text = open(path).read()
    text, n = re.subn(pattern, repl, text, count=count)
    assert n == count, f"expected {count} match(es) for {pattern!r} in {path}, got {n}"
    open(path, "w").write(text)


sub_file("pyproject.toml", r'(?m)^version = "[^"]+"$', f'version = "{v}"')
sub_file(
    "src/ocm_mcp_server/__init__.py",
    r'(?m)^__version__ = "[^"]+"$',
    f'__version__ = "{v}"',
)
sub_file("deploy/charts/ocm-mcp-server/Chart.yaml", r'(?m)^version: [^\s]+$', f"version: {v}")
sub_file(
    "deploy/charts/ocm-mcp-server/Chart.yaml",
    r'(?m)^appVersion: "[^"]+"$',
    f'appVersion: "{v}"',
)
sub_file(
    "deploy/charts/ocm-mcp-server/values.yaml",
    r'(?m)^(\s*)tag: v[^\s]+$',
    rf"\g<1>tag: v{v}",
)

s = json.load(open("server.json"))
s["version"] = v
for pkg in s["packages"]:
    if pkg.get("registryType") == "oci":
        # Registry schema: OCI packages carry the version in the identifier
        # tag and must NOT have a separate "version" field.
        base = pkg["identifier"].rsplit(":", 1)[0]
        pkg["identifier"] = f"{base}:{v}"
        pkg.pop("version", None)
    else:
        pkg["version"] = v
open("server.json", "w").write(json.dumps(s, indent=2) + "\n")
PY

say "Running the CI-identical gate"
./hack/ci-local.sh

say "Committing, tagging v$v, pushing"
git add pyproject.toml server.json src/ocm_mcp_server/__init__.py \
  deploy/charts/ocm-mcp-server/Chart.yaml deploy/charts/ocm-mcp-server/values.yaml
git commit -m "release: v$v"
git tag -a "v$v" -m "v$v"
git push origin main "v$v"

say "Done - the tag pipeline now publishes: GitHub Release, PyPI, MCP Registry, signed image"
echo "watch: https://github.com/sandeepbazar/ocm-mcp-server/actions"
