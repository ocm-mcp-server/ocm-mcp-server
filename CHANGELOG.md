# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Expanded the tool surface to 27 tools across nine toolsets** (inventory,
  observability, placement, work, addons, registration, policy, resources,
  audit), covering the Open Cluster Management read API end to end: cluster sets
  and bindings, cluster claims, per-cluster detail, Placements and
  PlacementDecisions, AddOnPlacementScores, ManifestWork status feedback,
  ManifestWorkReplicaSets, ClusterManagementAddOns and per-cluster add-on health,
  pending join CSRs, and governance Policy compliance.
- **Generic allow-listed reader** (`list_resources`, `get_resource`) over OCM API
  types. Secrets and core kinds are not on the allow-list and cannot be named, so
  the dangerous read does not exist rather than being merely restricted.
- **Gated OCM lifecycle actions** (`propose_cluster_action`,
  `apply_cluster_action`): cordon, uncordon, set_label, accept. Each routes
  through the same static-guardrail, hub dry-run, and HMAC-token gate as a
  ManifestWork; none is applied inline.
- **Four MCP prompts**: `diagnose_fleet`, `remediate_with_approval`,
  `incident_postmortem`, `why_not_scheduled`, encoding the safe workflow.
- **MCP tool annotations** (`readOnlyHint` / `destructiveHint`) on every tool, and
  an `OCM_MCP_READ_ONLY` backstop that disables both write toolsets for
  inspection-only deployments.
- **Homepage demo** (animated terminal GIF) plus a
  [Tools and Prompts reference](docs/tools.md) and a matching wiki page.
- **HyperShift HCP toolset**: `list_hosted_clusters`, `get_hosted_cluster`,
  `list_node_pools` (hypershift.openshift.io/v1beta1), for fleets running Hosted
  Control Planes. Feature-detects when HCPs are hosted on a separate management
  cluster.
- **ACM extended inventory**: `get_cluster_info` (ManagedClusterInfo: OpenShift
  version, nodes, console URL, vendor - read from the hub, no spoke access needed),
  `list_addons_for_cluster`, and `list_policy_violations` (NonCompliant / Pending
  rollup; `Pending` correctly counts as a violation).
- **Add-on lifecycle actions**: `enable_addon` / `disable_addon` (create/delete a
  ManagedClusterAddOn) as gated `propose_cluster_action` actions.
- **Six more prompts**: `onboard_cluster`, `addon_troubleshoot`,
  `hosted_cluster_health`, `policy_compliance_report`, `capacity_report`,
  `rollout_status` (ten prompts total).
- **`ocm-mcp doctor`**: a live read-path smoke test that calls every read tool
  against the hub and prints a PASS/EMPTY/SKIP/FAIL table, writing nothing.

### Changed

- Approval proposals now carry a `kind` (manifestwork or action) and typed
  `params`; the content hash binds the whole proposal, so a token approves an
  exact ManifestWork bundle or an exact lifecycle action.
- Tool surface: 33 tools across ten toolsets (from the initial 10). ManifestWork
  status feedback now decodes the FieldValue `type` discriminator
  (Integer/String/Boolean/JsonRaw) rather than guessing.
- Unit tests: 46 (from 26), adding lifecycle-action approvals, the reader
  allow-list, and the HCP / ManagedClusterInfo / add-on shaping logic.

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
  oom-loop, broken-service, config-drift, scaled-to-zero, reversible via
  `make reset`.
- **Evaluation harness**: 22 scripted incident scenarios (15 remediate,
  3 diagnose-only, 4 adversarial) scored objectively from transcripts, live
  cluster state, and the audit log.
- **Client examples** for Claude Code, Codex CLI, Gemini CLI, and IBM BOB,
  plus a production-shaped system prompt.
- **Documentation**: deployment guide, worked examples, architecture,
  guardrail rationale and threat model, demo script, upstream notes, and a
  project wiki covering the full journey from problem to roadmap.
- Unit tests (26), ruff lint, CI, and Dockerfile.

[0.1.0]: https://github.com/sandeepbazar/ocm-mcp-server/releases/tag/v0.1.0
