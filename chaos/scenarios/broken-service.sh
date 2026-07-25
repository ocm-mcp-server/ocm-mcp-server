#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
# Service selector no longer matches any pods: app "up" but unreachable.
# Expected diagnosis: Service endpoints empty while pods are Running.
# Expected fix: restore the selector to app=payments.
set -euo pipefail
kubectl --context "$CTX" -n shop patch service payments --type=merge -p '
spec:
  selector:
    app: payments-renamed
'
