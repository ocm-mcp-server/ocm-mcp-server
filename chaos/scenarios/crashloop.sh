#!/usr/bin/env bash
# Make payments crash shortly after start, like a missing config key would.
# Expected diagnosis: CrashLoopBackOff; the reason is in the container logs.
# Expected fix: restore the original container command/args (or the "config").
set -euo pipefail
kubectl --context "$CTX" -n shop patch deployment payments --patch '
spec:
  template:
    spec:
      containers:
        - name: payments
          command: ["/bin/sh"]
          args: ["-c", "echo fatal: config key PAYMENTS_DB_URL missing >&2; exit 1"]
'
