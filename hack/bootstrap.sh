#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
# Bootstrap a local OCM fleet for ocm-mcp-server:
#   1 hub + 3 managed kind clusters, OCM via clusteradm, Kyverno on the hub,
#   guardrail policies, least-privilege RBAC, read-only spoke ServiceAccounts,
#   and (optionally) a Jaeger container for traces.
#
# Requirements: docker, kind, kubectl, clusteradm, helm.
#   brew install kind kubectl helm
#   curl -L https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh | bash
#
# Usage:
#   ./hack/bootstrap.sh              # full fleet
#   SPOKES=2 ./hack/bootstrap.sh     # fewer spokes (laptop-friendly)
#   ./hack/bootstrap.sh --no-jaeger  # skip the tracing container
set -euo pipefail

SPOKES="${SPOKES:-3}"
HUB=hub
JAEGER=1
[[ "${1:-}" == "--no-jaeger" ]] && JAEGER=0

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

for bin in docker kind kubectl clusteradm helm; do
  command -v "$bin" >/dev/null || die "'$bin' is required. See header of this script."
done
docker info >/dev/null 2>&1 || die "docker daemon is not running."

say "Creating kind clusters (1 hub + ${SPOKES} spokes)"
kind get clusters | grep -qx "$HUB" || kind create cluster --name "$HUB" --wait 120s
for i in $(seq 1 "$SPOKES"); do
  kind get clusters | grep -qx "cluster${i}" || kind create cluster --name "cluster${i}" --wait 120s
done

HUB_CTX="kind-${HUB}"

say "Initializing OCM hub (clusteradm init)"
clusteradm init --wait --context "$HUB_CTX" >/dev/null
JOIN_CMD=$(clusteradm get token --context "$HUB_CTX" | grep -o 'clusteradm join.*')

say "Joining ${SPOKES} spoke clusters to the hub"
# --force-internal-endpoint-lookup makes spokes reach the hub over the
# docker network (kind-specific), instead of the host-mapped port.
for i in $(seq 1 "$SPOKES"); do
  eval "$JOIN_CMD --context kind-cluster${i} --cluster-name cluster${i} --force-internal-endpoint-lookup --wait" \
    || die "join failed for cluster${i}"
done

say "Accepting cluster registrations on the hub"
clusteradm accept --clusters "$(seq -s, -f 'cluster%g' 1 "$SPOKES")" --context "$HUB_CTX" --wait

say "Installing Kyverno on the hub"
helm repo add kyverno https://kyverno.github.io/kyverno >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --kube-context "$HUB_CTX" --wait --timeout 5m >/dev/null

say "Applying guardrail policies and RBAC on the hub"
kubectl --context "$HUB_CTX" apply -f "$(dirname "$0")/../deploy/policies/"
kubectl --context "$HUB_CTX" apply -f "$(dirname "$0")/../deploy/rbac.yaml"

say "Creating read-only ServiceAccounts on each spoke"
for i in $(seq 1 "$SPOKES"); do
  CTX="kind-cluster${i}"
  kubectl --context "$CTX" create serviceaccount ocm-mcp-reader -n default \
    --dry-run=client -o yaml | kubectl --context "$CTX" apply -f -
  kubectl --context "$CTX" apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ocm-mcp-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "namespaces", "services"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ocm-mcp-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ocm-mcp-reader
subjects:
  - kind: ServiceAccount
    name: ocm-mcp-reader
    namespace: default
EOF
done

if [[ "$JAEGER" == "1" ]]; then
  say "Starting Jaeger (all-in-one) for traces at http://localhost:16686"
  docker rm -f ocm-mcp-jaeger >/dev/null 2>&1 || true
  docker run -d --name ocm-mcp-jaeger \
    -p 16686:16686 -p 4318:4318 \
    jaegertracing/all-in-one:1.60 >/dev/null
fi

say "Deploying the demo app to all spokes (namespace 'shop')"
for i in $(seq 1 "$SPOKES"); do
  kubectl --context "kind-cluster${i}" apply -f "$(dirname "$0")/demo-app.yaml"
done

SPOKE_CONTEXTS=$(seq -f 'cluster%g=kind-cluster%g' 1 "$SPOKES" | paste -sd, -)
say "Done. Configure your MCP client environment:"
cat <<EOF

  export OCM_MCP_HUB_CONTEXT=${HUB_CTX}
  export OCM_MCP_SPOKE_CONTEXTS=${SPOKE_CONTEXTS}
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # if Jaeger enabled

  # then register the server with your MCP client, e.g. for Claude Code:
  #   see examples/claude-code.mcp.json

Verify the fleet:
  kubectl --context ${HUB_CTX} get managedclusters
EOF
