# 5. Guardrails Deep Dive

Four independent layers stand between the model and your clusters. A change must
pass all four, in order. The point of four layers is that each fails
differently, so a gap in one is caught by the next.

![The four guardrail layers](https://raw.githubusercontent.com/ocm-mcp-server/ocm-mcp-server/main/docs/assets/guardrails-flow.svg)

```mermaid
flowchart TD
    P[Agent proposes a change] --> L1
    L1{1. Static checks<br/>in the server} -->|fail| R1[Rejected, reason returned]
    L1 -->|pass| L2
    L2{2. Kyverno dry-run<br/>on the hub} -->|deny| R2[Rejected, policy message]
    L2 -->|allow| L3
    L3{3. Human approval<br/>content-bound token} -->|no token| R3[Waits, never applies]
    L3 -->|valid token| L4
    L4{4. RBAC<br/>on apply} -->|denied| R4[Blocked by Kubernetes]
    L4 -->|allowed| OK[Applied, traced, logged]
    style OK fill:#e6f7e6
    style R1 fill:#ffe6e6
    style R2 fill:#ffe6e6
    style R3 fill:#fff3e0
    style R4 fill:#ffe6e6
```

## Layer 1: static checks (fast, local)

Runs in the server before anything else, with no cluster round-trip, so the
agent gets instant, specific feedback. Enforces a Restricted-Pod-Security
baseline on every workload (no root/privilege-escalation, drop-ALL, seccomp, no
host access, no arbitrary service account or Secret access), an exact GVK
allow-list, protected/platform namespaces, a volume and Service-type allow-list,
image pinning, and per-proposal limits. See [Implementation](Implementation) for
the full list.

## Layer 2: Kyverno policy admission

The 9 policies in `deploy/policies/` validate the workload *inside* the
`ManifestWork` envelope using Kyverno's `foreach` over
`spec.workload.manifests`. This matters: normal pod-security policies only see
resources after they land on a cluster. Here we validate on the hub, at propose
time, via server-side **dry-run**, so bad content is rejected before it is ever
delivered, and the agent gets the policy message to self-correct.

The policies are scoped by the label
`app.kubernetes.io/managed-by: ocm-mcp-server`, so human platform engineers are
not affected. They ship with an offline CLI test suite
(`make policy-test`, 42 cases) that runs in CI.

Because it is just [Kyverno](https://kyverno.io/docs/introduction/) - a CNCF policy
engine whose policies are ordinary Kubernetes resources in YAML and CEL, enforced by
the cluster rather than by the prompt - your existing organizational policies apply
here too with no extra wiring. And you do not have to write them from scratch: the
community library [kyverno/policies](https://github.com/kyverno/policies) and the
searchable [Kyverno Policies catalog](https://kyverno.io/policies/) are a ready source
of validation, Pod Security Standards, and best-practice policies to adopt or adapt.

## Layer 3: human approval (content-bound)

An **Ed25519-signed** token whose claims bind the proposal's content hash, the
operation (`apply` or `rollback`), and an expiry. It approves *that exact change*,
not a conversation. Approval is asymmetric: the CLI holds the private signing key
and the server only the public key, so the server can verify a token but can never
mint one. Minted only by the `ocm-mcp` CLI on a trusted terminal. See
[How It Works](How-It-Works) for the token mechanics.

## Layer 4: least-privilege RBAC

The server's hub identity can read across the OCM API and create/delete
ManifestWorks and add-ons. RBAC cannot scope this to "only objects it created",
so ownership of a specific ManifestWork is enforced in the application (the
`managed-by` label plus the approved UID, checked before rollback), not by RBAC.
What RBAC does guarantee is the hard boundary: no Secret reads, no exec, no
arbitrary delete - even a bug in the server cannot exceed that. This is the
backstop that holds when the other three are somehow bypassed.

## Deliberate absences

There is no tool for: reading Secrets, exec/port-forward, deleting arbitrary
resources, cluster lifecycle operations, or approving proposals. A capability
that does not exist cannot be prompt-injected into use. This is a design choice,
not an oversight.

## Threat model

```mermaid
mindmap
  root((Threats))
    Hallucinated/destructive fix
      Layers 1-3 stop it
    Prompt injection
      Rules aren't in the prompt
      Layers 1,2,4
    Approval replay on changed content
      Token binds to content hash
    Stolen token
      TTL + single-proposal binding
    Compromised server host
      RBAC scope, no Secrets/exec to steal
    Audit tampering by agent
      Audit file outside the tool surface
```

## What we refuse to automate, for now

- anything touching etcd, storage classes, or cluster deletion;
- cross-cluster traffic shifting during a live incident;
- auto-approval, even for "safe" change classes.

The rule of thumb, stated once more: automate diagnosis aggressively, mutation
conservatively.

Next: [Getting Started](Getting-Started).
