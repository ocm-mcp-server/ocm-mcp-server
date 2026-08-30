<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CNCF Sandbox readiness

This document is a self-check of how ocm-mcp-server measures up against the community,
governance, and security practices expected of a
[CNCF Sandbox](https://github.com/cncf/sandbox) project. It is used as a quality bar: a
transparent checklist of what is in place and what remains before applying.

## Project health and governance

| Expectation | Status | Where |
|---|---|---|
| OSI-approved open source license | Done | [LICENSE](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/LICENSE) (Apache-2.0) |
| Public repository and issue tracker | Done | GitHub |
| Governance model | Done | [GOVERNANCE.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/GOVERNANCE.md) |
| Maintainers listed | Done | [MAINTAINERS.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/MAINTAINERS.md) |
| Adopters page | Done (open for entries) | [ADOPTERS.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/ADOPTERS.md) |
| Code of Conduct (CNCF CoC) | Done | [CODE_OF_CONDUCT.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/CODE_OF_CONDUCT.md) |
| Contributing guide | Done | [CONTRIBUTING.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/CONTRIBUTING.md) |
| DCO sign-off on commits | Done | enforced by the `dco` job on every pull request; early single-maintainer history predates the practice |
| Public roadmap | Done | [ROADMAP.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/ROADMAP.md) |

## Security

| Expectation | Status | Where |
|---|---|---|
| Security disclosure policy | Done | [SECURITY.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/SECURITY.md) |
| Documented threat model | Done | [docs/guardrails.md](guardrails.md) |
| Security self-assessment | Done | [docs/security-self-assessment.md](security-self-assessment.md) |
| Least-privilege deployment identity | Done | [deploy/rbac.yaml](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/deploy/rbac.yaml) |
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
| In-cluster deployment artifacts | Done | [Helm chart](https://github.com/ocm-mcp-server/ocm-mcp-server/tree/main/deploy/charts/ocm-mcp-server) + [Deployment manifest](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/deploy/deployment.yaml) |
| Evaluation evidence | Done | [published multi-model results](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/eval/results/README.md): agents from different vendors, 22 scenarios each on one build, raw per-run JSON with its own provenance, failures analyzed. Scenarios the agent refused without consulting the server are reported as not measured rather than counted as guardrail passes |

## What's left before applying

Sandbox readiness here is now entirely a community milestone. The engineering
side is done - DCO is enforced in CI and published tags are immutable - so the
three steps that remain all need people rather than code.

1. **Three maintainers from at least two employer organizations.** Current CNCF
   lifecycle requirements ask for this, with a Company/Organization column in
   MAINTAINERS.md. The project is single-maintainer today, and applications
   missing this are normally closed before TOC review - so this is the step that
   gates the rest.
   *Needs: people. This one cannot be engineered.*
2. **Public adopters.** [ADOPTERS.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/ADOPTERS.md)
   is open, and even one or two named evaluators materially strengthen an
   application.
   *Needs: one or two users willing to be named.*
3. **Documented OCM support.** The name builds on Open Cluster Management's
   acronym, and CNCF naming guidance asks for documented agreement from that
   project's leadership. The upstream issues are already drafted in
   [upstream notes](upstream-notes.md).
   *Needs: those issues filed, and a public statement of support or
   non-objection.*

## How to help

The highest-leverage contributions are: add yourself to [ADOPTERS.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/ADOPTERS.md),
publish evaluation results, or step up as a maintainer per
[GOVERNANCE.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/GOVERNANCE.md).
