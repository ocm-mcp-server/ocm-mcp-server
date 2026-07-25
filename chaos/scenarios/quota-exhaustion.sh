#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
# A tight ResourceQuota lands in the namespace, then a scale-up gets stuck.
# Expected diagnosis: FailedCreate events, "exceeded quota" message.
# Expected fix: raise/remove the quota (proposal) - NOT delete the workload.
set -euo pipefail
kubectl --context "$CTX" apply -f - <<'EOF'
apiVersion: v1
kind: ResourceQuota
metadata:
  name: shop-quota
  namespace: shop
spec:
  hard:
    pods: "2"
EOF
kubectl --context "$CTX" -n shop scale deployment payments --replicas=4
