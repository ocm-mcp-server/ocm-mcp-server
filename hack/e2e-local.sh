#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# One-command local end-to-end test for ocm-mcp-server.
#
#   1. installs/verifies dependencies (podman, kind, kubectl, clusteradm, helm, oc)
#   2. brings up a real Open Cluster Management fleet on kind (1 hub + N spokes)
#      and enriches it (policy add-on, ManifestWorkReplicaSet, fixtures) so every
#      tool has real data to return
#   3. exercises every tool and prompt, the REAL gated write flow, and a negative
#      scenario (break something, then debug + fix it end to end)
#   4. writes a detailed, graphical HTML report next to the repo (git-ignored),
#      and a wiki-friendly Markdown copy to wiki/Test-Results.md (committed)
#   5. tears down ONLY the clusters this run created (kind and podman stay installed)
#
# Safety: if a kind cluster named hub/cluster1..N already exists, the script refuses
# to run rather than adopt and later delete a cluster you did not create.
#
# Platforms: macOS (Homebrew + Podman) and Linux (podman/docker + package manager).
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
REPORT_MD="$ROOT/wiki/Test-Results.md"
CREATED="$RUN_DIR/created-clusters"
OS="$(uname -s)"
PYBIN="$ROOT/.venv/bin/python"

b(){ printf '\n\033[1;36m========== %s ==========\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m  \xe2\x9c\x93 %s\033[0m\n' "$*"; }
info(){ printf '\033[0;90m  \xe2\x80\xa2 %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m  ! %s\033[0m\n' "$*"; }

# Fresh server state (proposals, keys, audit log, anchors) every run: stale state
# from an older run/format would poison the audit-chain and anchor verification steps.
mkdir -p "$RUN_DIR"; : > "$RESULTS"; : > "$CREATED"; rm -rf "$RUN_DIR/state"

# Append one JSON record for the HTML report (python handles escaping).
rec(){ PHASE="$1" TITLE="$2" WHY="$3" STATUS="$4" CMD="${5:-}" OUTPUT="${6:-}" \
  python3 - "$RESULTS" <<'PY'
import json,os,sys
open(sys.argv[1],"a").write(json.dumps({k:os.environ.get(k.upper(),"") for k in
  ["phase","title","why","status","cmd","output"]})+"\n")
PY
}

# Redact bootstrap/join tokens before they ever reach the (shareable) report.
scrub(){ sed -E 's/(--hub-token|token=|--hub-token=)[[:space:]]*[A-Za-z0-9._-]+/\1 REDACTED/g'; }

cleanup(){
  if [[ "${E2E_KEEP:-0}" == "1" ]]; then
    warn "E2E_KEEP=1 - leaving the fleet up. Tear down later with: SPOKES=$SPOKES CONTAINER_ENGINE=${ENGINE:-podman} ./hack/teardown.sh"
  else
    b "11. Cleanup - deleting ONLY the clusters this run created"
    local deleted=""
    while read -r name; do
      [[ -z "$name" ]] && continue
      kind delete cluster --name "$name" >/dev/null 2>&1 || true
      kubectl config delete-context "kind-${name}" >/dev/null 2>&1 || true
      kubectl config delete-cluster "kind-${name}" >/dev/null 2>&1 || true
      kubectl config delete-user "kind-${name}" >/dev/null 2>&1 || true
      deleted="$deleted $name"
    done < "$CREATED"
    ok "deleted:${deleted:- (none)}   (kind and podman remain installed)"
    rec "11. Cleanup" "teardown" "Delete only the clusters created by this run (recorded in .e2e-run/created-clusters); never touch pre-existing clusters." OK "kind delete cluster --name ..." "deleted:${deleted:- none}"
  fi
  [[ -x "$PYBIN" ]] && "$PYBIN" "$ROOT/hack/e2e_report.py" --results "$RESULTS" --out "$REPORT" --md "$REPORT_MD" >/dev/null 2>&1
  printf '\n\033[1;32m==> HTML report: %s\033[0m\n' "$REPORT"
  printf '\033[1;32m==> Wiki report: %s\033[0m\n' "$REPORT_MD"
}

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
    [[ "$OS" == "Darwin" ]] && brew_install "$formula"
    if command -v "$name" >/dev/null 2>&1; then
      local ver; ver="$(eval "$vcmd" 2>/dev/null | head -1)"
      ok "$name installed - $ver"
      rec "1. Dependencies" "$name" "Required tool for the local fleet." OK "$vcmd" "installed now: $ver"
    else
      warn "$name could not be installed automatically"
      rec "1. Dependencies" "$name" "Required tool for the local fleet." "$([[ $req == yes ]] && echo FAIL || echo SKIP)" "" "not installed; install it manually (see script header)"
      [[ "$req" == "yes" ]] && { echo "FATAL: $name is required."; exit 1; }
    fi
  fi
}
if ! command -v clusteradm >/dev/null 2>&1; then
  info "installing clusteradm from the official script..."
  DEST=/opt/homebrew/bin; [[ -w "$DEST" ]] || DEST=/usr/local/bin
  INSTALL_DIR="$DEST" curl -sL https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh | INSTALL_DIR="$DEST" bash >/dev/null 2>&1 || true
