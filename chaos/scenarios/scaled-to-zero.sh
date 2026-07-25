#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar <sandeepbazar@gmail.com>
# SPDX-License-Identifier: Apache-2.0
# Someone scaled payments to zero replicas: total outage, no errors anywhere.
# Expected diagnosis: Deployment desired=0, no pods, no error events (the trap).
# Expected fix: propose scaling back to the intended replica count.
set -euo pipefail
kubectl --context "$CTX" -n shop scale deployment payments --replicas=0
