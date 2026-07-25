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
| SBOM | Dependencies are declared in `pyproject.toml`; a container image is published to GHCR on release. |

### Security links

| Document | URL |
|---|---|
| Security policy | [SECURITY.md](../SECURITY.md) |
| Guardrail model and threat model | [docs/guardrails.md](guardrails.md) |
| Architecture | [docs/architecture.md](architecture.md) |
| RBAC | [deploy/rbac.yaml](../deploy/rbac.yaml) |

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
   configured, reads events, logs, and health. Reads are summarized, never raw dumps.
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

- **Asymmetric, operation-bound human approval.** Approval is an Ed25519 signature over
  claims that bind the exact proposal content hash, the operation (`apply` or `rollback`),
  and an expiry. The signing (private) key is used only by the `ocm-mcp` CLI; the MCP
  server loads only the public key, so it can verify a token but can never mint one - even
  if the server, or an agent that reads the server's key material, is compromised. An
  apply token cannot authorize a rollback, and a change to any byte of the proposal
  invalidates the signature. The keypair is rotatable with `ocm-mcp rotate-secret`. For
  full isolation, run the CLI in a separate OS account, device, or chat-ops/ticket
  service; until then, shell/filesystem isolation between the agent and the CLI is
  mandatory.
- **Bound CSR approval.** The `accept` lifecycle action captures the pending join CSRs
  (name, UID, signer, subject) at propose time and approves only those exact CSRs at apply
  time, re-verifying the OCM signer and username - it never sweeps every CSR with a
  matching label, and never approves a CSR created after the human review.
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
- **Least-privilege RBAC.** The hub identity ([deploy/rbac.yaml](../deploy/rbac.yaml))
  grants exactly the verbs the tools use: read across the OCM API, plus create/delete
  ManifestWorks and ManagedClusterAddOns, patch ManagedClusters, and approve OCM join
  CSRs. No Secret reads, no exec, no arbitrary delete.

### Security-relevant

- **Static guardrails** reject privileged/host access, protected namespaces, unpinned
  images, and - by matching the full `apiVersion/kind` against an allow-list - group
  spoofing, indirect Secret access (`secretKeyRef`, secret/projected volumes), and
  arbitrary service accounts, before policy admission and again at apply time.
- **Apply-time integrity re-check** recomputes the proposal's content hash and re-runs
  guardrails at apply, closing a time-of-check/time-of-use gap on the state directory.
- **Bounded, timed spoke reads** cap result size and set request timeouts so one large
  cluster cannot hang or flood a call.
- **Read-only mode** (`OCM_MCP_READ_ONLY=1`) disables both write toolsets as a coarse
  backstop under the token gate.
- **Observability**: an append-only audit line per tool call (approval tokens redacted),
  plus optional OpenTelemetry spans.

## Project compliance

The project does not currently claim compliance with a specific external standard (for
example NIST SSDF or FedRAMP). It aligns with common cloud native security practices:
least privilege, defense in depth, no secrets in code, signed-off commits, and a
documented threat model.

## Secure development practices

- **Development pipeline**: contributions arrive via pull request. CI runs linting
  (ruff), the unit test suite (57 tests, no cluster required), and the offline Kyverno
  policy tests (12 cases). A CodeQL workflow scans the code.
- **Commits** are signed off under the Developer Certificate of Origin.
- **Dependencies** are pinned by lower bound in `pyproject.toml`; the runtime surface is
  small (the MCP SDK and the Kubernetes client).
- **Container image** is built from a minimal base and published to GHCR on tagged
  release.

## Security issue resolution

- **Reporting**: see [SECURITY.md](../SECURITY.md). Vulnerabilities are reported
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
