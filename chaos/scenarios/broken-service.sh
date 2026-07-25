#!/usr/bin/env bash
# Service selector no longer matches any pods: app "up" but unreachable.
# Expected diagnosis: Service endpoints empty while pods are Running.
# Expected fix: restore the selector to app=payments.
set -euo pipefail
kubectl --context "$CTX" -n shop patch service payments --type=merge -p '
spec:
  selector:
    app: payments-renamed
'
