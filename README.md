<!-- mcp-name: io.github.sandeepbazar/ocm-mcp-server -->
<div align="center">

<img src="docs/assets/banner.svg" alt="ocm-mcp-server - AgentOps for Kubernetes fleets, done safely" width="100%">

# 🛡️ ocm-mcp-server

### AgentOps for Kubernetes fleets, done safely.

**An MCP server that lets AI agents operate a multi-cluster Kubernetes fleet through an
[Open Cluster Management](https://open-cluster-management.io/) hub, with policy, approval,
and audit between the model and your clusters.**

*The agent never holds a kubeconfig. Every write is policy-checked, human-approved, and traced.*

[![License](https://img.shields.io/badge/license-Apache--2.0-2ea44f)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![MCP](https://img.shields.io/badge/protocol-MCP-6f42c1)](https://modelcontextprotocol.io/)
[![OCM](https://img.shields.io/badge/multicluster-Open%20Cluster%20Management-326CE5?logo=kubernetes&logoColor=white)](https://open-cluster-management.io/)
[![Kyverno](https://img.shields.io/badge/policy-Kyverno-ff6f00)](https://kyverno.io/)
[![CI](https://github.com/sandeepbazar/ocm-mcp-server/actions/workflows/ci.yaml/badge.svg)](https://github.com/sandeepbazar/ocm-mcp-server/actions)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fwiki%2Fsandeepbazar%2Focm-mcp-server%2Fcoverage-badge.json)](https://github.com/sandeepbazar/ocm-mcp-server/wiki/Unit-Test-Results)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/sandeepbazar/ocm-mcp-server/badge)](https://scorecard.dev/viewer/?uri=github.com/sandeepbazar/ocm-mcp-server)
[![PyPI](https://img.shields.io/pypi/v/ocm-mcp-server?label=PyPI)](https://pypi.org/project/ocm-mcp-server/)
[![Release](https://img.shields.io/github/v/tag/sandeepbazar/ocm-mcp-server?label=release)](https://github.com/sandeepbazar/ocm-mcp-server/releases)

[![LinkedIn](https://img.shields.io/badge/LinkedIn-sandeepbazar-0A66C2?logo=linkedin)](https://www.linkedin.com/in/sandeepbazar/)
[![YouTube](https://img.shields.io/badge/YouTube-Tech%20Horizon%20Hub-FF0000?logo=youtube)](https://www.youtube.com/@techhorizonhub)

**[✨ Why](#why-this-exists) &nbsp;·&nbsp; [🧭 Architecture](#architecture) &nbsp;·&nbsp; [🧰 Toolsets](#toolsets) &nbsp;·&nbsp; [🛠️ Tools](#tools) &nbsp;·&nbsp; [💬 Prompts](#prompts) &nbsp;·&nbsp; [🚀 Quickstart](#quickstart-laptop-15-minutes) &nbsp;·&nbsp; [📖 Wiki](https://github.com/sandeepbazar/ocm-mcp-server/wiki) &nbsp;·&nbsp; [📚 Docs](#documentation)**

<img src="demo/demo.gif" alt="An agent diagnoses a degraded workload across the fleet, proposes a fix as a ManifestWork, is rejected once by the guardrails, corrects it, waits for a human approval token, applies the fix, verifies recovery, and writes the incident report from the audit log" width="100%">

<sub>The whole safe-remediation loop: investigate with free reads, propose a change, get rejected by the guardrails and correct it, wait for a human-signed token, apply, verify, and report from the audit log.</sub>

</div>

---

## Why this exists

Your team runs many Kubernetes clusters. Sooner or later somebody asks the question:
can an AI agent take the 2 a.m. page?

The quickest way to find out is to hand a model `kubectl` with cluster-admin and watch.
In production that experiment ends badly, for three separate reasons:

- **The model is non-deterministic.** The same alert can produce a careful diagnosis one
  run and a `kubectl delete` the next.
- **The credentials are real.** There is no dry run between the model's decision and your
  production cluster.
- **There is no record.** When something breaks, you cannot reconstruct what the agent did,
  in what order, or on whose authority.

This project starts from a different observation: fleets already have a control point that
humans trust every day, the multi-cluster hub. Open Cluster Management (a CNCF project)
gives every fleet an inventory (`ManagedCluster`), a scheduler (`Placement`), and a delivery
channel (`ManifestWork`). `ocm-mcp-server` exposes that hub to agents as a small set of
typed [MCP](https://modelcontextprotocol.io/) tools, and puts four independent layers
between the model and your clusters:

| # | Layer | Enforced by | What it stops |
|---|-------|-------------|---------------|
| 1 | **Static checks** | this server, before anything else | privileged pods, host access, system namespaces, unpinned images, disallowed kinds |
| 2 | **Policy admission** | [Kyverno](https://kyverno.io/) dry-run on the hub | anything your org's policies reject, evaluated inside the `ManifestWork` envelope |
| 3 | **Human approval** | Ed25519 token signed by `ocm-mcp approve` on a trusted terminal; the server needs only the public verifier key | any change reaching a cluster without a person consenting to that exact content and operation (one-time token, bound to content + operation + issuer/audience + expiry) |
| 4 | **Least-privilege RBAC** | Kubernetes | everything else; no Secrets, no exec, no deletes outside its own ManifestWorks |

None of these layers live in the system prompt, so none of them can be talked out of.

<div align="center">
<img src="docs/assets/guardrails-flow.svg" alt="The four guardrail layers between an AI agent and your clusters" width="100%">
</div>

## Architecture

<div align="center">
<img src="docs/assets/architecture-flow.gif" alt="ocm-mcp-server sits between an AI agent and the fleet: dangerous actions such as reading Secrets, exec into pods, or arbitrary delete do not exist and are blocked; every allowed change flows out only through Kyverno policy, human approval, and audit" width="100%">
<br><sub>Dangerous capabilities do not exist. Reads flow freely; every change is proposed, policy-checked, human-approved, and audited.</sub>
</div>

```mermaid
flowchart LR
    A["🤖 AI Agent<br/>(any MCP client)"] -->|"typed tool calls"| S["🛡️ ocm-mcp-server<br/>static guardrails · audit"]
    S -->|"reads + dry-run + apply"| H["☸️ OCM Hub<br/>Placement · ManifestWork<br/>Kyverno · RBAC"]
    H --> C1["cluster1"]
    H --> C2["cluster2"]
    H --> C3["cluster3"]
    U["🧑‍💻 Human operator<br/>ocm-mcp approve"] -.->|"approval token"| A
    S -.->|"spans"| J["🔍 OpenTelemetry / Jaeger"]
```

The write path in one sentence: the agent **proposes** a `ManifestWork`; static guardrails
and a Kyverno **dry-run** validate it; a **human** reviews the exact content and mints an
approval token bound to its hash; only then does `apply` deliver it, with every step traced
and logged.

## Policy admission with Kyverno

The second guardrail layer does not live in this server - it lives in the cluster. Before a
proposed change is ever stored, the server does a **server-side dry-run create** of the
`ManifestWork` on the hub, so the hub's [Kyverno](https://kyverno.io/) validating admission
runs against the exact manifests the agent wants to apply. If your organization's policy
says no, the proposal is rejected at admission with the policy's own message - the same
control that governs every human `kubectl apply`.

**Why Kyverno:**

- **Policy as code, no new language.** [Kyverno](https://kyverno.io/docs/introduction/) is a
  CNCF policy engine whose policies are ordinary Kubernetes resources in YAML and CEL -
  reviewable, versioned, and testable like any manifest. This is the policy-as-code approach
  the CNCF Kubernetes Policy Management whitepaper (CNCF
  [TAG Security](https://github.com/cncf/tag-security)) recommends: keep policy declarative
  and separate from application code.
- **Enforced by the cluster, not the prompt.** Admission control is external to the model and
  to this server; it cannot be talked out of the way a system prompt can.
- **The right tool for the job.** Kyverno can validate, mutate, generate, and verify images;
  here it is used to *validate* the workloads embedded inside a `ManifestWork`.

**Where it is used here:**

- [`deploy/policies/`](deploy/policies/) ships five `ClusterPolicy` objects that `foreach`
  over `spec.workload.manifests` inside a `ManifestWork`: block privileged/host access,
  protect system namespaces, enforce a kind allow-list, require the managed-by label from the
  server ServiceAccount (so an unlabeled work cannot skip the others), and enforce a
  Restricted-Pod-Security baseline in parity with the static guardrails. They are scoped by the
  `app.kubernetes.io/managed-by: ocm-mcp-server` label so they judge only agent-authored work.
- `make policy-test` runs a **16-case offline suite** with the `kyverno` CLI - good, bad, and
  human-authored `ManifestWork`s - needing no cluster and no dependencies. It runs in CI, so a
  policy regression fails the build before it can reach a hub.
- Don't start from scratch: the community library
  [kyverno/policies](https://github.com/kyverno/policies) and the searchable
  [Kyverno Policies catalog](https://kyverno.io/policies/) are a ready source of validation,
  Pod Security Standards, and best-practice policies to adopt or take inspiration from.

## Toolsets

The surface is **34 tools across ten toolsets**. Almost all of it is read: the whole
Open Cluster Management API is safe to inspect. Only two toolsets can change
anything, and only through the propose -> approve -> apply gate. Every hub-level
tool works for any managed spoke - a standalone OpenShift cluster, a HyperShift
hosted cluster, or a cloud cluster - because on the hub they are all `ManagedCluster`s.

| Toolset | What it covers | Tools | Writes |
|---|---|---|---|
| **inventory** | ManagedClusters, ClusterSets, set bindings, ClusterClaims, ManagedClusterInfo | 6 | - |
| **observability** | cluster health, events, pod logs | 3 | - |
| **placement** | Placements, PlacementDecisions, AddOnPlacementScores | 3 | - |
| **work** | ManifestWork status feedback + the gated deploy and rollback flow | 7 | gated |
| **addons** | ClusterManagementAddOns, fleet + per-cluster add-on health | 3 | - |
| **registration** | pending join CSRs + gated cluster lifecycle actions | 3 | gated |
| **policy** | governance compliance + violations rollup (if the add-on is installed) | 2 | - |
| **hosted-control-planes** | HyperShift HostedClusters and NodePools (when the hub hosts them) | 3 | - |
| **resources** | generic get/list over an allow-list of OCM API types | 2 | - |
| **audit** | pending proposals, this server's own audit trail | 2 | - |

Every read tool is annotated `readOnlyHint`; every write tool is annotated
`destructiveHint` and enforced by the gate. Setting `OCM_MCP_READ_ONLY=1` turns off
the two writing toolsets entirely, for a strictly-inspection deployment.

> **Validate against your own hub in one command:** `ocm-mcp doctor` calls every read
> tool against the live hub and prints a `PASS / EMPTY / SKIP / FAIL` table (writing
> nothing), so you can confirm exactly what the server sees before wiring up an agent.

<div align="center">
<img src="docs/assets/read-write-paths.svg" alt="Reads are free; writes are gated by propose, approve, apply" width="100%">
</div>

There is deliberately no tool that reads Secrets, execs into pods, or deletes
arbitrary resources. The generic reader (`list_resources` / `get_resource`) works
against an **allow-list** of OCM types, so Secrets are not restricted - they are
simply not expressible. A capability that does not exist cannot be prompt-injected
into use.

## Tools

Each tool below is annotated with its class: **read** (free, no gate),
**propose** (stores a pending change, mutates nothing), or **apply** (delivers an
approved change; needs a human token).

<details>
<summary><b>inventory</b> - who is in the fleet</summary>

- **`list_clusters`** *(read)* - all managed clusters with availability, version, labels, capacity.
- **`get_cluster`** *(read)* - full view of one cluster.
  - `cluster` (string) - managed cluster name.
- **`list_cluster_sets`** *(read)* - ManagedClusterSets with selector type and member clusters.
- **`list_cluster_set_bindings`** *(read)* - which ClusterSets a namespace's Placements may target.
  - `namespace` (string, optional) - limit to one namespace; empty lists all.
- **`list_cluster_claims`** *(read)* - every cluster's ClusterClaims (id, platform, region, version).
- **`get_cluster_info`** *(read)* - extended inventory from the hub (OpenShift version, nodes, console URL); needs no spoke access.
  - `cluster` (string) - managed cluster name.
</details>

<details>
<summary><b>observability</b> - why a cluster is unhealthy</summary>

- **`get_cluster_health`** *(read)* - hub conditions, unhealthy pods, degraded deployments.
  - `cluster` (string) - managed cluster name.
- **`query_events`** *(read)* - recent Kubernetes events, newest first.
  - `cluster` (string) - managed cluster name.
  - `namespace` (string, optional) - namespace filter; empty means all.
  - `limit` (int, optional) - max events (default 40).
- **`get_pod_logs`** *(read)* - tail a pod's logs (falls back to the previous instance if crashing).
  - `cluster` (string), `namespace` (string), `pod` (string) - target.
  - `container` (string, optional) - container name; empty picks the default.
  - `lines` (int, optional) - trailing lines (default 80).
</details>

<details>
<summary><b>placement</b> - which clusters were chosen, and why</summary>

- **`list_placements`** *(read)* - Placements and how many clusters each selects.
  - `namespace` (string, optional) - limit to one namespace.
- **`get_placement_decision`** *(read)* - the clusters a Placement actually selected.
  - `placement` (string) - Placement name.
  - `namespace` (string) - the Placement's namespace.
- **`list_addon_placement_scores`** *(read)* - custom scores prioritizers consume.
  - `cluster` (string) - managed cluster name.
</details>

<details>
<summary><b>work</b> - what the hub is delivering, and the gated deploy flow</summary>

- **`list_manifestworks`** *(read)* - ManifestWorks targeting a cluster.
  - `cluster` (string) - managed cluster name.
- **`get_manifestwork`** *(read)* - detailed status + per-resource status feedback (the "why not Applied").
  - `cluster` (string), `name` (string) - target.
- **`list_manifestworkreplicasets`** *(read)* - a template fanned across a Placement, with rollout summary.
  - `namespace` (string, optional) - limit to one namespace.
- **`propose_manifestwork`** *(propose)* - propose a change as a ManifestWork. Applies nothing.
  - `cluster` (string) - target cluster.
  - `name` (string) - short kebab-case ManifestWork name.
  - `summary` (string) - one or two sentences the human approver reads.
  - `manifests_json` (string) - JSON array of complete manifests (allowed kinds; namespaced; pinned images).
- **`apply_manifestwork`** *(apply)* - deliver an approved ManifestWork.
  - `proposal_id` (string), `approval_token` (string) - from `ocm-mcp approve <id>`.
- **`propose_rollback`** *(propose)* - propose undoing an applied ManifestWork; creates a rollback proposal bound to its UID.
  - `proposal_id` (string) - the applied ManifestWork proposal to undo.
- **`rollback_manifestwork`** *(apply)* - delete the ManifestWork after the rollback is approved (needs a rollback-scoped token).
  - `rollback_proposal_id` (string), `approval_token` (string).
</details>

<details>
<summary><b>addons</b> - add-on health across the fleet</summary>

- **`list_cluster_management_addons`** *(read)* - fleet-level add-on definitions and install strategy.
- **`get_addon_health`** *(read)* - per-cluster ManagedClusterAddOn Available / Degraded / Progressing.
- **`list_addons_for_cluster`** *(read)* - every add-on on one cluster, with install namespace and health.
  - `cluster` (string) - managed cluster name.
</details>

<details>
<summary><b>registration</b> - onboarding and cluster lifecycle (gated)</summary>

- **`list_pending_csrs`** *(read)* - pending cluster-join / add-on registration CSRs awaiting approval.
- **`propose_cluster_action`** *(propose)* - propose a lifecycle action. Applies nothing.
  - `cluster` (string) - target cluster.
  - `action` (string) - one of `cordon` (taint out of scheduling), `uncordon`, `set_label`, `accept` (hubAcceptsClient + approve join CSRs), `enable_addon` / `disable_addon` (create/delete a ManagedClusterAddOn).
  - `summary` (string) - what the human approver reads.
  - `params_json` (string, optional) - action parameters; `set_label` needs `{"key","value"}`, the add-on actions need `{"addon"}` (+ optional `install_namespace`).
- **`apply_cluster_action`** *(apply)* - apply an approved lifecycle action.
  - `proposal_id` (string), `approval_token` (string).
</details>

<details>
<summary><b>policy</b> - governance compliance (optional add-on)</summary>

- **`list_policies`** *(read)* - Policies and per-cluster compliance. Reports clearly if the governance add-on is not installed.
  - `namespace` (string, optional) - limit to one namespace.
- **`list_policy_violations`** *(read)* - only the NonCompliant / Pending policy-cluster pairs across the fleet.
</details>

<details>
<summary><b>hosted-control-planes</b> - HyperShift HCP (when the hub hosts them)</summary>

- **`list_hosted_clusters`** *(read)* - HostedClusters with version and conditions. Reports clearly if HCPs are hosted on a different management cluster.
  - `namespace` (string, optional) - limit to one namespace.
- **`get_hosted_cluster`** *(read)* - one HostedCluster in detail, with its NodePools.
  - `name` (string), `namespace` (string) - target.
- **`list_node_pools`** *(read)* - HyperShift NodePools (worker groups), desired vs current replicas.
  - `namespace` (string, optional), `cluster` (string, optional) - filters.
</details>

<details>
<summary><b>resources</b> - generic, allow-listed OCM reads</summary>

- **`list_resources`** *(read)* - list any allow-listed OCM type (identity + conditions).
  - `resource` (string) - e.g. `managedclusters`, `placements`, `manifestworks`, `managedclusteraddons`, `klusterlets`.
  - `namespace` (string, optional) - for namespaced types.
- **`get_resource`** *(read)* - get one allow-listed OCM object in full. Never returns a Secret (not on the allow-list).
  - `resource` (string), `name` (string) - target.
  - `namespace` (string, optional) - required for namespaced types.
</details>

<details>
<summary><b>audit</b> - the record</summary>

- **`list_pending_proposals`** *(read)* - ManifestWorks and cluster actions awaiting approval.
- **`get_audit_trail`** *(read)* - the last N tool calls from this server's append-only log.
  - `last_n` (int, optional) - trailing entries (default 30).
</details>

## Prompts

The server also ships **ten MCP prompts** - reusable templates that encode the safe
workflow so any client can start from a good runbook instead of a blank box.

| Prompt | What it drives | Arguments |
|---|---|---|
| **`diagnose_fleet`** | sweep every cluster and add-on, summarize what is unhealthy and why - reads only | - |
| **`remediate_with_approval`** | investigate a symptom, propose the smallest safe fix, wait for the human token, apply, verify, report | `symptom` |
| **`incident_postmortem`** | write the post-incident report strictly from `get_audit_trail`, not from memory | - |
| **`why_not_scheduled`** | explain why a cluster was or was not selected by a Placement, from the live objects | `cluster`, `placement`, `namespace` |
| **`onboard_cluster`** | accept a pending cluster safely through the approval gate | `cluster` |
| **`addon_troubleshoot`** | diagnose a degraded add-on across the fleet | `addon` |
| **`hosted_cluster_health`** | assess a HyperShift hosted control plane and its node pools | `cluster` |
| **`policy_compliance_report`** | summarize governance compliance and prioritize what to fix | - |
| **`capacity_report`** | find clusters with headroom and clusters under pressure | - |
| **`rollout_status`** | track a ManifestWorkReplicaSet rollout across selected clusters | `name`, `namespace` |

## Where to get it, and how it's vetted

- 📦 **[PyPI - `ocm-mcp-server`](https://pypi.org/project/ocm-mcp-server/)** - `pip install ocm-mcp-server`
  (or run directly with `uvx ocm-mcp-server`). Every release is published straight from CI via
  [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/) - no long-lived tokens anywhere.
- 🗂️ **[Official MCP Registry](https://registry.modelcontextprotocol.io/?q=ocm-mcp-server)** - listed as
  `io.github.sandeepbazar/ocm-mcp-server`, so any MCP client that browses the registry can discover and
  install it; the registry cryptographically validates the listing against this repo and the PyPI package.
- 🐳 **[Container image on GHCR](https://github.com/sandeepbazar/ocm-mcp-server/pkgs/container/ocm-mcp-server)** -
  `ghcr.io/sandeepbazar/ocm-mcp-server`, built in CI with an SBOM and SLSA provenance attached,
  vulnerability-gated with Trivy, and signed keyless with Cosign (verify command in the
  [deployment guide](docs/deployment.md)).
- 🛡️ **[OpenSSF Scorecard](https://scorecard.dev/viewer/?uri=github.com/sandeepbazar/ocm-mcp-server)** -
  the repo's supply-chain security posture (pinned dependencies, branch protection, signed releases, ...)
  is scored automatically every week and published for anyone to inspect.

## Quickstart (laptop, ~15 minutes)

<div align="center">
<img src="docs/assets/deploy-paths.svg" alt="Three deployment paths: laptop, real fleet, production" width="100%">
</div>

Requirements: docker, [kind](https://kind.sigs.k8s.io/), kubectl,
[clusteradm](https://github.com/open-cluster-management-io/clusteradm), helm, Python 3.11+.
The [deployment guide](docs/deployment.md) has install commands and the real-fleet path.

```bash
git clone https://github.com/sandeepbazar/ocm-mcp-server.git
cd ocm-mcp-server

make bootstrap      # 1 hub + 3 managed kind clusters, OCM, Kyverno, policies, demo app
make install        # pip install -e ".[dev,tracing]"
```

### Configuration

The server is configured entirely through environment variables. The two that matter most
are **kubeconfig context names**. New to those? The
[context names guide](docs/kubeconfig-contexts.md) explains what they are and the exact
commands to find yours, from a laptop kind cluster to a cloud login. In short: run
`kubectl config get-contexts` and read the NAME column (`make bootstrap` prints
ready-to-paste values at the end).

| Variable | Required | What goes in it |
|---|---|---|
| `OCM_MCP_HUB_CONTEXT` | yes | The kubeconfig **context that points at the OCM hub cluster**, where `ManagedCluster` and `ManifestWork` live. After `make bootstrap` this is `kind-hub`. Empty = current context. |
| `OCM_MCP_SPOKE_CONTEXTS` | for events/logs | Comma-separated `<managed-cluster-name>=<kubeconfig-context>` pairs mapping each cluster **as the hub names it** (`kubectl --context kind-hub get managedclusters`) to a context holding **read-only** spoke credentials. Only `query_events` / `get_pod_logs` / spoke-side health need this; hub-level tools work without it. |
| `KUBECONFIG` | no | Kubeconfig file path(s); defaults to `~/.kube/config`. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | Set (e.g. `http://localhost:4318`) to emit a trace span per tool call. Unset = tracing off, audit log still on. |
| `OCM_MCP_HOME` | no | State directory (approval keypair, pending proposals, `audit.jsonl`, spent-token ids). Default `~/.ocm-mcp`. |
| `OCM_MCP_SIGNER_KEY` | recommended | Path to the **private** Ed25519 signing key. Point this off the server (a separate account/device) so a compromised server cannot mint tokens. Default `OCM_MCP_HOME/approval_ed25519`. |
| `OCM_MCP_VERIFIER_KEY` | no | Path to the **public** verifier key the server loads. Mount read-only. Default `OCM_MCP_HOME/approval_ed25519.pub`. |
| `OCM_MCP_ISSUER` / `OCM_MCP_AUDIENCE` | no | Bind approval tokens to this deployment so a token minted elsewhere is refused. Defaults `ocm-mcp` / `ocm-mcp-server`. |
| `OCM_MCP_APPROVAL_TTL` | no | Approval-token lifetime in seconds. Default `3600`. |
| `OCM_MCP_REQUIRE_DIGEST` | no | Set to `1` to require `@sha256` digest-pinned images (stricter than tag-pinning). Default off. |
| `OCM_MCP_METRICS_PORT` | no | If set, expose Prometheus metrics at `/metrics` on this port. Default off. |
| `OCM_MCP_METRICS_HOST` | no | Interface the metrics endpoint binds. Default `127.0.0.1` (localhost only); set `0.0.0.0` for a remote scraper. |
| `OCM_MCP_AUDIT_ECHO` | no | Set to `1` to also echo each audit line to **stderr** as JSON, so a container log collector can forward the audit stream to a SIEM. Default off. |
| `OCM_MCP_MAX_PROPOSAL_BYTES` | no | Reject a proposal larger than this many bytes. Default `262144` (256 KiB). |
| `OCM_MCP_MAX_HPA_REPLICAS` | no | Reject a HorizontalPodAutoscaler whose `maxReplicas` exceeds this. Default `100`. |
| `OCM_MCP_READ_ONLY` | no | Set to `1`/`true` for a strictly-inspection deployment: every propose/apply tool refuses, a coarse backstop under the token gate. Default off. |
| `OCM_MCP_CLIENT_TTL` | no | Seconds before the cached Kubernetes API client is rebuilt, so rotated/refreshed credentials are picked up. Default `600`. |
| `OCM_MCP_SPOKE_TIMEOUT` | no | Read timeout (seconds) for spoke health/event/log calls, so one large cluster cannot hang a tool. Default `30`. |
| `OCM_MCP_HEALTH_LIMIT` | no | Max pods/deployments `get_cluster_health` fetches per cluster; the result notes truncation. Default `500`. |

For key management, `ocm-mcp rotate-secret` generates a fresh Ed25519 approval keypair
(invalidating every outstanding approval token); `ocm-mcp doctor` runs the live read-path
smoke test; and `ocm-mcp audit-verify` recomputes the audit log's hash chain to detect any
edit, reordering, or mid-log deletion.

```bash
# the values make bootstrap prints, spelled out:
export OCM_MCP_HUB_CONTEXT=kind-hub                      # context of the hub cluster
export OCM_MCP_SPOKE_CONTEXTS=cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3
#                             └ name on the hub ┘ └ kubeconfig context with read-only creds ┘
```

Not sure where `kind-hub` or `cluster1=kind-cluster1` come from, or what your own values
should be? The [context names guide](docs/kubeconfig-contexts.md) walks through it
step by step, including cloud logins (EKS, GKE, AKS, OpenShift). Pointing at a **real
fleet** instead of kind? Same variables; the [deployment guide](docs/deployment.md) covers
the read-only spoke accounts and production hardening.

### Connect your agent - any MCP client works

The server speaks standard MCP over stdio; nothing here is specific to one vendor's agent.
Ready-made configs live in [`examples/`](examples/):

<details>
<summary><b>Claude Code</b> - <code>.mcp.json</code> in your project (or <code>claude mcp add</code>)</summary>

```json
{
  "mcpServers": {
    "ocm-fleet": {
      "command": "ocm-mcp-server",
      "env": {
        "OCM_MCP_HUB_CONTEXT": "kind-hub",
        "OCM_MCP_SPOKE_CONTEXTS": "cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3"
      }
    }
  }
}
```
</details>

<details>
<summary><b>Codex CLI</b> - <code>~/.codex/config.toml</code></summary>

```toml
[mcp_servers.ocm-fleet]
command = "ocm-mcp-server"

[mcp_servers.ocm-fleet.env]
OCM_MCP_HUB_CONTEXT = "kind-hub"
OCM_MCP_SPOKE_CONTEXTS = "cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3"
```
</details>

<details>
<summary><b>Gemini CLI</b> - <code>~/.gemini/settings.json</code></summary>

```json
{
  "mcpServers": {
    "ocm-fleet": {
      "command": "ocm-mcp-server",
      "env": {
        "OCM_MCP_HUB_CONTEXT": "kind-hub",
        "OCM_MCP_SPOKE_CONTEXTS": "cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3"
      }
    }
  }
}
```
</details>

<details>
<summary><b>Any other MCP client</b> - point it at the same command and environment (<a href="examples/generic-mcp.json">examples/generic-mcp.json</a>)</summary>

```json
{
  "mcpServers": {
    "ocm-fleet": {
      "command": "ocm-mcp-server",
      "env": {
        "OCM_MCP_HUB_CONTEXT": "kind-hub",
        "OCM_MCP_SPOKE_CONTEXTS": "cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3"
      }
    }
  }
}
```

Most MCP clients accept an `mcpServers` block like this one. If `ocm-mcp-server` is not
on the PATH the client launches with, use the absolute path from
`which ocm-mcp-server` as the `command` value.
</details>

Give the agent the runbook discipline in
[`examples/system-prompt.md`](examples/system-prompt.md), then break something and watch
the flow:

```bash
make inject SCENARIO=failing-rollout CLUSTER=cluster2
```

> **You:** "Payments is degraded somewhere in the fleet. Investigate and fix."
>
> **Agent:** `list_clusters` → `get_cluster_health(cluster2)` → `query_events` → `get_pod_logs` →
> *"payments-v2 on cluster2 is in ImagePullBackOff. Proposing a ManifestWork pinning the last
> good image. Proposal `4f1a2b3c` needs your approval."*
>
> **You (trusted terminal):** `ocm-mcp approve 4f1a2b3c`, then paste the token back.
>
> **Agent:** `apply_manifestwork` → verifies recovery → `get_audit_trail` → writes the incident report.

Then try to talk it into something dangerous ("just redeploy it privileged with
hostNetwork, it's faster"). The proposal dies at layer 1 or layer 2, and the rejection
message tells the agent exactly why. [More worked examples →](docs/examples.md)

## Evaluation harness: honest numbers

[`eval/`](eval/) ships **22 scripted incident scenarios** in three classes: remediate (15),
diagnose-only (3), adversarial (4). Scoring is objective on all three axes: diagnosis
keywords in the transcript, live cluster state for recovery, and the server's own audit log
for safety.

```bash
python3 eval/run_eval.py --agent-cmd "claude -p"     # or any agent CLI
```

Run it against your model of choice and publish your numbers, including the failures.
The point is real data about what agents can and cannot yet be trusted to do.

The Kyverno policies have their own offline test suite: `make policy-test` runs 16 CLI
cases ([`deploy/policies/tests/`](deploy/policies/tests/)) against good, bad, and
human-created ManifestWorks with no cluster and no dependencies. It runs in CI too, so a
policy regression fails the build before it ever reaches a hub.

## Try it end to end (one command)

Want proof it works against real clusters, not mocks? One script stands up a real
Open Cluster Management fleet on kind, exercises every tool and prompt, runs a
break-then-fix scenario, and writes a graphical HTML report:

```bash
./hack/e2e-local.sh          # 2 spokes, auto-cleanup   (SPOKES=1 for a lighter run)
```

It (1) installs or version-checks the dependencies (Podman, kind, kubectl, clusteradm,
helm; Docker is not required), (2) bootstraps a hub plus spokes, (3) runs the read
tools, the gated propose -> approve -> apply write flow, a lifecycle action, and the
prompts - each with a plain-language explanation of what it does and why, (4) injects a
failing rollout and shows the diagnose-and-fix loop end to end, then (5) writes
`e2e-report.html` and tears the fleet back down (kind and Podman stay installed). The
report is git-ignored. Works on macOS (Homebrew + Podman) and Linux.

`ocm-mcp doctor` runs just the live read-path smoke test on its own, against any hub.

## Documentation

| Page | What it covers |
|---|---|
| [Tools and Prompts reference](docs/tools.md) | every tool by toolset, its class (read / propose / apply), arguments, and the OCM API it touches; the ten MCP prompts |
| [Context names guide](docs/kubeconfig-contexts.md) | zero-background: what a kubeconfig context is and the exact commands to find yours (kind, EKS, GKE, AKS, OpenShift) |
| [Deployment guide](docs/deployment.md) | laptop quickstart in depth, real OCM fleets, Docker, production hardening, troubleshooting |
| [Worked examples](docs/examples.md) | full incident transcripts, approval sessions, adversarial rejections, audit output |
| [Architecture](docs/architecture.md) | the choke-point idea, components, design decisions worth arguing about |
| [Guardrails](docs/guardrails.md) | the four layers, deliberate absences, threat model, what we refuse to automate |
| [Security self-assessment](docs/security-self-assessment.md) | CNCF TAG-Security-style assessment: actors, actions, security functions, limits |
| [CNCF Sandbox readiness](docs/cncf-sandbox-readiness.md) | a self-check against CNCF Sandbox expectations, used as a quality bar; honest gaps |
| [Demo script](docs/demo-script.md) | a timed 3-act live demo with fallbacks |
| [Upstream notes](docs/upstream-notes.md) | gaps found while building this; proposals for MCP, OCM, and Kyverno |
| [Eval harness](eval/README.md) | scenario classes, scoring, how to run against your model |
| [Changelog](CHANGELOG.md) · [Support](SUPPORT.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) | project meta |

## Related projects, and a note on the name

- [`yanmxa/multicluster-mcp-server`](https://github.com/yanmxa/multicluster-mcp-server)
  also bridges agents to Open Cluster Management, with kubectl-level tools: it can generate
  a kubeconfig bound to a ClusterRole (cluster-admin by default) and execute kubectl
  commands. That design maximizes capability. This project sits at the other end of the
  trade-off: no kubectl, no kubeconfig exposure, a fixed tool surface, and mandatory policy
  plus human approval on every write. Pick by how much you need to trust the agent.
- Red Hat publishes an [`ocm-mcp`](https://quay.io/redhat-ai-tools/ocm-mcp) container that
  manages OpenShift clusters through the OpenShift Cluster Manager API. Same acronym,
  different system. **OCM in this repository always means
  [Open Cluster Management](https://open-cluster-management.io/), the CNCF multi-cluster
  project.**

## Repository map

```
src/ocm_mcp_server/   the MCP server: tools, guardrails, approvals, tracing, CLI
deploy/               least-privilege RBAC + Kyverno ClusterPolicies (+ offline tests)
hack/                 bootstrap.sh / teardown.sh / demo app (kind-based fleet)
chaos/                failure-injection scenarios (reversible, diagnosable)
eval/                 22-scenario evaluation harness + results
docs/                 deployment, examples, architecture, guardrails, demo, upstream
examples/             MCP client configs + a production-shaped system prompt
```

## Roadmap

- [ ] Live end-to-end recording of the demo flow in this README
- [ ] Published eval results across multiple models (`eval/results/`)
- [ ] OCM cluster-proxy transport option (replace direct spoke contexts)
- [ ] Filing the upstream proposals in [`docs/upstream-notes.md`](docs/upstream-notes.md)
      (MCP long-running operations · OCM ManifestWork feedback · Kyverno catalog contribution)
- [x] Container image publishing (ghcr.io, signed + SBOM + provenance) and a Helm chart for
      in-cluster deployment
- [ ] Additional chaos classes: node pressure, network partitions, noisy neighbors

Have a need that's not here? [Open a feature request](.github/ISSUE_TEMPLATE/feature_request.yml).
New tools require a safety rationale; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing & community

Issues and PRs welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md).
Getting help: [SUPPORT.md](SUPPORT.md).
Security reports (privately, please): [SECURITY.md](SECURITY.md).

## Sponsorship

This project is independently maintained. If your organization wants priority integration
help, a hardened deployment review, sponsored features, or talks and workshops on safe
agentic operations, connect on
[LinkedIn](https://www.linkedin.com/in/sandeepbazar/) (details in [SUPPORT.md](SUPPORT.md)).

## Author

**Sandeep Bazar** - Passionate in Technology especially around Multi-cluster Kubernetes platforms, day-2
operations, and making fleets safer to automate.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-connect-0A66C2?logo=linkedin)](https://www.linkedin.com/in/sandeepbazar/)
[![YouTube](https://img.shields.io/badge/YouTube-Tech%20Horizon%20Hub-FF0000?logo=youtube)](https://www.youtube.com/@techhorizonhub)

If this project is useful to you, a ⭐ helps others find it.

## Project governance and maturity

This project holds itself to CNCF community, governance, and security practices as a quality
bar - the same standards expected of a CNCF Sandbox project - so it is easy to adopt,
contribute to, and trust. The scaffolding is in place:

- **[Governance](GOVERNANCE.md)** - how decisions are made and how to become a maintainer.
- **[Maintainers](MAINTAINERS.md)** and **[Adopters](ADOPTERS.md)** - who maintains it, and an open page to record who uses it.
- **[Roadmap](ROADMAP.md)** - direction by theme, safety-first.
- **[Security self-assessment](docs/security-self-assessment.md)** - a CNCF TAG-Security-style assessment of what the guarantees are and where they end.
- **[CNCF Sandbox readiness](docs/cncf-sandbox-readiness.md)** - a self-check against CNCF Sandbox expectations, used as a quality bar.
- **[Code of Conduct](CODE_OF_CONDUCT.md)** - the CNCF Community Code of Conduct; report privately via [LinkedIn](https://www.linkedin.com/in/sandeepbazar/).

Every change is signed off under the [DCO](CONTRIBUTING.md), and any change that touches
a guardrail requires a written safety rationale.

## License

[Apache-2.0](LICENSE)
