<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CNCF Sandbox readiness

This document tracks how ocm-mcp-server maps to the expectations for a
[CNCF Sandbox](https://github.com/cncf/sandbox) project. It is a transparent checklist,
not a claim of acceptance. The project is independently maintained and has not yet
applied; this page exists so the path is legible and the gaps are honest.

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
| DCO sign-off on commits | Done | enforced in contribution flow |
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
| Automated tests | Done | 52 unit tests + 12 offline Kyverno policy tests, in CI |
| Reproducible local environment | Done | `make bootstrap` (kind-based fleet) |
| Release automation | Done | tag-driven release + GHCR image publish |
| Documentation for new users | Done | README, wiki, deployment and context guides |
| Evaluation evidence | Partial | eval harness present; multi-model results pending |

## What is deliberately still open

CNCF Sandbox is aimed at early projects, but a credible application benefits from a
little community around the code. The honest gaps today:

- **A second maintainer.** The project is currently single-maintainer. Growing to at
  least two maintainers from different affiliations is the most important step.
- **Demonstrable adoption.** [ADOPTERS.md](../ADOPTERS.md) is open; even one or two
  public evaluators strengthen the case.
- **Published evaluation results.** Running the harness against several models and
  publishing the numbers (including failures) turns the safety claims into evidence.
- **In-cluster deployment artifacts.** A Helm chart and Deployment manifest (see the
  [roadmap](../ROADMAP.md)) make it trivial to run the server as a hub workload.

## How to help

If you want to see this become a CNCF project, the highest-leverage contributions are:
add yourself to [ADOPTERS.md](../ADOPTERS.md), publish evaluation results, or step up as
a maintainer per [GOVERNANCE.md](../GOVERNANCE.md).
