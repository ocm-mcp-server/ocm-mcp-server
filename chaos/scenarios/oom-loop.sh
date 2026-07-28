#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
# Drop the memory limit far below actual usage: OOMKilled loop.
# Expected diagnosis: OOMKilled in container status / events, restarts climbing.
# Expected fix: raise the memory limit to a sane value.
set -euo pipefail
# Request must drop with the limit: the API rejects request > limit, so patching
# the limit alone fails against the bootstrap payments spec (32Mi request).
kubectl --context "$CTX" -n shop patch deployment payments --type=json -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "8Mi"},
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "16Mi"}
]'
