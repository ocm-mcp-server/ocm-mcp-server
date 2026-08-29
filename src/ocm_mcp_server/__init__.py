# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""ocm-mcp-server: a guardrailed MCP server for multi-cluster Kubernetes operations.

The agent never holds a kubeconfig. Every write is policy-checked, human-approved,
and traced.
"""

__version__ = "0.5.0"
