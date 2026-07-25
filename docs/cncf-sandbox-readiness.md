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

## Where the project can go further

The practices above are strongest when a community forms around the code. The honest gaps
today:

- **A second maintainer.** The project is currently single-maintainer. Growing to at
  least two maintainers from different affiliations is the most important step.
- **Demonstrable adoption.** [ADOPTERS.md](../ADOPTERS.md) is open; even one or two
  public evaluators strengthen it.
- **Published evaluation results.** Running the harness against several models and
  publishing the numbers (including failures) turns the safety claims into evidence.
- **In-cluster deployment artifacts.** A Helm chart and Deployment manifest (see the
  [roadmap](../ROADMAP.md)) make it trivial to run the server as a hub workload.

## How to help

The highest-leverage contributions are: add yourself to [ADOPTERS.md](../ADOPTERS.md),
publish evaluation results, or step up as a maintainer per
[GOVERNANCE.md](../GOVERNANCE.md).
