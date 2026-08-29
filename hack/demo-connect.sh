#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# Re-record demo/connect-<agent>.* — "a fleet operator's day", driven by a real agent.
#
#   ./hack/demo-connect.sh                # drive Claude
#   AGENT=codex ./hack/demo-connect.sh    # drive Codex through the same ten chapters
#   DRY_RUN=1 ./hack/demo-connect.sh      # print the chapters, call no model
#
# This drives a REAL agent over the REAL MCP protocol against a REAL fleet. It is
# a different demo from demo/e2e-local.*, which records the test suite: this one
# is the operator's view, where every answer is the model's own.
#
# Why this lives in the repository: the previous version of this script was
# written to a scratchpad and lost, leaving a committed GIF that nothing could
# reproduce. The cast's own `command` field is what recovered its shape.
#
# Requirements: a fleet (hack/bootstrap.sh SPOKES=3), an authenticated `claude`
# or `codex`, and asciinema + agg + ffmpeg to render.
#
# NOTE: each chapter is a real model call and consumes your quota. Wording will
# differ between runs; the *shape* of the day is what the demo shows.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
AGENT="${AGENT:-claude}"
DRY_RUN="${DRY_RUN:-0}"
WORK="${WORK:-$ROOT/.demo-connect}"

b() { printf '\n\033[1;36m# %s\033[0m\n' "$*"; }
run() {
  printf '\033[0;90m$ %s\033[0m\n' "$*"
  [[ "$DRY_RUN" == "1" ]] && return 0
  # shellcheck disable=SC2294  # the demo shows shell lines verbatim, so it runs them as written
  eval "$*"
}

# Ask the agent one question. Both CLIs take a bare prompt non-interactively.
ask() {
  local prompt="$1"
  printf '\033[0;90m$ %s -p "%s"\033[0m\n' "$AGENT" "${prompt:0:96}..."
  [[ "$DRY_RUN" == "1" ]] && return 0
  case "$AGENT" in
    claude) claude -p "$prompt" ;;
    codex)  codex exec "$prompt" ;;
    *) echo "unknown AGENT: $AGENT" >&2; return 1 ;;
  esac
}

# ----------------------------------------------------------------- 1. install
b "1. install the MCP server from PyPI"
run "rm -rf '$WORK' && mkdir -p '$WORK' && cd '$WORK'"
# In a dry run nothing was created, so there is nothing to cd into.
[[ "$DRY_RUN" == "1" ]] || cd "$WORK" || exit 1
run "python3 -m venv ocm && source ocm/bin/activate"
# shellcheck disable=SC1091
[[ "$DRY_RUN" == "1" ]] || source ocm/bin/activate
run "pip install -q ocm-mcp-server && which ocm-mcp-server"

# ------------------------------------------------------- 2. point at the fleet
b "2. point it at the fleet: hub context, read-only spoke contexts, a state dir"
export OCM_MCP_HUB_CONTEXT=kind-hub
export OCM_MCP_SPOKE_CONTEXTS=cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3
export OCM_MCP_HOME="$WORK/state"
run "export OCM_MCP_HUB_CONTEXT=kind-hub"
run "export OCM_MCP_SPOKE_CONTEXTS=$OCM_MCP_SPOKE_CONTEXTS"
run "export OCM_MCP_HOME=\$PWD/state"

# ------------------------------------------------------------ 3. connect it
b "3. add it to $AGENT - guardrailed tools in, kubeconfig stays out"
if [[ "$AGENT" == "claude" ]]; then
  run "claude mcp remove ocm >/dev/null 2>&1 || true"
  run "claude mcp add ocm --env OCM_MCP_HUB_CONTEXT=\$OCM_MCP_HUB_CONTEXT --env OCM_MCP_SPOKE_CONTEXTS=\$OCM_MCP_SPOKE_CONTEXTS --env OCM_MCP_HOME=\$OCM_MCP_HOME -- ocm-mcp-server"
  run "claude mcp list 2>/dev/null | grep ocm"
else
  echo "  (codex reads examples/codex-config.toml - see examples/README.md)"
