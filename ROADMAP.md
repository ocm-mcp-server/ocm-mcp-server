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
- [ ] Published evaluation results across multiple models (`eval/results/`).
- [ ] Recorded end-to-end demo of the remediation flow (MP4).

## Next

- [ ] **In-cluster deployment**: a Deployment manifest and a Helm chart so the server
      runs as a workload on the hub with its own ServiceAccount.
- [ ] **cluster-proxy transport**: reach spokes through the OCM cluster-proxy and
      managed-serviceaccount add-ons instead of direct kubeconfig contexts, so no spoke
      credentials live beside the server.
- [ ] **Structured audit sink**: optional export of the audit log to a SIEM or object
      store, in addition to the local append-only file.
- [ ] **Policy pack**: a small library of reusable Kyverno policies for common fleet
      guardrails, contributable upstream to kyverno/policies.
- [ ] Additional chaos classes: node pressure, network partitions, noisy neighbors.

## Later (0.3+)

- [ ] **Multi-tenancy**: per-team tool scoping and RBAC boundaries on one server.
- [ ] **Approval integrations**: mint approval tokens from a chat-ops or ticketing flow
      while keeping the content-bound, asymmetric-signature guarantee.
- [ ] **Progressive rollout tools**: first-class support for ManifestWorkReplicaSet
      progressive strategies and decision groups.
- [ ] **Signed audit**: tamper-evident audit log (hash chaining or signing).

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
