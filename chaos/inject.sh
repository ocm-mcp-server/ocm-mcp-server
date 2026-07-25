#!/usr/bin/env bash
# Inject a failure scenario into a managed cluster.
#
# Usage: ./chaos/inject.sh <scenario> <cluster>     e.g. ./chaos/inject.sh failing-rollout cluster2
#        ./chaos/inject.sh reset <cluster>          restore the demo app to healthy
#
# Scenarios are small, composable, and reversible. Each one leaves the cluster
# in a state a competent on-call engineer could diagnose from events + logs.
set -euo pipefail

SCENARIO="${1:?scenario required (see chaos/scenarios/)}"
CLUSTER="${2:?cluster name required, e.g. cluster2}"
CTX="kind-${CLUSTER}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "$SCENARIO" == "reset" ]]; then
  kubectl --context "$CTX" delete resourcequota --all -n shop --ignore-not-found >/dev/null
  kubectl --context "$CTX" delete deployment payments-v2 -n shop --ignore-not-found >/dev/null
  kubectl --context "$CTX" apply -f "$HERE/../hack/demo-app.yaml" >/dev/null
  kubectl --context "$CTX" rollout restart deployment/payments -n shop >/dev/null
  echo "reset: ${CLUSTER} demo app restored"
  exit 0
fi

SCRIPT="$HERE/scenarios/${SCENARIO}.sh"
[[ -f "$SCRIPT" ]] || { echo "unknown scenario '$SCENARIO'"; ls "$HERE/scenarios" | sed 's/\.sh$//'; exit 1; }
CTX="$CTX" CLUSTER="$CLUSTER" bash "$SCRIPT"
echo "injected: ${SCENARIO} into ${CLUSTER}"
