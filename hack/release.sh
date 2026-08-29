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

# --- Ownership drift ------------------------------------------------------
# A release depends on THREE things configured outside this repository: PyPI's
# trusted publisher, the MCP Registry namespace, and the GHCR package path.
# All three are keyed to the repository owner, and none of them moves when the
# repository is transferred. Transferring it once already left every one of
# them pointing at the previous owner. The failure surfaces mid-release, after
# the tag is pushed, which is the worst possible moment to discover it.
#
# So: check that this repo's own declarations agree with each other and with
# the remote, and make the human confirm the parts no script can see.

origin_slug="$(git remote get-url origin \
  | sed -E 's#(git@github\.com:|https://github\.com/)##; s#\.git$##')"
owner="${origin_slug%%/*}"

declared_server_name="$(python3 -c '
import json; print(json.load(open("server.json"))["name"])')"
expected_server_name="io.github.${owner}/ocm-mcp-server"
[[ "$declared_server_name" == "$expected_server_name" ]] || die \
  "server.json declares '$declared_server_name' but this repo is owned by '$owner'.
  The MCP Registry validates the listing against the repository, so it must be
  '$expected_server_name'. Fix server.json, the Dockerfile LABEL and
  .github/workflows/publish-image.yaml together - they must all agree."

for f in Dockerfile .github/workflows/publish-image.yaml; do
  grep -q "$expected_server_name" "$f" || die \
    "$f does not declare $expected_server_name - all three declarations must agree"
done
grep -rq "io\.github\.${owner}/ocm-mcp-server" server.json || die "server.json drifted"

# Scan TRACKED files only. Scratch output (browser dumps, _site/) legitimately
# contains historical strings and is not what ships.
bad_ghcr="$(git ls-files -z | xargs -0 grep -n "ghcr\.io/[a-z0-9-]*/ocm-mcp-server" 2>/dev/null \
  | grep -v "ghcr\.io/${owner}/ocm-mcp-server" || true)"
if [[ -n "$bad_ghcr" ]]; then
  printf '\033[1;31mERROR: a GHCR path does not match the current owner (%s):\033[0m\n' "$owner" >&2
  printf '%s\n' "$bad_ghcr" >&2
  exit 1
fi

bad_ns="$(git ls-files -z | xargs -0 grep -n "io\.github\.[a-z0-9-]*/ocm-mcp-server" 2>/dev/null \
  | grep -v "$expected_server_name" | grep -v '^wiki/Test-Results\.md' || true)"
if [[ -n "$bad_ns" ]]; then
  printf '\033[1;31mERROR: an MCP server name does not match the current owner (%s):\033[0m\n' "$owner" >&2
  printf '%s\n' "$bad_ns" >&2
  exit 1
fi

registry_listed="$(curl -fsS --max-time 20 \
  "https://registry.modelcontextprotocol.io/v0/servers?search=ocm-mcp-server" 2>/dev/null \
  | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin); rows=d.get("servers") or d.get("data") or []
    names={(r.get("server",r) or {}).get("name") for r in rows}
    print(sorted(n for n in names if n)[-1] if names else "")
except Exception: print("")' || echo "")"
if [[ -n "$registry_listed" && "$registry_listed" != "$expected_server_name" ]]; then
  printf '\033[1;33mWARNING: the MCP Registry currently lists %s\033[0m\n' "$registry_listed" >&2
  printf '         this release will publish %s\n' "$expected_server_name" >&2
  printf '         The io.github.<owner> namespace is owned by that GitHub account, so\n' >&2
  printf '         publishing under the new one requires authenticating as %s.\n\n' "$owner" >&2
fi

cat >&2 <<CONFIRM
\033[1;33mConfirm the three settings that live OUTSIDE this repository:\033[0m
  1. pypi.org -> ocm-mcp-server -> Settings -> Publishing
     trusted publisher must be ${origin_slug}, environment 'pypi'
  2. MCP Registry namespace must be ${expected_server_name}
  3. GHCR package must be under ghcr.io/${owner}

These are keyed to the repository owner and do NOT follow a transfer.
CONFIRM
if [[ -t 0 && "${RELEASE_ASSUME_EXTERNAL_OK:-0}" != "1" ]]; then
  read -r -p "All three confirmed? [y/N] " ok
  [[ "$ok" == "y" || "$ok" == "Y" ]] || die "aborted - confirm the external settings first"
fi

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
echo "watch: https://github.com/ocm-mcp-server/ocm-mcp-server/actions"
