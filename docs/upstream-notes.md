# Upstream gaps found while building this

Draft issue texts, ready to file against the respective projects. Once filed,
replace each draft with a link to the live issue.

## 1. MCP: first-class support for long-running operations

**Target:** modelcontextprotocol (specification / SDK discussion)

Applying a ManifestWork and waiting for the work agent to report `Applied` and
`Available` can take tens of seconds to minutes. Today a tool has two bad
options: block the call (client timeouts, no progress signal) or return
immediately (agent must poll a status tool, burning turns and tokens).

Proposal: a standard pattern for tools to return an *operation handle* with
streamed progress updates, so a client can await completion without polling.
Use case attached: multi-cluster remediation where apply → rollout → verify is
one logical operation with three observable phases.

## 2. OCM: lifecycle feedback hooks for ManifestWork consumers

**Target:** open-cluster-management-io/OCM

When a ManifestWork's embedded Deployment fails on the spoke (image pull,
admission rejection by a spoke-side policy), the failure surfaces in
`status.resourceStatus` conditions with limited detail and no event stream.
For agent feedback loops we want the *reason* (e.g. the spoke admission
message) propagated to the hub condition, so a proposer can self-correct
without spoke access.

## 3. Kyverno: document foreach-over-CR-embedded-manifests as a pattern

**Filed:** [kyverno/policies#1534](https://github.com/kyverno/policies/issues/1534) —
proposes the pattern, links the pack, and asks whether a new category or a single
well-documented exemplar is the better contribution before opening a PR.

Validating workloads embedded inside another CR (here: ManifestWork
`spec.workload.manifests`) works well with `foreach`, but no policy in the catalog
demonstrates it. The 9 policies in `deploy/policies/` are shaped for that contribution
rather than only for this repository: every one carries the catalog's
`policies.kyverno.io/minversion` annotation, and `deploy/policies/README.md` documents
the `foreach` pattern, the two identifiers an adopter has to change, and the offline
suite of 42 cases.

The 1.13 under-enforcement was deliberately **not** filed as a separate bug. A container
declaring both `runAsNonRoot: true` and `runAsUser: 0` is admitted on 1.13.0 and 1.13.6,
and rejected on 1.12.0 and on 1.15.0 and later — so it was introduced and fixed inside
that window. 1.13.6 was last patched in May 2025 and every supported release behaves
correctly, so a bug report would be noise for the maintainers. It is recorded in the
proposal instead, as the evidence for the `minversion: 1.15.0` floor: naming 1.12.0
would place a release that quietly weakens the control inside the supported range.

Reproducer, if it is ever needed: `kyverno apply
deploy/policies/restrict-manifestwork-pod-security.yaml --resource
deploy/policies/tests/resources.yaml` gives 7 failures on 1.13.x against 8 everywhere
else, with the `bad-run-as-root` fixture as the one that escapes.
