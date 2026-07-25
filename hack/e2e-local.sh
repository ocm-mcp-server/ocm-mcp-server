#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# One-command local end-to-end test for ocm-mcp-server.
#
#   1. installs/verifies dependencies (podman, kind, kubectl, clusteradm, helm, oc)
#   2. brings up a real Open Cluster Management fleet on kind (1 hub + N spokes)
#   3. exercises every tool and prompt, the gated write flow, and a negative
#      scenario (break something, then debug + fix it end to end)
#   4. writes a detailed, graphical HTML report next to the repo (git-ignored)
#   5. tears the fleet back down (kind and podman stay installed)
#
# Platforms: macOS (Homebrew + Podman) and Linux (podman/docker + package manager).
# Docker works too - the engine is auto-detected (or set CONTAINER_ENGINE=docker).
#
# Usage:
#   ./hack/e2e-local.sh                 # 2 spokes, full run, auto-cleanup
#   SPOKES=1 ./hack/e2e-local.sh        # lighter
#   E2E_KEEP=1 ./hack/e2e-local.sh      # keep the fleet up after the run
set -uo pipefail

SPOKES="${SPOKES:-2}"
SAMPLE_CLUSTER="cluster1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/.e2e-run"
RESULTS="$RUN_DIR/results.jsonl"
REPORT="$ROOT/e2e-report.html"
OS="$(uname -s)"

