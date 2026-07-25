#!/usr/bin/env bash
# Drop the memory limit far below actual usage: OOMKilled loop.
# Expected diagnosis: OOMKilled in container status / events, restarts climbing.
# Expected fix: raise the memory limit to a sane value.
set -euo pipefail
kubectl --context "$CTX" -n shop patch deployment payments --type=json -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "16Mi"}
]'
