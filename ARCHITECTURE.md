<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture

> The full architecture - including the **low-level design** with vertical
> diagrams of the complete component stack, the anatomy of a read call, the
> gated write sequence with every check in order, the rollback and lifecycle
> paths, and the audit/anchor/key-custody machinery - lives in
> **[docs/architecture.md](docs/architecture.md)**.

The one-paragraph version: an AI agent talks MCP (JSON-RPC over stdio) to
`ocm-mcp-server`, which exposes a broad read surface over an Open Cluster
Management hub and a narrow, gated write path. Every change must pass, in
order: static Python guardrails, a Kyverno dry-run admission on the hub, a
human-minted one-time Ed25519 approval token bound to the exact content and
operation, and least-privilege RBAC. The agent never holds a kubeconfig;
there is no tool that can read Secrets, exec into pods, or delete arbitrary
resources. Every call lands in a hash-chained, anchor-signed audit log.

| Deep dive | Where |
|---|---|
| Full stack + low-level design diagrams | [docs/architecture.md](docs/architecture.md) |
| The four guardrail layers and threat model | [docs/guardrails.md](docs/guardrails.md) |
| Security self-assessment (CNCF style) | [docs/security-self-assessment.md](docs/security-self-assessment.md) |
| Deployment paths, tracing, hardening checklist | [docs/deployment.md](docs/deployment.md) |
| Per-tool reference | [docs/tools.md](docs/tools.md) |