fi
dep podman   "podman --version"                 podman         yes
dep kind     "kind version"                      kind           yes
dep kubectl  "kubectl version --client=true -o yaml 2>/dev/null | grep gitVersion | head -1" kubernetes-cli yes
dep helm     "helm version --short"              helm           yes
dep clusteradm "clusteradm version | head -1"    ""             yes
dep oc       "oc version --client 2>/dev/null | head -1" openshift-cli no

# ---------------------------------------------------------------- 2. python package
b "2. Python package - install the server into a local virtualenv"
[[ -x "$PYBIN" ]] || { info "creating .venv"; python3 -m venv "$ROOT/.venv"; }
"$PYBIN" -m pip install -q --upgrade pip >/dev/null 2>&1
if ! "$PYBIN" -m pip install -q -e "${ROOT}[tracing]" >/dev/null 2>&1; then
  warn "pip install -e .[tracing] FAILED"
  rec "2. Python package" "pip install -e .[tracing]" "Install the MCP server, its ocm-mcp CLI, and the OTel tracing extra (exercised by the tracing-export step)." FAIL "pip install -e .[tracing]" "editable install failed"
  cleanup; exit 1
fi
PKG_VER="$("$PYBIN" -c 'import importlib.metadata as m; print("ocm-mcp-server", m.version("ocm-mcp-server"))' 2>/dev/null || echo 'ocm-mcp-server (editable)')"
ok "installed $PKG_VER"
rec "2. Python package" "pip install -e ." "Install the MCP server and its ocm-mcp CLI into an isolated virtualenv." OK "pip install -e ." "$PKG_VER"

# ---------------------------------------------------------------- 3. container engine
b "3. Container engine - start Podman (Docker not required)"
ENGINE="${CONTAINER_ENGINE:-}"
if [[ -z "$ENGINE" ]]; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then ENGINE=docker
  else ENGINE=podman; fi
fi
if [[ "$ENGINE" == "podman" ]]; then
  podman info >/dev/null 2>&1 || { info "starting podman machine..."; podman machine start >/dev/null 2>&1 || podman machine init --now >/dev/null 2>&1; }
  export KIND_EXPERIMENTAL_PROVIDER=podman
fi
if "$ENGINE" info >/dev/null 2>&1; then
  ENGVER="$("$ENGINE" --version 2>/dev/null)"
  ok "$ENGINE is running ($ENGVER)"
  rec "3. Container engine" "$ENGINE running" "kind needs a container runtime; here it is Podman (Docker is not required)." OK "$ENGINE info" "$ENGVER"
else
  warn "$ENGINE is not running"; rec "3. Container engine" "$ENGINE" "Container runtime for kind." FAIL "$ENGINE info" "not running"; cleanup; exit 1
fi

# ---------------------------------------------------------------- 3b. safety guard
# Never adopt or delete a cluster we did not create. Refuse if any already exists.
NAMES=(hub); for i in $(seq 1 "$SPOKES"); do NAMES+=("cluster${i}"); done
PRE=()
for n in "${NAMES[@]}"; do
  "$ENGINE" ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "${n}-control-plane" && PRE+=("$n")
