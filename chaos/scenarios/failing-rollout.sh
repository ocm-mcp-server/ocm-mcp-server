#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar <sandeepbazar@gmail.com>
# SPDX-License-Identifier: Apache-2.0
# A new "v2" rollout of payments that can never become ready: bad image tag.
# Expected diagnosis: ImagePullBackOff on payments-v2.
# Expected fix: pin back to the known-good image (or delete the v2 rollout).
set -euo pipefail
kubectl --context "$CTX" apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payments-v2
  namespace: shop
  labels:
    app: payments
    version: v2
spec:
  replicas: 2
  selector:
    matchLabels:
      app: payments
      version: v2
  template:
    metadata:
      labels:
        app: payments
        version: v2
    spec:
      containers:
        - name: payments
          image: registry.k8s.io/e2e-test-images/agnhost:2.47-nonexistent
          args: ["netexec", "--http-port=8080"]
          ports:
            - containerPort: 8080
EOF
