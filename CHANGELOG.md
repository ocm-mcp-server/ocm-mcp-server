# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-07-26

A hardening release addressing two independent external enterprise-readiness audits. It
strengthens the actual trust boundaries and narrows the security documentation to describe
only what is enforced.

### Security

- **Restricted Pod Security guardrails.** Embedded workloads (and their init and ephemeral
  containers) must now meet a Restricted baseline: `automountServiceAccountToken: false`,
  required `runAsNonRoot`, explicit `allowPrivilegeEscalation: false`, all capabilities
  dropped, and a seccomp profile. Added an allow-list of volume types (no PVC, CSI,
  hostPath, or secret) and Service types (no NodePort/LoadBalancer/ExternalName/externalIPs),
  optional digest-pinning (`OCM_MCP_REQUIRE_DIGEST`), and schema validation so a malformed
  manifest is a clean rejection instead of a crash.
- **One-time, issuer/audience-bound approval tokens.** Tokens now carry a unique id, issuer,
  audience, and not-before; the id is recorded as spent (locked, fsynced) on first use, so a
  token cannot be replayed, and a token minted for one deployment cannot be used against
  another. The signer and verifier key paths are now independent (`OCM_MCP_SIGNER_KEY` /
  `OCM_MCP_VERIFIER_KEY`) so the private key can live off the server; a planned rotation can
  keep a previous verifier key valid until outstanding tokens expire.
- **Requester-bound Kyverno policy.** A new policy matches ManifestWorks by the server's
  ServiceAccount identity and requires the `managed-by` label, closing the bypass where an
  unlabeled ManifestWork would skip the label-keyed content policies. Verified by a new
  offline test with requester `userInfo`.
- **Stronger CSR validation.** The `accept` action now also rejects denied CSRs and requires
  an OCM group, `client auth` usage, and a bootstrap username bound to the target cluster,
  re-checked at apply.
- **Tamper-evident audit log.** Each entry carries an actor, a sequence number, and a hash
  chained to the previous entry; `ocm-mcp audit-verify` recomputes the chain. An audit-write
  failure is surfaced to stderr and never masks a tool result.
- **Hardened state store.** Proposal ids are validated (no path traversal), writes are locked
  and fsynced, and status advances only along legal transitions. Proposal/audit files are
  created 0600 and the proposals directory 0700.

### Added

- Reference `deploy/deployment.yaml` and a Helm chart (`deploy/charts/ocm-mcp-server`) with a
  Restricted pod shape and read-only verifier-key mount.
- Optional Prometheus `/metrics` endpoint (`OCM_MCP_METRICS_PORT`).
- `ocm-mcp audit-verify` command.
- Hash-pinned `requirements.lock`, Dependabot, and CI gates for `ruff format`, `mypy`, and a
  coverage floor; release images now ship an SBOM, provenance, and a keyless Cosign signature.

### Fixed

- Documentation narrowed to enforced boundaries: the "compromised server cannot mint" claim
  is now scoped to off-box signing; RBAC no longer claims per-object ownership (enforced in
  the app); the generic reader is described as returning full allow-listed objects. Removed
  the last HMAC/secret wording remnants. Corrected the invalid `.github/FUNDING.yml`.

## [0.2.0] - 2026-07-25

A security-focused release addressing an external security audit. The headline change
is that human approval is now cryptographically independent of the server.

### Security

- **Asymmetric, operation-bound approval (was shared HMAC).** The `ocm-mcp` CLI holds an
  Ed25519 private signing key; the MCP server loads only the public key. The server can
  verify a token but can never mint one, so a compromised server - or an agent that reads
  the server's key material - still cannot approve its own changes. Each token's claims
  bind the exact proposal hash, the operation (`apply` or `rollback`), and an expiry, so
  an apply token can never authorize a rollback.
- **Rollback is now a distinct, approvable operation.** `propose_rollback` creates a
  separate rollback proposal bound to the applied ManifestWork's name and UID;
  `rollback_manifestwork` verifies a rollback-scoped token, checks the work is still
  ours (managed-by label) with the approved UID, then deletes it. This fixes the old
  workflow where a fresh rollback token could not be minted and an apply token could
  authorize deletion.
- **Static guardrails hardened.** Manifests are matched against an exact
  `apiVersion/kind` allow-list (blocking group spoofing like `evil.example/v1, Deployment`),
  and now reject Secret access via `env.secretKeyRef`/`envFrom.secretRef`, secret and
  serviceAccountToken-projected volumes, and arbitrary `serviceAccountName`.
- **CSR approval is bound to exact CSRs.** The `accept` action captures the pending join
  CSRs (name, UID, signer, subject) at propose time and approves only those at apply time,
  re-verifying signer and username - it no longer sweeps every CSR with a matching label
  or approves CSRs created after the human reviewed.
- **Truthful audit.** The trace wrapper now classifies a tool's outcome from its result
  (`rejected` / `failed` / `unavailable`), so a refused operation is no longer logged as
  `ok`; the evaluation harness scores from the corrected outcomes.
- **Dependency bounds.** Pinned `mcp>=1.9,<2` (MCP v2 is a breaking rewrite) and
  `kubernetes<37`; added `cryptography` for Ed25519.

### Changed

- Tool surface: 34 tools (added `propose_rollback`). Proposals are written atomically
  (temp file + rename). `get_audit_trail` streams the tail instead of reading the whole
  file. `cluster_events` fetches a wider window before sorting so newer events are not
  missed on busy clusters. Unit tests: 57.

### Added (tooling, platform, and governance in this release)

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
  through the same static-guardrail, hub dry-run, and approval-token gate as a
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

### Security and hardening

- **Apply-time integrity re-check (TOCTOU)**: `apply_manifestwork` and
  `apply_cluster_action` now recompute the proposal's content hash and (for
  ManifestWorks) re-run the static guardrails at apply time, so a proposal file
  edited at rest is rejected even though the token still matches the stale hash.
- **RBAC now mirrors the real tool surface**: the hub ClusterRole covers placement,
  add-on, operator, policy, ManagedClusterInfo, HyperShift, and CSR APIs, plus
  `patch` on ManagedClusters and CSR approval - previously it only allowed
  ManagedCluster reads and ManifestWorks, so most tool calls would have 403'd. Still
  no Secret reads, no exec, no arbitrary delete.
- **Approval key rotation**: `ocm-mcp rotate-secret` regenerates the approval
  keypair, invalidating all outstanding tokens.
- **Bounded spoke reads**: health/event/log calls carry a read timeout
  (`OCM_MCP_SPOKE_TIMEOUT`) and a fetch cap (`OCM_MCP_HEALTH_LIMIT`) that reports
  truncation, so one large cluster cannot hang or flood a tool call.
- **API client TTL**: the cached Kubernetes client is rebuilt after
  `OCM_MCP_CLIENT_TTL` seconds so rotated/exec-refreshed credentials are picked up.
- **Full-UUID proposal IDs** (128-bit) instead of 8 hex characters.
- **Robust PodSpec extraction** in the static guardrails for CronJob and other
  workload kinds, so the security checks stay correct if `ALLOWED_KINDS` grows.

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
- **Client examples** for Claude Code, Codex CLI, Gemini CLI, and any other
  MCP-capable client, plus a production-shaped system prompt.
- **Documentation**: deployment guide, worked examples, architecture,
  guardrail rationale and threat model, demo script, upstream notes, and a
  project wiki covering the full journey from problem to roadmap.
- Unit tests (26), ruff lint, CI, and Dockerfile.

[0.1.0]: https://github.com/sandeepbazar/ocm-mcp-server/releases/tag/v0.1.0
