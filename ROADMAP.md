<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Roadmap

This roadmap is a statement of direction, not a commitment of dates. It is organized by
theme. Items move to a milestone when someone commits to owning them; help is welcome on
any of them (see [CONTRIBUTING.md](CONTRIBUTING.md)).

The north star does not change: an AI agent must never be able to take a dangerous
action on a fleet without policy admission and a human approval, and every action must
be auditable.

## Now (0.2.x)

- [x] Read coverage across the OCM API (inventory, placement, work, add-ons,
      registration, policy, ManagedClusterInfo) and HyperShift Hosted Control Planes.
- [x] Gated write path for ManifestWorks and OCM lifecycle actions.
- [x] Four-layer guardrail model with an offline Kyverno policy test suite.
- [x] `ocm-mcp doctor` live read-path smoke test.
- [x] RBAC that mirrors the full tool surface; Ed25519 approval keypair rotation.
- [x] Asymmetric, operation-bound approval (Ed25519): the CLI signs, the server
      holds only the public key; rollback is a distinct, separately approved operation.
- [x] Hardened static guardrails (exact GVK allow-list, indirect-Secret and
      arbitrary-service-account blocking) and CSR approval bound to the exact join CSRs.
- [x] One-time, issuer/audience-bound approval tokens; independent signer/verifier key
      paths; tamper-evident (hash-chained) audit log; hardened proposal state store.
- [x] Restricted-Pod-Security static guardrails and a requester-identity Kyverno policy
      that closes the unlabeled-ManifestWork bypass.
- [x] Reference in-cluster Deployment and Helm chart; optional Prometheus `/metrics`.
- [x] Supply chain: hash-pinned lock file, Dependabot, SBOM + provenance + Cosign
      signature on release images, dependency review and secret scanning in CI.
- [ ] Published evaluation results across multiple models (`eval/results/`).
- [ ] Recorded end-to-end demo of the remediation flow (MP4).

## Next

- [ ] **Off-box / external signer**: back the approval signer with a KMS, HSM, or a
      chat-ops/ticket service so the "compromised server cannot mint" property holds
      without relying on filesystem isolation.
- [ ] **Authenticated HTTP transport**: serve MCP over an authenticated transport (SSO /
      OAuth 2.1, per-tool scopes, actor propagated into approvals and audit) so the server
      can run standalone rather than attached over stdio.
- [ ] **Transactional state backend**: move the proposal store to CRDs (resourceVersion
      compare-and-swap) or a database, with a reconciler that recovers after a crash
      between cluster-write and state-save.
- [ ] **cluster-proxy transport**: reach spokes through the OCM cluster-proxy and
      managed-serviceaccount add-ons instead of direct kubeconfig contexts, so no spoke
      credentials live beside the server.
- [ ] **Structured audit sink**: export the hash-chained audit log to a SIEM or object
      store, with retention/legal-hold, in addition to the local file.
- [ ] **Policy pack**: a small library of reusable Kyverno policies for common fleet
      guardrails, contributable upstream to kyverno/policies.
- [ ] Additional chaos classes: node pressure, network partitions, noisy neighbors.

## Later (0.3+)

- [ ] **Multi-tenancy**: per-team tool scoping and RBAC boundaries on one server.
- [ ] **Approval integrations**: mint approval tokens from a chat-ops or ticketing flow
      while keeping the content-bound, asymmetric-signature guarantee.
- [ ] **Progressive rollout tools**: first-class support for ManifestWorkReplicaSet
      progressive strategies and decision groups.
- [ ] **Externally-anchored audit**: the audit log is already hash-chained (done); anchor
      or sign the chain head to a SIEM/object store so tail-truncation is also detectable.

## Project maturity

The project holds itself to CNCF-style community, governance, and security practices as a
quality bar.

- [x] Governance, maintainers, adopters, code of conduct, security policy, DCO.
- [x] Security self-assessment ([docs/security-self-assessment.md](docs/security-self-assessment.md)).
- [x] Self-check against CNCF Sandbox expectations ([docs/cncf-sandbox-readiness.md](docs/cncf-sandbox-readiness.md)).
- [ ] OpenSSF Best Practices badge (self-assessment in progress).

## How to influence the roadmap

Open an issue describing the problem you have (not just the feature you want), or add
yourself to [ADOPTERS.md](ADOPTERS.md) so your use case is visible. Maintainers weigh
real adoption heavily when prioritizing.
