# Tools and Prompts

**27 tools across nine toolsets, plus four prompts.** Almost all of it is read: the
whole Open Cluster Management API is safe to inspect. Only two toolsets can change
anything, and only through the propose -> approve -> apply gate.

![Reads are free; writes are gated](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/docs/assets/read-write-paths.svg)

## Toolsets at a glance

| Toolset | What it covers | Tools | Writes |
|---|---|---|---|
| **inventory** | ManagedClusters, ClusterSets, set bindings, ClusterClaims | 5 | - |
| **observability** | cluster health, events, pod logs | 3 | - |
| **placement** | Placements, PlacementDecisions, AddOnPlacementScores | 3 | - |
| **work** | ManifestWork status feedback + the gated deploy flow | 6 | gated |
| **addons** | ClusterManagementAddOns, per-cluster add-on health | 2 | - |
| **registration** | pending join CSRs + gated cluster lifecycle actions | 3 | gated |
| **policy** | governance policy compliance (if the add-on is installed) | 1 | - |
| **resources** | generic get/list over an allow-list of OCM API types | 2 | - |
| **audit** | pending proposals, this server's own audit trail | 2 | - |

## Tool classes

- **read** - safe, non-mutating, no gate. Annotated `readOnlyHint`.
- **propose** - stores a pending change; mutates nothing on any cluster. Runs static
  guardrails and a hub dry-run first.
- **apply** - delivers an already-approved change. Needs a human-minted HMAC token
  bound to the exact content. Annotated `destructiveHint`.

`OCM_MCP_READ_ONLY=1` makes every propose and apply tool refuse - a strictly-inspection
deployment, backstopping the token gate.

## The reads

- **inventory:** `list_clusters`, `get_cluster`, `list_cluster_sets`,
  `list_cluster_set_bindings`, `list_cluster_claims`.
- **observability:** `get_cluster_health`, `query_events`, `get_pod_logs`.
- **placement:** `list_placements`, `get_placement_decision`,
  `list_addon_placement_scores`.
- **work:** `list_manifestworks`, `get_manifestwork` (per-resource status feedback,
  the "why not Applied"), `list_manifestworkreplicasets`.
- **addons:** `list_cluster_management_addons`, `get_addon_health`.
- **registration:** `list_pending_csrs`.
- **policy:** `list_policies` (reports clearly if the add-on is not installed).
- **resources:** `list_resources`, `get_resource`.
- **audit:** `list_pending_proposals`, `get_audit_trail`.

## The gated writes

The `work` toolset proposes a workload change:

- `propose_manifestwork(cluster, name, summary, manifests_json)` -> validate + store.
- `apply_manifestwork(proposal_id, approval_token)` -> create the ManifestWork.
- `rollback_manifestwork(proposal_id, approval_token)` -> delete it (fresh token).

The `registration` toolset proposes an OCM lifecycle action:

- `propose_cluster_action(cluster, action, summary, params_json)` -> validate + store.
- `apply_cluster_action(proposal_id, approval_token)` -> apply it.

`action` is one of:

- **`cordon`** - add a `NoSelect` taint so Placements stop scheduling to the cluster.
- **`uncordon`** - remove that taint.
- **`set_label`** - set or remove a label (`params_json`: `{"key": "...", "value": "..."}`; empty value removes it).
- **`accept`** - set `hubAcceptsClient=true` and approve the cluster's pending join CSRs (the double opt-in that finishes onboarding).

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
policysets                   placementbindings
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

The full argument-by-argument reference lives in
[docs/tools.md](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/docs/tools.md).

Next: [Guardrails Deep Dive](Guardrails-Deep-Dive).
