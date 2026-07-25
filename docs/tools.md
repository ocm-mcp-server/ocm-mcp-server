<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tools and Prompts reference

The server exposes **27 tools across nine toolsets** plus **four prompts**. This page
is the canonical reference: every tool, its class, its arguments, and the Open
Cluster Management API it reads or writes. The short version lives in the
[README](../README.md#toolsets); the safety model behind the classes is in
[guardrails.md](guardrails.md).

## Tool classes

| Class | Meaning | Enforcement |
|---|---|---|
| **read** | Safe, non-mutating. No gate. Annotated `readOnlyHint`. | none needed |
| **propose** | Stores a pending change. Mutates nothing on any cluster. | static guardrails + Kyverno dry-run at propose time |
| **apply** | Delivers an already-approved change. Annotated `destructiveHint`. | human-minted HMAC token bound to the exact content + least-privilege RBAC |

`OCM_MCP_READ_ONLY=1` makes every **propose** and **apply** tool refuse before doing
anything - a coarse backstop layered under the token gate, for inspection-only
deployments.

Everything below `get`/`list` is a plain read against the hub (or, for
events/logs, a read-only spoke context). Nothing here can read a Secret, exec into
a pod, or delete an arbitrary resource: those tools are not implemented, so no
prompt can call them.

## inventory

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_clusters` | read | - | `ManagedCluster` (cluster.open-cluster-management.io/v1) |
| `get_cluster` | read | `cluster` | `ManagedCluster` (acceptance, taints, version, capacity, claims) |
| `list_cluster_sets` | read | - | `ManagedClusterSet` v1beta2 + membership |
| `list_cluster_set_bindings` | read | `namespace?` | `ManagedClusterSetBinding` v1beta2 |
| `list_cluster_claims` | read | - | `ManagedCluster.status.clusterClaims` |

## observability

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `get_cluster_health` | read | `cluster` | hub conditions + spoke pods/deployments (needs a spoke context) |
| `query_events` | read | `cluster`, `namespace?`, `limit?` | spoke `Event`s, newest first |
| `get_pod_logs` | read | `cluster`, `namespace`, `pod`, `container?`, `lines?` | spoke pod logs (falls back to previous instance) |

## placement

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_placements` | read | `namespace?` | `Placement` v1beta1 + selected count |
| `get_placement_decision` | read | `placement`, `namespace` | `PlacementDecision` v1beta1 (the chosen clusters) |
| `list_addon_placement_scores` | read | `cluster` | `AddOnPlacementScore` v1alpha1 |

## work

| Tool | Class | Arguments | Reads / writes |
|---|---|---|---|
| `list_manifestworks` | read | `cluster` | `ManifestWork` v1 (Applied/Available) |
| `get_manifestwork` | read | `cluster`, `name` | `ManifestWork` conditions + per-resource `statusFeedback` |
| `list_manifestworkreplicasets` | read | `namespace?` | `ManifestWorkReplicaSet` v1alpha1 rollout summary |
| `propose_manifestwork` | propose | `cluster`, `name`, `summary`, `manifests_json` | validates, stores pending |
| `apply_manifestwork` | apply | `proposal_id`, `approval_token` | creates the `ManifestWork` |
| `rollback_manifestwork` | apply | `proposal_id`, `approval_token` | deletes the applied `ManifestWork` |

## addons

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_cluster_management_addons` | read | - | `ClusterManagementAddOn` v1alpha1 + install strategy |
| `get_addon_health` | read | - | `ManagedClusterAddOn` v1alpha1 Available/Degraded per cluster |

## registration

| Tool | Class | Arguments | Reads / writes |
|---|---|---|---|
| `list_pending_csrs` | read | - | pending OCM `CertificateSigningRequest`s |
| `propose_cluster_action` | propose | `cluster`, `action`, `summary`, `params_json?` | dry-runs, stores pending |
| `apply_cluster_action` | apply | `proposal_id`, `approval_token` | applies the action |

`action` is one of:

- `cordon` - add a `NoSelect` taint so Placements stop scheduling to the cluster.
- `uncordon` - remove that taint.
- `set_label` - set or remove a label (`params_json`: `{"key": "...", "value": "..."}`; empty value removes it).
- `accept` - set `spec.hubAcceptsClient=true` and approve the cluster's pending join CSRs (the double opt-in that completes onboarding).

## policy (optional add-on)

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_policies` | read | `namespace?` | `Policy` v1 + per-cluster compliance |

If the governance policy add-on is not installed on the hub, this returns a clear
`UNAVAILABLE` message rather than an error.

## resources (generic, allow-listed)

| Tool | Class | Arguments |
|---|---|---|
| `list_resources` | read | `resource`, `namespace?` |
| `get_resource` | read | `resource`, `name`, `namespace?` |

`resource` must be one of the allow-listed OCM types. This is an allow-list, not a
deny-list: any type not on it - including `Secret`, `ConfigMap`, and every core
kind - simply cannot be named, so the dangerous read does not exist.

```
managedclusters              managedclustersets           managedclustersetbindings
placements                   placementdecisions           addonplacementscores
manifestworks                manifestworkreplicasets       clustermanagementaddons
managedclusteraddons         addondeploymentconfigs        addontemplates
clustermanagers              klusterlets                   policies
policysets                   placementbindings
```

## audit

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_pending_proposals` | read | - | pending proposals (ManifestWorks and actions) |
| `get_audit_trail` | read | `last_n?` | this server's append-only `audit.jsonl` |

## Prompts

MCP prompts are reusable templates a client can offer as a starting point. Each one
drives the agent through the safe workflow with the real tool names.

| Prompt | Arguments | What it drives |
|---|---|---|
| `diagnose_fleet` | - | sweep every cluster and add-on, summarize what is unhealthy and why. Reads only. |
| `remediate_with_approval` | `symptom` | investigate, propose the smallest safe fix, wait for the human token, apply, verify, report. |
| `incident_postmortem` | - | write the post-incident report strictly from `get_audit_trail`. |
| `why_not_scheduled` | `cluster`, `placement`, `namespace` | explain a Placement decision from the live objects. |
