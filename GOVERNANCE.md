<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Governance

ocm-mcp-server is an open, community-driven project. This document describes how
decisions are made and how anyone can grow into a position of responsibility. It is
intentionally lightweight for an early-stage project and will evolve as the community
grows.

## Principles

- **Open**: development, discussion, and decisions happen in public, on the issue
  tracker and pull requests.
- **Safety first**: every change is judged against the project's core promise - that
  an AI agent cannot take a dangerous action without policy admission and a human
  approval. New capabilities require a written safety rationale.
- **Meritocratic**: influence is earned through sustained, high-quality contribution,
  not affiliation.

## Roles

### Contributors

Anyone who opens an issue or a pull request is a contributor. There is no barrier to
entry beyond agreeing to the [Developer Certificate of Origin](CONTRIBUTING.md#sign-off)
and the [Code of Conduct](CODE_OF_CONDUCT.md).

### Maintainers

Maintainers review and merge contributions, triage issues, cut releases, and own the
project's direction. The current maintainers are listed in [MAINTAINERS.md](MAINTAINERS.md).

Maintainer responsibilities:

- review pull requests and provide actionable feedback;
- uphold the security model and the contribution and conduct standards;
- keep the roadmap and documentation honest and current;
- be responsive to security reports (see [SECURITY.md](SECURITY.md)).

### Becoming a maintainer

Contributors who show sustained, high-quality involvement can be nominated. Concretely,
a candidate has usually:

- landed several non-trivial pull requests, including at least one touching the
  security model or the tool surface;
- reviewed others' pull requests helpfully;
- demonstrated good judgment on the safety-first principle.

An existing maintainer nominates the candidate in a pull request adding them to
[MAINTAINERS.md](MAINTAINERS.md). Nomination is approved by lazy consensus (see below)
of the current maintainers.

## Decision making

The project uses **lazy consensus**. Most changes are approved simply by a maintainer
review and merge. For larger or contentious decisions (breaking changes, changes to the
security model, governance changes), a maintainer opens an issue or pull request
describing the proposal and allows at least **72 hours** for objections. If no
maintainer objects, the proposal is accepted. If consensus cannot be reached, a simple
majority vote of maintainers decides.

Any change that weakens a guardrail - the static checks, policy admission, the human
approval requirement, or least-privilege RBAC - requires explicit agreement from a
majority of maintainers and a documented rationale, never lazy consensus.

## Changing this document

Changes to governance follow the same process as other contentious decisions: a pull
request, a 72-hour comment window, and lazy consensus among maintainers.

## Code of Conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
