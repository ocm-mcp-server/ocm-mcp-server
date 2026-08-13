<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Security self-assessment

This self-assessment follows the structure used by the CNCF TAG-Security
[self-assessment template](https://github.com/cncf/tag-security/blob/main/community/assessments/guide/self-assessment.md).
It is a living document, maintained by the project, describing what the project does,
its security posture, and where the boundaries of its guarantees lie. It is written to
be honest about limits, not to market.

## Metadata

| | |
|---|---|
| Software | https://github.com/sandeepbazar/ocm-mcp-server |
| Security provider | No. The project is a control point that adds safety to agent-driven fleet operations; it is not a security product in itself. |
| Languages | Python |
| SBOM | Dependencies are bounded in `pyproject.toml` and hash-pinned in `requirements.lock`; the release container image is published to GHCR with a generated SBOM, build provenance, and a keyless Cosign signature. |

### Security links

| Document | URL |
|---|---|
| Security policy | [SECURITY.md](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/SECURITY.md) |
| Guardrail model and threat model | [docs/guardrails.md](guardrails.md) |
| Architecture | [docs/architecture.md](architecture.md) |
| RBAC | [deploy/rbac.yaml](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/deploy/rbac.yaml) |

## Overview

ocm-mcp-server is a Model Context Protocol (MCP) server that lets AI agents operate a
multi-cluster Kubernetes fleet through an Open Cluster Management (OCM) hub. Its purpose
is to make that operation **safe by construction**: agents can read the whole fleet
freely, but any change must be proposed, pass policy admission, and be approved by a
human before it reaches a cluster.

### Background

Fleets managed by OCM (and its downstream ACM/MCE) expose a hub with an inventory
(`ManagedCluster`), a scheduler (`Placement`), and a delivery channel (`ManifestWork`).
The server exposes this hub to agents as a small, typed set of MCP tools and interposes
four independent controls between the model and the clusters.

### Actors

- **AI agent / MCP client** - untrusted with respect to intent; may be prompt-injected.
  It can call tools but never holds a kubeconfig, a Secret, or an exec socket.
- **ocm-mcp-server** - the trusted mediator. Holds the hub kubeconfig, applies static
  guardrails, writes the audit log, and talks to the hub.
- **OCM hub** - enforces Kyverno policy admission and RBAC.
- **Human operator** - the only source of approval tokens, on a trusted terminal.

### Actions

1. **Read** (ungated): the agent lists/gets OCM resources and, where a spoke context is
   configured, reads events, logs, and health. Most reads are summarized; the generic
   reader returns full allow-listed OCM objects (never Secrets or core kinds).
2. **Propose** (mutates nothing): the agent proposes a ManifestWork or a lifecycle
   action. It passes static guardrails and a Kyverno dry-run on the hub, then is stored
   pending.
3. **Approve** (human, out of band): the operator runs `ocm-mcp approve <id>` on a
   trusted terminal, which signs an Ed25519 token bound to the proposal's content hash
   and the intended operation. The server holds only the public verification key.
4. **Apply** (gated): the agent submits the token; the server re-checks content
   integrity and re-runs guardrails, verifies the token, and applies through
   least-privilege RBAC.

### Goals

- An agent cannot cause a change to reach a cluster without policy admission and an
  explicit human approval of the exact content.
- No tool exists that reads Secrets, execs into pods, or deletes arbitrary resources.
- Every tool call is recorded in an append-only audit log.

### Non-goals

- The project does not defend against a compromised or malicious **human operator**, who
  is the trust anchor for writes.
- It does not defend against a compromised **hub cluster** or its Kubernetes API server.
- It does not sandbox the model itself; it constrains what the model can *do*, not what
  it can *say*.

## Security functions and features

### Critical

- **Asymmetric, operation-bound, one-time human approval.** Approval is an Ed25519
  signature over claims that bind the exact proposal content hash, the operation (`apply`
  or `rollback`), the issuer and audience, a unique token id, and an expiry. The token is
  single-use: its id is recorded as spent under a lock on first use, so it cannot be
  replayed. An apply token cannot authorize a rollback, and a change to any byte of the
  proposal invalidates the signature. The keypair is rotatable with `ocm-mcp
  rotate-secret`, and a planned rotation can keep a previous verifier key valid until
  outstanding tokens expire.
  **Isolation boundary (be precise):** the MCP server needs only the public verifier key,
  but "a compromised server cannot mint a token" holds **only when the private signing key
  is kept off the server** - a separate OS account or device via `OCM_MCP_SIGNER_KEY`, or a
  chat-ops/ticket signer. When signer and server share one `OCM_MCP_HOME`, a compromised
  server process could read the private key; there, signer isolation is a filesystem
  convention, not an enforced boundary. Off-box signing is required for the stronger claim.
- **Bound CSR approval.** The `accept` lifecycle action captures the pending join CSRs
  (name, UID, signer, requester, and a hash of the PKCS#10 request) at propose time and
  approves only those exact CSRs at apply time, re-verifying that each is still a pending,
  not-denied, OCM client-auth join CSR (signer, an OCM group, `client auth` usage, OCM
  bootstrap username) bound to the target cluster, that the PKCS#10 request bytes are
  unchanged since the human reviewed, and that the parsed certificate subject Common Name
  is the OCM agent identity for that cluster. It never sweeps every CSR with a matching
  label, and never approves a CSR created or altered after the human review.
- **Rollback as a distinct operation.** Undoing an applied change requires a separate
  rollback proposal bound to the ManifestWork's UID and a rollback-scoped token; the
  server verifies the work is still ours (managed-by label) with the approved UID before
  deleting it.
- **Policy admission.** Every proposed ManifestWork is dry-run created on the hub so
  Kyverno validating policies run during admission and reject non-compliant content
  before anything is stored or applied.
- **Allow-listed capability surface.** The tool set is fixed and small. The generic
  reader accepts only an allow-list of OCM API types, so Secrets and core kinds are not
  expressible - the dangerous read does not exist rather than being merely restricted.
- **Least-privilege RBAC.** The hub identity ([deploy/rbac.yaml](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/deploy/rbac.yaml))
  grants exactly the verbs the tools use: read across the OCM API, plus create/delete
  ManifestWorks and ManagedClusterAddOns, patch ManagedClusters, and approve OCM join
  CSRs. No Secret reads, no exec, no arbitrary delete. RBAC cannot restrict writes to
  "only objects this server created", so per-object ownership is enforced in the
  application (managed-by label + approved UID), not by RBAC.
- **Requester-bound policy (no label bypass).** A Kyverno policy matches ManifestWorks by
  the server's ServiceAccount identity (`request.userInfo`) and requires the
  `managed-by` label, so the server SA cannot create an unlabeled ManifestWork that would
  skip the content policies keyed on that label.

### Security-relevant

- **Restricted-Pod-Security guardrails.** Static checks enforce a Restricted baseline on
  every embedded workload (and its init/ephemeral containers): exact `apiVersion/kind`
  allow-list (blocks group spoofing), no host namespaces, `automountServiceAccountToken:
  false`, no arbitrary service account, an allow-list of volume and Service types (no
  PVC/CSI/hostPath/secret, no NodePort/LoadBalancer/externalIPs), required
  `runAsNonRoot`, `allowPrivilegeEscalation: false`, all capabilities dropped, a seccomp
  profile, no indirect Secret access, and pinned images (optionally digest-pinned via
  `OCM_MCP_REQUIRE_DIGEST`). Inputs are schema-checked first, so a malformed manifest is a
  clean rejection, not a crash. Checks run before policy admission and again at apply.
- **Apply-time integrity re-check** recomputes the proposal's content hash and re-runs
  guardrails at apply, closing a time-of-check/time-of-use gap on the state directory.
- **Hardened state store.** Proposal ids are validated (no path traversal); writes are
  atomic (temp + fsync + rename) under a file lock; status advances only along legal
  transitions, so a stale file cannot be re-applied.
- **Tamper-evident audit.** Each audit line carries an actor, a monotonic sequence number,
  and a hash chained to the previous entry; `ocm-mcp audit-verify` recomputes the chain and
  detects any edit, reordering, or mid-log deletion. Tail truncation and wholesale rewrites
  are covered by signed anchors: `ocm-mcp audit-anchor` (run from the trusted terminal, like
  minting an approval) signs the chain head with the off-box approval key, and
  `audit-verify` fails unless the log still extends every anchored head. Entries newer than
  the last anchor are unprotected until the next anchor - run it on a schedule. An
  audit-write failure is surfaced to stderr and never masks a tool's result.
- **Bounded, timed spoke reads** cap result size and set request timeouts so one large
  cluster cannot hang or flood a call.
- **Read-only mode** (`OCM_MCP_READ_ONLY=1`) disables both write toolsets as a coarse
  backstop under the token gate.
- **Observability**: the append-only audit log, plus optional OpenTelemetry spans and an
  optional Prometheus `/metrics` endpoint (`OCM_MCP_METRICS_PORT`). Approval tokens are
  redacted from all three.

## Project compliance

The project does not currently claim compliance with a specific external standard (for
example NIST SSDF or FedRAMP). It aligns with common cloud native security practices:
least privilege, defense in depth, no secrets in code, signed-off commits, and a
documented threat model.

## Secure development practices

- **Development pipeline**: contributions arrive via pull request. CI runs linting and
  format checks (ruff), static typing (mypy), the unit test suite with a coverage gate
  (403 tests, 100% branch coverage, no cluster required), the offline Kyverno policy tests
  (42 cases, including a
  requester-identity bypass test), a dependency review, and a secret scan (gitleaks). A
  CodeQL workflow scans the code.
- **Commits**: new contributions are asked to sign off under the Developer Certificate
  of Origin via the pull-request checklist; automated DCO enforcement is not yet wired
  up, and part of the early single-maintainer history predates the sign-off practice.
- **Dependencies** are bounded above and below in `pyproject.toml` and pinned with hashes
  in `requirements.lock`; Dependabot proposes updates for pip and GitHub Actions.
- **Container image** is built from a minimal base and published to GHCR on a release with
  a generated SBOM, build provenance, and a keyless Cosign signature.

## Security issue resolution

- **Reporting**: see [SECURITY.md](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/SECURITY.md). Vulnerabilities are reported
  privately (via GitHub private advisories or by contacting a maintainer on LinkedIn),
  not in public issues.
- **Response**: a maintainer acknowledges the report, confirms the issue, prepares a fix
  on a private branch when warranted, and coordinates disclosure with the reporter.

## Appendix

- **Known limitations**: the human operator and the hub are trusted; the model is
  constrained but not sandboxed; add-on APIs (policy, HyperShift, ManagedClusterInfo)
  are feature-detected and degrade to a clear message when absent.
- **Related work and positioning**: see the README section "Related projects, and a note
  on the name" for how this project's trade-off (fixed tool surface, mandatory approval)
  differs from kubectl-granting alternatives.
