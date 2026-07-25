#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar <sandeepbazar@gmail.com>
# SPDX-License-Identifier: Apache-2.0
# A ConfigMap the app reads gets a wrong value; the app stays up but misbehaves.
# Expected diagnosis: recent ConfigMap change; app logs show the bad value.
# Expected fix: propose the corrected ConfigMap.
set -euo pipefail
kubectl --context "$CTX" -n shop create configmap payments-config \
  --from-literal=RATE_LIMIT=0 --dry-run=client -o yaml | kubectl --context "$CTX" apply -f -
kubectl --context "$CTX" -n shop annotate configmap payments-config \
  ocm-mcp.chaos/injected="config-drift" --overwrite
