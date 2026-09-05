# Tools and Prompts

**37 tools across ten toolsets, plus ten prompts.** Almost all of it is read: the
whole Open Cluster Management API is safe to inspect. Only two toolsets can change
anything, and only through the propose -> approve -> apply gate.

![Reads answer immediately and freely; writes go through propose, a human approval, and a one-time-token apply](https://raw.githubusercontent.com/ocm-mcp-server/ocm-mcp-server/main/docs/assets/art/paths-dark.svg)

Every hub-level tool works for any managed spoke - a standalone OpenShift cluster, a
HyperShift hosted cluster, or a cloud cluster - because on the hub they are all
`ManagedCluster`s. Run `ocm-mcp doctor` to call every read tool against your hub and
print a `PASS / EMPTY / SKIP / FAIL` table before wiring up an agent.

## Toolsets at a glance

| Toolset | What it covers | Tools | Writes |
|---|---|---|---|
| **inventory** | ManagedClusters, ClusterSets, set bindings, ClusterClaims, ManagedClusterInfo | 6 | - |
| **observability** | cluster health, one-call fleet sweep, events, pod logs | 4 | - |
| **placement** | Placements, PlacementDecisions, AddOnPlacementScores | 3 | - |
| **work** | ManifestWork status feedback + the gated deploy flow | 7 | gated |
| **addons** | ClusterManagementAddOns, fleet + per-cluster add-on health | 3 | - |
| **registration** | pending join CSRs + gated cluster lifecycle actions | 3 | gated |
| **policy** | governance compliance + violations rollup (if installed) | 2 | - |
| **hosted-control-planes** | HyperShift HostedClusters and NodePools (when the hub hosts them) | 3 | - |
| **resources** | generic get/list over an allow-list of OCM API types | 2 | - |
| **audit** | pending proposals, this server's own audit trail | 2 | - |

![The whole tool surface across ten toolsets, with only work and registration able to change anything](https://raw.githubusercontent.com/ocm-mcp-server/ocm-mcp-server/main/docs/assets/art/toolsets-dark.svg)

## Tool classes

- **read** - safe, non-mutating, no gate. Annotated `readOnlyHint`.
- **propose** - stores a pending change; mutates nothing on any cluster. Runs static
  guardrails and a hub dry-run first.
- **apply** - delivers an already-approved change. Needs an Ed25519 token
  bound to the exact content. Annotated `destructiveHint`.

`OCM_MCP_READ_ONLY=1` makes every propose and apply tool refuse - a strictly-inspection
deployment, backstopping the token gate.

## The reads

- **inventory:** `list_clusters`, `get_cluster`, `list_cluster_sets`,
  `list_cluster_set_bindings`, `list_cluster_claims`, `get_cluster_info` (OpenShift
  version, nodes, console URL - from the hub, no spoke access needed).
- **observability:** `get_cluster_health`, `get_fleet_health` (the whole fleet in one
  call - hub conditions plus concurrent spoke scans, `OCM_MCP_FANOUT_WORKERS`),
  `query_events`, `get_pod_logs`.
- **placement:** `list_placements`, `get_placement_decision`,
  `list_addon_placement_scores`.
- **work:** `list_manifestworks`, `get_manifestwork` (per-resource status feedback,
  the "why not Applied"), `list_manifestworkreplicasets`, `list_applied_manifestworks`
  (read from the spoke itself — what it actually materialised, rather than what the hub
  believes), `list_cluster_permissions` (the RBAC distributed to that cluster, which is
  where to look when layer 4 refuses an apply).
- **addons:** `list_cluster_management_addons`, `get_addon_health`,
  `list_addons_for_cluster`.
- **registration:** `list_pending_csrs`.
- **policy:** `list_policies`, `list_policy_violations` (reports clearly if the add-on
  is not installed).
- **hosted-control-planes:** `list_hosted_clusters`, `get_hosted_cluster`,
  `list_node_pools` (HostedCluster objects live on the hosting cluster; if HCPs are
  hosted elsewhere the tools say so and the ManagedCluster view still covers them).
- **resources:** `list_resources`, `get_resource`.
- **audit:** `list_pending_proposals`, `get_audit_trail`.

## The gated writes

The `work` toolset proposes a workload change:

- `propose_manifestwork(cluster, name, summary, manifests_json)` -> validate + store.
- `apply_manifestwork(proposal_id, approval_token)` -> create the ManifestWork.
- `propose_rollback(proposal_id)` -> create a rollback proposal bound to the applied work's UID.
- `rollback_manifestwork(rollback_proposal_id, approval_token)` -> delete it (rollback-scoped token).

The `registration` toolset proposes an OCM lifecycle action:

- `propose_cluster_action(cluster, action, summary, params_json)` -> validate + store.
- `apply_cluster_action(proposal_id, approval_token)` -> apply it.

`action` is one of:

- **`cordon`** - add a `NoSelect` taint so Placements stop scheduling to the cluster.
- **`uncordon`** - remove that taint.
- **`set_label`** - set or remove a label (`params_json`: `{"key": "...", "value": "..."}`; empty value removes it).
- **`accept`** - set `hubAcceptsClient=true` and approve the cluster's pending join CSRs (the double opt-in that finishes onboarding).
- **`enable_addon`** - create a `ManagedClusterAddOn` in the cluster namespace (`params_json`: `{"addon": "...", "install_namespace": "..."}`).
- **`disable_addon`** - delete a `ManagedClusterAddOn` (`params_json`: `{"addon": "..."}`).

## The generic reader is an allow-list

`list_resources` and `get_resource` read any Open Cluster Management type through one
interface - but only types on a fixed allow-list. This is deliberately an allow-list,
not a deny-list: `Secret`, `ConfigMap`, and every core kind are absent, so the
dangerous read cannot be named. The safety guarantee does not depend on an operator
remembering to block anything.

```
managedclusters              managedclustersets           managedclustersetbindings
placements                   placementdecisions           addonplacementscores
manifestworks                manifestworkreplicasets       clustermanagementaddons
managedclusteraddons         addondeploymentconfigs        addontemplates
clustermanagers              klusterlets                   policies
policysets                   placementbindings             managedclusterinfos
hostedclusters               nodepools
```

## Prompts

MCP prompts are reusable templates a client offers as a starting point. Each drives
the agent through the safe workflow with the real tool names.

| Prompt | Arguments | What it drives |
|---|---|---|
| **`diagnose_fleet`** | - | sweep every cluster and add-on, summarize what is unhealthy and why. Reads only. |
| **`remediate_with_approval`** | `symptom` | investigate, propose the smallest safe fix, wait for the human token, apply, verify, report. |
| **`incident_postmortem`** | - | write the post-incident report strictly from `get_audit_trail`. |
| **`why_not_scheduled`** | `cluster`, `placement`, `namespace` | explain a Placement decision from the live objects. |
| **`onboard_cluster`** | `cluster` | accept a pending cluster safely through the approval gate. |
| **`addon_troubleshoot`** | `addon` | diagnose a degraded add-on across the fleet. |
| **`hosted_cluster_health`** | `cluster` | assess a HyperShift hosted control plane and its node pools. |
| **`policy_compliance_report`** | - | summarize governance compliance and prioritize what to fix. |
| **`capacity_report`** | - | find clusters with headroom and clusters under pressure. |
| **`rollout_status`** | `name`, `namespace` | track a ManifestWorkReplicaSet rollout across selected clusters. |

The full argument-by-argument reference lives in
[docs/tools.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/docs/tools.md).

Next: [Guardrails Deep Dive](Guardrails-Deep-Dive).