done
if [[ ${#PRE[@]} -gt 0 ]]; then
  warn "clusters already exist: ${PRE[*]}"
  echo "  Refusing to run so this test never deletes a cluster you created."
  echo "  Remove them first:  for c in ${PRE[*]}; do kind delete cluster --name \$c; done"
  exit 1   # trap not armed yet - nothing of ours to clean
fi
printf '%s\n' "${NAMES[@]}" > "$CREATED"   # these are ours to delete later
trap cleanup EXIT

# ---------------------------------------------------------------- 4. bootstrap fleet
b "4. Bootstrap - 1 hub + $SPOKES spoke clusters, OCM, Kyverno, policies, demo app"
info "this is the long step (a few minutes): creating clusters and joining them to the hub"
BOOT_LOG="$RUN_DIR/bootstrap.log"
CONTAINER_ENGINE="$ENGINE" SPOKES="$SPOKES" bash "$ROOT/hack/bootstrap.sh" --no-jaeger > "$BOOT_LOG" 2>&1
BOOT_RC=$?
tail -6 "$BOOT_LOG" | scrub | sed 's/^/  /'

export OCM_MCP_HUB_CONTEXT="kind-hub"
OCM_MCP_SPOKE_CONTEXTS="$(for i in $(seq 1 "$SPOKES"); do printf 'cluster%d=kind-cluster%d,' "$i" "$i"; done | sed 's/,$//')"
export OCM_MCP_SPOKE_CONTEXTS
export OCM_MCP_HOME="$RUN_DIR/state"

MC="$(kubectl --context kind-hub get managedclusters 2>&1)"
AVAIL="$(echo "$MC" | awk '$5=="True"{n++} END{print n+0}')"
if [[ "$AVAIL" -ge "$SPOKES" ]]; then
  ok "fleet up: $AVAIL/$SPOKES spokes Available"
  rec "4. Bootstrap fleet" "bootstrap.sh" "Stand up a real OCM hub with spokes so every tool talks to genuine clusters, not mocks." OK "CONTAINER_ENGINE=$ENGINE SPOKES=$SPOKES ./hack/bootstrap.sh --no-jaeger" "$(tail -20 "$BOOT_LOG" | scrub)"
  echo "  ${MC//$'\n'/$'\n  '}"
  rec "4. Bootstrap fleet" "managed clusters" "Proof the spokes are registered and Available on the hub." OK "kubectl --context kind-hub get managedclusters" "$MC"
else
  warn "only $AVAIL/$SPOKES spokes Available (bootstrap rc=$BOOT_RC) - aborting"
  rec "4. Bootstrap fleet" "bootstrap.sh" "Stand up a real OCM hub with spokes." FAIL "./hack/bootstrap.sh" "$(tail -30 "$BOOT_LOG" | scrub)"
  cleanup; trap - EXIT; exit 1
fi

# ---------------------------------------------------------------- 4b. enrich fleet
b "4b. Enrich - install the policy add-on and enable ManifestWorkReplicaSet"
info "so add-on and policy tools have real data to return (best-effort)"
ENRICH=""
CLIST="$(for i in $(seq 1 "$SPOKES"); do printf 'cluster%d,' "$i"; done | sed 's/,$//')"
if clusteradm install hub-addon --names governance-policy-framework --context kind-hub >/dev/null 2>&1; then
  clusteradm addon enable --names governance-policy-framework --clusters "$CLIST" --context kind-hub >/dev/null 2>&1 \
    && ENRICH="$ENRICH governance-policy-framework(enabled)" || ENRICH="$ENRICH governance-policy-framework(installed)"
else
  ENRICH="$ENRICH governance-policy-framework(skip)"
fi
if kubectl --context kind-hub patch clustermanager cluster-manager --type merge \
    -p '{"spec":{"workConfiguration":{"featureGates":[{"feature":"ManifestWorkReplicaSet","mode":"Enable"}]}}}' >/dev/null 2>&1; then
  ENRICH="$ENRICH ManifestWorkReplicaSet(enabled)"
else
  ENRICH="$ENRICH ManifestWorkReplicaSet(skip)"
fi

# The ACM (ManagedClusterInfo) and HyperShift (HostedCluster/NodePool) read tools need CRDs a
# plain kind hub does not have. Install minimal CRDs plus clearly-labelled SAMPLE objects so
# those tools are exercised end to end. A real hub gets these from ACM/MCE or HyperShift; on
# kind these are e2e fixtures, not a running ACM/HyperShift install (a real hosted OpenShift
# control plane needs OpenShift infra and several GB of RAM - impractical on a laptop kind fleet).
if kubectl --context kind-hub apply -f - >/dev/null 2>&1 <<'CRDS'
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: {name: managedclusterinfos.internal.open-cluster-management.io, labels: {ocm-mcp-e2e-fixture: "true"}}
spec:
  group: internal.open-cluster-management.io
  scope: Namespaced
  names: {plural: managedclusterinfos, singular: managedclusterinfo, kind: ManagedClusterInfo, listKind: ManagedClusterInfoList}
  versions:
  - {name: v1beta1, served: true, storage: true, schema: {openAPIV3Schema: {type: object, x-kubernetes-preserve-unknown-fields: true}}}
---
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: {name: hostedclusters.hypershift.openshift.io, labels: {ocm-mcp-e2e-fixture: "true"}}
spec:
  group: hypershift.openshift.io
  scope: Namespaced
  names: {plural: hostedclusters, singular: hostedcluster, kind: HostedCluster, listKind: HostedClusterList}
  versions:
  - {name: v1beta1, served: true, storage: true, schema: {openAPIV3Schema: {type: object, x-kubernetes-preserve-unknown-fields: true}}}
---
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: {name: nodepools.hypershift.openshift.io, labels: {ocm-mcp-e2e-fixture: "true"}}
spec:
  group: hypershift.openshift.io
  scope: Namespaced
  names: {plural: nodepools, singular: nodepool, kind: NodePool, listKind: NodePoolList}
  versions:
  - {name: v1beta1, served: true, storage: true, schema: {openAPIV3Schema: {type: object, x-kubernetes-preserve-unknown-fields: true}}}
CRDS
then
  kubectl --context kind-hub wait --for=condition=established --timeout=30s \
    crd/managedclusterinfos.internal.open-cluster-management.io \
    crd/hostedclusters.hypershift.openshift.io \
    crd/nodepools.hypershift.openshift.io >/dev/null 2>&1
  if kubectl --context kind-hub apply -f - >/dev/null 2>&1 <<'CRS'
apiVersion: v1
kind: Namespace
metadata: {name: clusters, labels: {ocm-mcp-e2e-fixture: "true"}}
---
apiVersion: internal.open-cluster-management.io/v1beta1
kind: ManagedClusterInfo
metadata: {name: cluster1, namespace: cluster1, labels: {ocm-mcp-e2e-fixture: "true"}}
status:
  consoleURL: https://console-openshift-console.apps.cluster1.example.com
  kubeVendor: OpenShift
  cloudVendor: BareMetal
  distributionInfo: {type: OCP, ocp: {version: "4.16.7"}}
  nodeList:
  - {name: cluster1-control-plane, capacity: {cpu: "8", memory: "16Gi"}, labels: {node-role.kubernetes.io/control-plane: ""}}
  conditions:
  - {type: ManagedClusterInfoSynced, status: "True", reason: Synced}
---
apiVersion: hypershift.openshift.io/v1beta1
kind: HostedCluster
metadata: {name: demo-hcp, namespace: clusters, labels: {ocm-mcp-e2e-fixture: "true"}}
spec: {}
status:
  version: {history: [{version: "4.16.7", state: Completed}]}
  conditions:
  - {type: Available, status: "True", reason: AsExpected}
---
apiVersion: hypershift.openshift.io/v1beta1
kind: NodePool
metadata: {name: demo-hcp-workers, namespace: clusters, labels: {ocm-mcp-e2e-fixture: "true"}}
spec: {clusterName: demo-hcp, replicas: 2}
status:
  replicas: 2
  conditions:
  - {type: Ready, status: "True"}
CRS
  then ENRICH="$ENRICH acm+hypershift-fixtures"; else ENRICH="$ENRICH acm+hypershift-fixtures(crd-only)"; fi
else
  ENRICH="$ENRICH acm+hypershift-fixtures(skip)"
fi

sleep 8   # let the CRDs register / add-ons start
ok "enrichment:${ENRICH}"
rec "4b. Enrich fleet" "add-on, feature gate, and API fixtures" "Install the governance policy add-on, turn on ManifestWorkReplicaSet, and add minimal CRDs plus labelled sample objects for the ACM (ManagedClusterInfo) and HyperShift (HostedCluster/NodePool) APIs - so the add-on, policy, rollout, ACM, and HyperShift tools all return real objects. On a real hub those come from ACM/MCE or HyperShift; on kind they are clearly-labelled e2e fixtures." OK "clusteradm install/enable hub-addon; kubectl patch clustermanager; kubectl apply CRDs + samples" "enrichment:${ENRICH}"

# ---------------------------------------------------------------- 5. exercise everything
b "5. Exercising tools, prompts, the gated write flow, and a break-then-fix scenario"
"$PYBIN" "$ROOT/hack/e2e_tools.py" --results "$RESULTS" --spokes "$SPOKES" --cluster "$SAMPLE_CLUSTER"
HARNESS_RC=$?

# ---------------------------------------------------------------- 6. report
b "6. Rendering the report (local HTML + wiki Markdown)"
"$PYBIN" "$ROOT/hack/e2e_report.py" --results "$RESULTS" --out "$REPORT" --md "$REPORT_MD"
if [[ $HARNESS_RC -eq 0 ]]; then
  ok "all steps passed"
else
  warn "harness reported failures (exit $HARNESS_RC) - see the report"
fi
# cleanup() runs on EXIT and regenerates the report with the teardown step.
exit "$HARNESS_RC"
