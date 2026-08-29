#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
# Tear down everything bootstrap.sh created: kind clusters, the tracing container,
# and the now-stale kubeconfig contexts. Works with docker or podman.
set -euo pipefail

SPOKES="${SPOKES:-3}"

# Pick the container engine the same way bootstrap.sh does.
ENGINE="${CONTAINER_ENGINE:-}"
if [[ -z "$ENGINE" ]]; then
  if command -v podman >/dev/null && podman info >/dev/null 2>&1; then ENGINE=podman
  elif command -v docker >/dev/null && docker info >/dev/null 2>&1; then ENGINE=docker
  else ENGINE=podman; fi
fi
[[ "$ENGINE" == "podman" ]] && export KIND_EXPERIMENTAL_PROVIDER=podman

"$ENGINE" rm -f ocm-mcp-jaeger >/dev/null 2>&1 || true

# Build the cluster list portably (some macOS `seq -f` builds are unreliable in scripts).
NAMES=(hub)
for i in $(seq 1 "$SPOKES"); do NAMES+=("cluster${i}"); done

for name in "${NAMES[@]}"; do
  kind delete cluster --name "$name" 2>/dev/null || true
  # kind delete usually removes the context, but if the node container was deleted
  # out from under kind, the stale context lingers - clean it up explicitly.
  kubectl config delete-context "kind-${name}" >/dev/null 2>&1 || true
  kubectl config delete-cluster "kind-${name}" >/dev/null 2>&1 || true
  kubectl config delete-user "kind-${name}" >/dev/null 2>&1 || true
done

echo "Fleet deleted (${ENGINE}). Local state in ~/.ocm-mcp is kept; remove manually if wanted."
