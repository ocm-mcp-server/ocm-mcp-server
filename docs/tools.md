<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tools and Prompts reference

The server exposes **37 tools across ten toolsets** plus **ten prompts**. This page is
the canonical reference: every tool, its class, its arguments, and the Open Cluster
Management API it reads or writes. The short version lives in the
[README](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/README.md#toolsets); the safety model behind the classes is in
[guardrails.md](guardrails.md).

## Works with any managed cluster

Every hub-level tool operates on the OCM APIs on the hub, where each spoke - a
standalone OpenShift cluster, a HyperShift hosted cluster (hosted on the hub or on a
separate management cluster), or a cloud cluster - is a `ManagedCluster`. So inventory,
placement, work, add-on, registration, policy, and `get_cluster_info` are all
topology-agnostic. Two things depend on topology:

- **`list_hosted_clusters` / `get_hosted_cluster` / `list_node_pools`** read
  `HostedCluster` objects, which live on whichever cluster hosts the control plane.
  When the hub is the HyperShift hosting cluster they are on the hub; when HCPs are
  hosted elsewhere, these tools report that and the `ManagedCluster` view still covers
  those spokes.
- **`get_cluster_health`, `get_fleet_health`, `query_events`, `get_pod_logs`** read the
  spoke directly and need a per-cluster context (a kubeconfig, or cluster-proxy +
  managed-serviceaccount). `get_fleet_health` fans the same per-cluster scan out
  concurrently across every cluster (`OCM_MCP_FANOUT_WORKERS`, default 8); a cluster
  without configured spoke context shows `spoke_view: "unavailable (no read context configured)"`
  with no error entry; broken spokes show as an `error` entry instead of failing the
  sweep. `get_cluster_info` gives version, nodes, and console URL from the hub with no
  spoke access at all.

## Validate against a live hub

`ocm-mcp doctor` calls every read tool against the hub and prints a
`PASS / EMPTY / SKIP / FAIL` table, writing nothing. `SKIP` means a spoke context or an
optional CRD is absent; `FAIL` means the hub returned an error (check RBAC and the
CRD). Non-zero exit on any `FAIL`, so it works as a health gate too.

![The whole tool surface across ten toolsets, with only work and registration able to change anything](https://raw.githubusercontent.com/ocm-mcp-server/ocm-mcp-server/main/docs/assets/art/toolsets-dark.svg)

## Tool classes

| Class | Meaning | Enforcement |
|---|---|---|
| **read** | Safe, non-mutating. No gate. Annotated `readOnlyHint`. | none needed |
| **propose** | Stores a pending change. Mutates nothing on any cluster. | static guardrails + Kyverno dry-run at propose time |
| **apply** | Delivers an already-approved change. Annotated `destructiveHint`. | Ed25519 token (signed by the CLI, verified by the server's public key) bound to the exact content + operation, plus least-privilege RBAC |

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
| `get_cluster_info` | read | `cluster` | `ManagedClusterInfo` v1beta1 (internal.) - OpenShift version, nodes, console URL; hub-side |

## observability

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `get_cluster_health` | read | `cluster` | hub conditions + spoke pods/deployments (needs a spoke context) |
| `get_fleet_health` | read | `clusters?` | whole-fleet hub conditions + concurrent spoke pods/deployments (`OCM_MCP_FANOUT_WORKERS`); broken spokes are an `error` entry, not a failed call |
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
| `list_applied_manifestworks` | read | `cluster` | `AppliedManifestWork` v1 read from the **spoke**: what the agent actually materialised there |
| `list_cluster_permissions` | read | `cluster` | `ClusterPermission` v1alpha1 (`rbac.open-cluster-management.io`) — the RBAC distributed to that cluster |
| `propose_manifestwork` | propose | `cluster`, `name`, `summary`, `manifests_json` | validates, stores pending |
| `apply_manifestwork` | apply | `proposal_id`, `approval_token` | verifies an apply-scoped token, creates the `ManifestWork` |
| `propose_rollback` | propose | `proposal_id` | creates a rollback proposal bound to the applied work's UID |
| `rollback_manifestwork` | apply | `rollback_proposal_id`, `approval_token` | verifies a rollback-scoped token + ownership, deletes the `ManifestWork` |

## addons

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_cluster_management_addons` | read | - | `ClusterManagementAddOn` v1alpha1 + install strategy |
| `get_addon_health` | read | - | `ManagedClusterAddOn` v1alpha1 Available/Degraded per cluster |
| `list_addons_for_cluster` | read | `cluster` | `ManagedClusterAddOn` in one cluster namespace + health |

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
- `enable_addon` - create a `ManagedClusterAddOn` in the cluster namespace (`params_json`: `{"addon": "...", "install_namespace": "..."}`; namespace optional).
- `disable_addon` - delete a `ManagedClusterAddOn` (`params_json`: `{"addon": "..."}`).

## policy (optional add-on)

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_policies` | read | `namespace?` | `Policy` v1 + per-cluster compliance |
| `list_policy_violations` | read | - | `Policy` v1, filtered to NonCompliant / Pending pairs |

If the governance policy add-on is not installed on the hub, these return a clear
`UNAVAILABLE` message rather than an error. Note ACM's `compliant` field is not binary:
`Pending` also counts as a violation.

## hosted-control-planes (HyperShift)

| Tool | Class | Arguments | Reads |
|---|---|---|---|
| `list_hosted_clusters` | read | `namespace?` | `HostedCluster` (hypershift.openshift.io/v1beta1) + version/conditions |
| `get_hosted_cluster` | read | `name`, `namespace` | one `HostedCluster` in detail + its NodePools |
| `list_node_pools` | read | `namespace?`, `cluster?` | `NodePool` desired vs current replicas |

These read `HostedCluster` objects on the hub, so they work when the hub is the
HyperShift hosting cluster. If HCPs are hosted on a separate management cluster, they
return a clear `UNAVAILABLE` message; the spokes still appear via `list_clusters`.

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
policysets                   placementbindings             managedclusterinfos
hostedclusters               nodepools
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
| `onboard_cluster` | `cluster` | accept a pending cluster safely through the approval gate. |
| `addon_troubleshoot` | `addon` | diagnose a degraded add-on across the fleet. |
| `hosted_cluster_health` | `cluster` | assess a HyperShift hosted control plane and its node pools. |
| `policy_compliance_report` | - | summarize governance compliance and prioritize what to fix. |
| `capacity_report` | - | find clusters with headroom and clusters under pressure. |
| `rollout_status` | `name`, `namespace` | track a ManifestWorkReplicaSet rollout across selected clusters. |
