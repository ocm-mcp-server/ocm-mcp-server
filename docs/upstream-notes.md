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

**Target:** kyverno/policies (docs/policy contribution)

Validating workloads embedded inside another CR (here: ManifestWork
`spec.workload.manifests`) works well with `foreach`, but no policy in the
catalog demonstrates it. Contribute the three policies in `deploy/policies/`
as a "Multi-Cluster Guardrails" category example set.
