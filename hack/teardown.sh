#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar <sandeepbazar@gmail.com>
# SPDX-License-Identifier: Apache-2.0
# Tear down everything bootstrap.sh created.
set -euo pipefail

SPOKES="${SPOKES:-3}"

docker rm -f ocm-mcp-jaeger >/dev/null 2>&1 || true
for name in hub $(seq -f 'cluster%g' 1 "$SPOKES"); do
  kind delete cluster --name "$name" 2>/dev/null || true
done
echo "Fleet deleted. Local state in ~/.ocm-mcp is kept; remove manually if wanted."