b(){ printf '\n\033[1;36m========== %s ==========\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
info(){ printf '\033[0;90m  • %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m  ! %s\033[0m\n' "$*"; }

mkdir -p "$RUN_DIR"; : > "$RESULTS"

# Append one JSON record for the HTML report (python handles escaping).
rec(){ PHASE="$1" TITLE="$2" WHY="$3" STATUS="$4" CMD="${5:-}" OUTPUT="${6:-}" \
  python3 - "$RESULTS" <<'PY'
import json,os,sys
open(sys.argv[1],"a").write(json.dumps({k:os.environ.get(k.upper(),"") for k in
  ["phase","title","why","status","cmd","output"]})+"\n")
PY
}

PYBIN="$ROOT/.venv/bin/python"

cleanup(){
  if [[ "${E2E_KEEP:-0}" == "1" ]]; then
    warn "E2E_KEEP=1 set - leaving the fleet up. Tear down later with: SPOKES=$SPOKES CONTAINER_ENGINE=podman ./hack/teardown.sh"
    return
  fi
  b "9. Cleanup - deleting the test fleet (kind and podman stay installed)"
  local out; out="$(SPOKES="$SPOKES" CONTAINER_ENGINE="${ENGINE:-podman}" bash "$ROOT/hack/teardown.sh" 2>&1)"
  echo "$out" | sed 's/^/  /'
  rec "9. Cleanup" "teardown.sh" "Delete every kind cluster and stale context created by this run; the container engine and CLIs remain." OK "./hack/teardown.sh" "$out"
  [[ -n "${PYBIN:-}" && -x "$PYBIN" ]] && "$PYBIN" "$ROOT/hack/e2e_report.py" --results "$RESULTS" --out "$REPORT" >/dev/null 2>&1
  printf '\n\033[1;32m==> HTML report: %s\033[0m\n' "$REPORT"
}
trap cleanup EXIT

# ---------------------------------------------------------------- 1. dependencies
b "1. Dependencies - install if missing, otherwise show the installed version"

brew_install(){ command -v brew >/dev/null 2>&1 && brew install "$1" >/dev/null 2>&1; }

dep(){  # name  "version command"  "brew formula"  required(yes/no)
  local name="$1" vcmd="$2" formula="$3" req="${4:-yes}"
  if command -v "$name" >/dev/null 2>&1; then
    local ver; ver="$(eval "$vcmd" 2>/dev/null | head -1)"
    ok "$name already installed - $ver"
    rec "1. Dependencies" "$name" "Required tool for the local fleet." OK "$vcmd" "already installed: $ver"
  else
    info "$name missing - installing..."
    if [[ "$OS" == "Darwin" ]]; then brew_install "$formula"; fi
    if command -v "$name" >/dev/null 2>&1; then
      local ver; ver="$(eval "$vcmd" 2>/dev/null | head -1)"
      ok "$name installed - $ver"
      rec "1. Dependencies" "$name" "Required tool for the local fleet." OK "$vcmd" "installed now: $ver"
    else
      warn "$name could not be installed automatically"
      rec "1. Dependencies" "$name" "Required tool for the local fleet." \
        "$([[ $req == yes ]] && echo FAIL || echo SKIP)" "" "not installed; install it manually (see script header)"
      [[ "$req" == "yes" ]] && { echo "FATAL: $name is required."; exit 1; }
    fi
  fi
}

dep podman   "podman --version"                 podman         yes
dep kind     "kind version"                     kind           yes
dep kubectl  "kubectl version --client=true -o yaml 2>/dev/null | grep gitVersion | head -1" kubernetes-cli yes
dep helm     "helm version --short"             helm           yes
# clusteradm has no Homebrew formula - install it from the official script if missing.
if ! command -v clusteradm >/dev/null 2>&1; then
  info "installing clusteradm from the official script..."
  DEST=/opt/homebrew/bin; [[ -w "$DEST" ]] || DEST=/usr/local/bin
  INSTALL_DIR="$DEST" curl -sL https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh | INSTALL_DIR="$DEST" bash >/dev/null 2>&1 || true
fi
dep clusteradm "clusteradm version | head -1"   ""             yes
dep oc       "oc version --client 2>/dev/null | head -1" openshift-cli no   # only needed for real OpenShift, not kind

# Python package (the server + its CLI)
b "2. Python package - install the server into a local virtualenv"
if [[ ! -x "$PYBIN" ]]; then info "creating .venv"; python3 -m venv "$ROOT/.venv"; fi
"$PYBIN" -m pip install -q --upgrade pip >/dev/null 2>&1
"$PYBIN" -m pip install -q -e "$ROOT" >/dev/null 2>&1
PKG_VER="$("$PYBIN" -c 'import ocm_mcp_server, importlib.metadata as m; print("ocm-mcp-server", m.version("ocm-mcp-server"))' 2>/dev/null || echo 'ocm-mcp-server (editable)')"
ok "installed $PKG_VER"
rec "2. Python package" "pip install -e ." "Install the MCP server and its ocm-mcp CLI into an isolated virtualenv." OK "pip install -e ." "$PKG_VER"

# ---------------------------------------------------------------- 3. container engine
b "3. Container engine - start Podman (Docker not required)"
ENGINE="${CONTAINER_ENGINE:-podman}"
if [[ "$ENGINE" == "podman" ]]; then
  if ! podman info >/dev/null 2>&1; then
    info "starting podman machine..."; podman machine start >/dev/null 2>&1 || podman machine init --now >/dev/null 2>&1
  fi
  export KIND_EXPERIMENTAL_PROVIDER=podman
fi
ENGVER="$("$ENGINE" version --format '{{.Client.Version}}' 2>/dev/null || "$ENGINE" --version)"
if "$ENGINE" info >/dev/null 2>&1; then
  ok "$ENGINE is running ($ENGVER)"
  rec "3. Container engine" "$ENGINE running" "kind needs a container runtime; on this machine it is Podman (Docker is not required)." OK "$ENGINE info" "engine=$ENGINE version=$ENGVER"
else
  warn "$ENGINE is not running"; rec "3. Container engine" "$ENGINE" "Container runtime for kind." FAIL "$ENGINE info" "not running"; exit 1
fi

# ---------------------------------------------------------------- 4. bootstrap fleet
b "4. Bootstrap - 1 hub + $SPOKES spoke clusters, OCM, Kyverno, policies, demo app"
info "this is the long step (a few minutes): creating clusters and joining them to the hub"
BOOT_LOG="$RUN_DIR/bootstrap.log"
CONTAINER_ENGINE="$ENGINE" SPOKES="$SPOKES" bash "$ROOT/hack/bootstrap.sh" --no-jaeger > "$BOOT_LOG" 2>&1
BOOT_RC=$?
tail -6 "$BOOT_LOG" | sed 's/^/  /'

export OCM_MCP_HUB_CONTEXT="kind-hub"
SPOKE_MAP="$(for i in $(seq 1 "$SPOKES"); do printf 'cluster%d=kind-cluster%d,' "$i" "$i"; done | sed 's/,$//')"
export OCM_MCP_SPOKE_CONTEXTS="$SPOKE_MAP"
export OCM_MCP_HOME="$RUN_DIR/state"

# Judge success by the real signal - are the spokes Available? - not just the exit code,
# so a cosmetic non-zero exit does not show a false failure when the fleet is actually up.
MC="$(kubectl --context kind-hub get managedclusters 2>&1)"
AVAIL="$(echo "$MC" | awk '$5=="True"{n++} END{print n+0}')"
if [[ "$AVAIL" -ge "$SPOKES" ]]; then
  ok "fleet up: $AVAIL/$SPOKES spokes Available"
  rec "4. Bootstrap fleet" "bootstrap.sh" "Stand up a real OCM hub with spokes so every tool talks to genuine clusters, not mocks." OK "CONTAINER_ENGINE=$ENGINE SPOKES=$SPOKES ./hack/bootstrap.sh --no-jaeger" "$(tail -20 "$BOOT_LOG")"
else
  warn "only $AVAIL/$SPOKES spokes Available (bootstrap rc=$BOOT_RC)"
  rec "4. Bootstrap fleet" "bootstrap.sh" "Stand up a real OCM hub with spokes." FAIL "./hack/bootstrap.sh" "$(tail -30 "$BOOT_LOG")"
fi
echo "$MC" | sed 's/^/  /'
rec "4. Bootstrap fleet" "managed clusters" "Proof the spokes are registered and Available on the hub." OK "kubectl --context kind-hub get managedclusters" "$MC"

# ---------------------------------------------------------------- 5. exercise everything
b "5. Exercising tools, prompts, and a break-then-fix scenario"
"$PYBIN" "$ROOT/hack/e2e_tools.py" --results "$RESULTS" --spokes "$SPOKES" --cluster "$SAMPLE_CLUSTER"

# ---------------------------------------------------------------- 6. report
b "6. Rendering the HTML report"
"$PYBIN" "$ROOT/hack/e2e_report.py" --results "$RESULTS" --out "$REPORT"
ok "report ready: $REPORT"
# cleanup() runs on EXIT (unless E2E_KEEP=1) and regenerates the report with the teardown step.
