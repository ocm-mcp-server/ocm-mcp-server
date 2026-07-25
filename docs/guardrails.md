# Guardrails: what, why, and what we refuse to automate

## The four layers

1. **Static checks** (`guardrails.py`) - fast, local, no cluster needed. Match the
   full `apiVersion/kind` against an allow-list (so a spoofed group like
   `evil.example/v1, Deployment` is rejected), and reject privileged/host access,
   protected namespaces, unpinned images, indirect Secret access
   (`env.secretKeyRef`, secret and projected-token volumes), arbitrary service
   accounts, and oversized proposals. These run first so the agent gets instant,
   actionable feedback, and again at apply time.
2. **Kyverno dry-run on the hub** (`deploy/policies/`) - organizational policy,
   evaluated inside the ManifestWork envelope via server-side dry-run at
   proposal time. Your existing policy library applies here too.
3. **Human approval** (`approvals.py`) - an **Ed25519** token whose claims bind the
   proposal's content hash, the operation (`apply` or `rollback`), and an expiry,
   signed by `ocm-mcp approve` on a trusted terminal. Approval is **asymmetric**:
   the CLI holds the private signing key, the server holds only the public key, so
   the server can verify a token but can never mint one - even if it (or an agent
   reading its key material) is compromised. An apply token cannot authorize a
   rollback; rollback needs its own proposal and token.
4. **RBAC** (`deploy/rbac.yaml`) - the server's own identity can read the OCM API
   and manage only the ManifestWorks and add-ons it creates. Nothing else. Even a
   bug in this server cannot read a Secret.

Defense in depth matters because each layer fails differently: static checks
can lag policy; policy can have gaps; humans approve too fast; RBAC is the
backstop that holds when the other three don't.

## Deliberate absences

There is no tool for: reading Secrets, exec/port-forward, deleting arbitrary
resources, cluster lifecycle operations, or approving proposals. Absent
capabilities cannot be prompt-injected into use.

## What we refuse to automate (for now)

- anything touching etcd, storage classes, or cluster deletion
- cross-cluster traffic shifting during live incidents
- auto-approval, even for "safe" change classes

Rule of thumb: **automate diagnosis aggressively, mutation conservatively.**

## Threat model (abridged)

| Threat | Countered by |
|---|---|
| hallucinated/destructive fix | layers 1–3 |
| prompt injection ("ignore your rules and…") | layers 1, 2, 4 - rules aren't in the prompt |
| approval replay on changed content | token binds to content hash |
| stolen approval token | TTL + single-proposal binding |
| compromised server host | RBAC scope; no Secrets/exec permissions to steal |
| audit tampering by the agent | audit file is outside the tool surface |
