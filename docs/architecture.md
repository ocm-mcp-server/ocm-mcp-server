# Architecture

## The choke-point idea

Fleet operations already flow through a hub: Open Cluster Management gives us
cluster inventory (`ManagedCluster`), scheduling (`Placement`), and delivery
(`ManifestWork`). Instead of handing an agent N kubeconfigs, we hand it a
narrow, typed view of that hub - one place to observe, one place to constrain.

```
agent (any MCP client)
   │  typed MCP tools
   ▼
ocm-mcp-server ──── audit.jsonl (every call)
   │                 └─ OTel spans → Jaeger
   │ static guardrails (layer 1)
   ▼
OCM hub API
   │ Kyverno admission, incl. dry-run   (layer 2)
   │ human approval token               (layer 3)
   │ least-privilege RBAC               (layer 4)
   ▼
ManifestWork → work agent on each managed cluster
```

## Components

| Component | Role |
|---|---|
| `server.py` | FastMCP server; the only surface the agent sees |
| `ocm.py` | ManagedCluster / ManifestWork operations, summarized for agents |
| `guardrails.py` | layer-1 static checks (kinds allowlist, namespaces, pod security, image pinning) |
| `approvals.py` | proposal store + Ed25519 approval tokens binding the content hash, operation, and TTL (server holds only the public key) |
| `tracing.py` | OTel span + audit line per tool call |
| `cli.py` | `ocm-mcp` - the human approval terminal |
| `deploy/policies/` | Kyverno ClusterPolicies validating **inside** the ManifestWork envelope |
| `deploy/rbac.yaml` | hub ServiceAccount: ManagedClusters read, ManifestWorks manage, nothing else |

## Design decisions worth arguing about

**Why validate ManifestWorks, not Pods?** Policies on the managed clusters see
resources only after delivery. Validating the *envelope* on the hub rejects bad
content before it ever leaves - at proposal time, via server-side dry-run, so
the agent gets the policy message as feedback and can self-correct.

**Why an Ed25519-signed token instead of a "yes" in chat?** A chat approval
approves a *conversation*. The token approves a *content hash* and an operation:
if the agent mutates the proposal after approval, the signature no longer
verifies, and an `apply` token cannot authorize a `rollback`. Approval is
asymmetric - the CLI signs with a private key the server never holds, so a
compromised server cannot mint one - provided the private signing key is kept off the
server (`OCM_MCP_SIGNER_KEY` on a separate account/device); co-located, that is a
filesystem convention, not a boundary. Tokens are single-use and expire (default 1 h), minted
only by the CLI on a trusted terminal.

**Why per-spoke read ServiceAccounts in the quickstart?** Simplicity. The
production-correct path is the OCM cluster-proxy add-on (hub-mediated access,
no direct spoke credentials on the server host); the tool surface is identical,
so swapping the transport does not change the agent's world.

**Why no Secrets/exec tools at all?** Any tool that exists will eventually be
called. Capabilities that are absent cannot be prompt-injected into use.

## Scaling the pattern

- More clusters: nothing changes - the hub is the fan-out point.
- More agents: one server per agent identity, each with its own RBAC and audit.
- Other hubs: the guardrail pattern (static → policy dry-run → human token →
  RBAC) ports to any declarative delivery API, not just OCM.
