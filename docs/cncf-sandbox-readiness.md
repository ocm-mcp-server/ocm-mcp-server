<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CNCF Sandbox readiness

This document is a self-check of how ocm-mcp-server measures up against the community,
governance, and security practices expected of a
[CNCF Sandbox](https://github.com/cncf/sandbox) project. It is used as a quality bar: a
transparent checklist of what is in place and where the project can go further.

## Project health and governance

| Expectation | Status | Where |
|---|---|---|
| OSI-approved open source license | Done | [LICENSE](../LICENSE) (Apache-2.0) |
| Public repository and issue tracker | Done | GitHub |
| Governance model | Done | [GOVERNANCE.md](../GOVERNANCE.md) |
| Maintainers listed | Done | [MAINTAINERS.md](../MAINTAINERS.md) |
| Adopters page | Done (open for entries) | [ADOPTERS.md](../ADOPTERS.md) |
| Code of Conduct (CNCF CoC) | Done | [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) |
| Contributing guide | Done | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| DCO sign-off on commits | Partial | requested in the PR checklist; automated enforcement not yet wired, early history predates the practice |
| Public roadmap | Done | [ROADMAP.md](../ROADMAP.md) |

## Security

| Expectation | Status | Where |
|---|---|---|
| Security disclosure policy | Done | [SECURITY.md](../SECURITY.md) |
| Documented threat model | Done | [docs/guardrails.md](guardrails.md) |
| Security self-assessment | Done | [docs/security-self-assessment.md](security-self-assessment.md) |
| Least-privilege deployment identity | Done | [deploy/rbac.yaml](../deploy/rbac.yaml) |
| Static analysis in CI | Done | ruff + CodeQL workflows |
| OpenSSF Best Practices badge | In progress | self-assessment underway |

## Technical maturity

| Expectation | Status | Where |
|---|---|---|
| Working software, not a proposal | Done | full server + CLI + policies |
| Automated tests | Done | full unit suite (100% statement + branch coverage) plus offline Kyverno policy tests, in CI |
| Reproducible local environment | Done | `make bootstrap` (kind-based fleet) |
| Release automation | Done | tag-driven release + GHCR image publish |
| Documentation for new users | Done | README, wiki, deployment and context guides |
| In-cluster deployment artifacts | Done | [Helm chart](../deploy/charts/ocm-mcp-server) + [Deployment manifest](../deploy/deployment.yaml) |
| Evaluation evidence | Done | [published multi-model results](../eval/results/README.md): claude-sonnet-5 and gpt-5.6-sol, 22 scenarios each, safety 44/44, failures analyzed |

## Where the project can go further

The practices above are strongest when a community forms around the code. The honest gaps
today:

- **Maintainer diversity - the hard gate.** Current CNCF lifecycle requirements ask
  for at least **three maintainers from at least two employer organizations** (with a
  Company/Organization column in MAINTAINERS.md). The project is single-maintainer
  today; applications missing this are normally closed before TOC review. This is the
  single most important step, and it cannot be engineered - it takes community.
- **Demonstrable adoption.** [ADOPTERS.md](../ADOPTERS.md) is open; even one or two
  public evaluators strengthen it.
- **Upstream OCM engagement.** The name builds on Open Cluster Management's acronym;
  CNCF naming guidance asks for documented agreement from that project's leadership.
  File the drafted upstream issues ([upstream-notes](upstream-notes.md)) and obtain a
  public statement of support or non-objection before applying.
- **DCO enforcement and release immutability.** Wire automated DCO checking, and treat
  published version tags as immutable (a failed release rolls forward to the next
  patch version, never re-cuts the same tag).

## How to help

The highest-leverage contributions are: add yourself to [ADOPTERS.md](../ADOPTERS.md),
publish evaluation results, or step up as a maintainer per
[GOVERNANCE.md](../GOVERNANCE.md).
