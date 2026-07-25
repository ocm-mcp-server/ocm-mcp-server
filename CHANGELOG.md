# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-07-25

First public release: the complete guardrailed-AgentOps pattern, end to end.

### Added

- **MCP server** with a deliberately small tool surface over an Open Cluster
  Management hub: 7 read tools (`list_clusters`, `get_cluster_health`,
  `query_events`, `get_pod_logs`, `list_manifestworks`,
  `list_pending_proposals`, `get_audit_trail`) and 3 gated write tools
  (`propose_manifestwork`, `apply_manifestwork`, `rollback_manifestwork`).
- **Four guardrail layers**: static checks (privileged/host access, protected
  namespaces, kind allowlist, pinned images) → Kyverno dry-run admission on
  the hub → human approval via HMAC tokens bound to proposal content hashes
  with TTL → least-privilege RBAC.
- **Kyverno ClusterPolicies** validating embedded manifests inside
  ManifestWorks (`foreach` over `spec.workload.manifests`), scoped by the
  `app.kubernetes.io/managed-by: ocm-mcp-server` label, with an offline CLI
  test suite (12 cases) following kyverno/policies conventions.
- **`ocm-mcp` CLI** for the human side: pending / show / approve / reject /
  audit.
- **Observability**: OpenTelemetry span per tool call (optional OTLP export)
  plus an always-on append-only audit log.
- **Fleet bootstrap** (`make bootstrap`): 1 hub + 3 managed kind clusters,
  OCM via clusteradm, Kyverno, policies, RBAC, demo app, optional Jaeger.
- **Chaos scenarios**: failing-rollout, crashloop, quota-exhaustion,
  oom-loop, broken-service — reversible via `make reset`.
- **Evaluation harness**: 20 scripted incident scenarios (13 remediate,
  3 diagnose-only, 4 adversarial) scored objectively from transcripts, live
  cluster state, and the audit log.
- **Client examples** for Claude Code, Codex CLI, Gemini CLI, and IBM BOB,
  plus a production-shaped system prompt.
- Unit tests (26), ruff lint, CI, Dockerfile, and full documentation
  (architecture, guardrail rationale and threat model, demo script,
  upstream notes).

[0.1.0]: https://github.com/sandeepbazar/ocm-mcp-server/releases/tag/v0.1.0