fi

# ------------------------------------------------- 3b. preconditions the demo needs
# bootstrap.sh brings up the fleet but not these: the Placement chapter 5 asks
# about, and the namespace chapters 7-9 deploy into. Created here so the demo is
# self-contained rather than depending on having run the test suite first.
b "3b. fixtures: a cluster-set binding, a Placement, and the target namespace"
if [[ "$DRY_RUN" != "1" ]]; then
  kubectl --context kind-hub apply -f - >/dev/null 2>&1 <<'YAML' || true
apiVersion: cluster.open-cluster-management.io/v1beta2
kind: ManagedClusterSetBinding
metadata: {name: global, namespace: default}
spec: {clusterSet: global}
---
apiVersion: cluster.open-cluster-management.io/v1beta1
kind: Placement
metadata: {name: demo-all, namespace: default}
spec: {clusterSets: [global]}
YAML
  kubectl --context kind-cluster2 create namespace shop >/dev/null 2>&1 || true
  echo "  placement demo-all + namespace shop ready"
else
  echo "  (dry run: would create ManagedClusterSetBinding, Placement demo-all, namespace shop)"
fi

# --------------------------------------------------------------- 4. know it
b "4. KNOW the fleet - inventory, versions, capacity, add-ons. one question"
ask "Give me a crisp fleet overview: every managed cluster with availability, Kubernetes version and capacity, plus the health of the platform add-ons. Use the ocm tools. Be brief."

# ------------------------------------------------------------ 5. placement
b "5. PLACEMENT - where will new workloads land, and why?"
ask "Explain the placement named demo-all in namespace default: which clusters does it currently select, and why those? Keep it to a few lines."

# ------------------------------------------------------- 6. the lazy way
b "6. ship a new service the LAZY way - the guardrails must refuse"
ask "Ship a new storefront service fast: propose deploying image nginx:latest to namespace shop on cluster2, running privileged. If anything refuses it, show me the exact reason."

# ------------------------------------------------------- 7. the right way
b "7. ship it RIGHT - the agent can only PROPOSE, never apply on its own"
ask "Propose - do not apply - a ManifestWork named storefront on cluster2: a Deployment in namespace shop with 2 replicas of nginx:1.27.4, non-root, no privilege escalation, all capabilities dropped. Report the proposal id."

# ------------------------------------------------- 8. the human signs it
b "8. a human reviews and signs in the terminal (Ed25519) - the only way through"
run "ocm-mcp pending"
PID=""
TOKEN=""
if [[ "$DRY_RUN" != "1" ]]; then
  PID="$(ocm-mcp pending | awk 'NF && $1 ~ /^[0-9a-f]{32}$/ {print $1; exit}')"
fi
if [[ -n "$PID" ]]; then
  run "ocm-mcp show $PID"
  # Approve exactly ONCE: a second call fails because the proposal is no longer
  # pending. Show the real output, then take the token from its last line.
  printf '\033[0;90m$ ocm-mcp approve %s --yes\033[0m\n' "$PID"
  APPROVE_OUT="$(ocm-mcp approve "$PID" --yes 2>&1)"
  echo "$APPROVE_OUT"
  TOKEN="$(printf '%s\n' "$APPROVE_OUT" | tail -1)"
else
  echo "  (no pending proposal captured - chapters 9 and 10 need one)"
fi

# ------------------------------------------------------------- 9. apply it
b "9. only WITH the token can $AGENT apply - then it verifies the rollout"
if [[ -n "$TOKEN" ]]; then
  ask "Apply proposal $PID on cluster2 using this approval token: $TOKEN. Then verify the rollout and tell me what is running."
else
  echo "  (skipped: no token)"
fi

# ------------------------------------------------------- 10. the record
b "10. the day, on the record - an operations log straight from the audit trail"
ask "From the audit trail, summarize this session as an operations log: the fleet review, the placement check, the refused shortcut, the approved change, and the verification. Short bullets."

b "done - fleet left running; tear down with ./hack/teardown.sh"
