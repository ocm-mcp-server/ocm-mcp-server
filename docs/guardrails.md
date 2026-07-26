# Guardrails: what, why, and what we refuse to automate

## The four layers

1. **Static checks** (`guardrails.py`) - fast, local, no cluster needed. Inputs are
   schema-checked first (a malformed manifest is a clean rejection, not a crash),
   then a Restricted-Pod-Security baseline is enforced on every embedded workload and
   its init/ephemeral containers: full `apiVersion/kind` allow-list (a spoofed group
   like `evil.example/v1, Deployment` is rejected), no host namespaces,
   `automountServiceAccountToken: false`, no arbitrary service account, an allow-list
   of volume types (no PVC/CSI/hostPath/secret) and Service types (no
   NodePort/LoadBalancer/externalIPs), required `runAsNonRoot`,
   `allowPrivilegeEscalation: false`, all capabilities dropped, a seccomp profile, no
   indirect Secret access (`env.secretKeyRef`, secret/projected-token volumes), and
   pinned images (optionally `@sha256` digests via `OCM_MCP_REQUIRE_DIGEST`). These
   run first for instant feedback, and again at apply time.
2. **Kyverno dry-run on the hub** (`deploy/policies/`) - organizational policy,
   evaluated inside the ManifestWork envelope via server-side dry-run at
   proposal time. Your existing policy library applies here too.
3. **Human approval** (`approvals.py`) - an **Ed25519** token whose claims bind the
   proposal's content hash, the operation (`apply` or `rollback`), the issuer and
   audience, a unique id, and an expiry, signed by `ocm-mcp approve` on a trusted
   terminal. Approval is **asymmetric** and the token is **one-time** (its id is
   recorded as spent on use, so it cannot be replayed). The server needs only the
   public verifier key. **Isolation caveat:** the "a compromised server cannot mint"
   property holds only when the private signing key is kept off the server - a
   separate OS account or device via `OCM_MCP_SIGNER_KEY`. Co-located under one
   `OCM_MCP_HOME`, signer isolation is a filesystem convention, not an enforced
   boundary; treat off-box signing (or a chat-ops/ticket signer) as required for
   that guarantee. An apply token cannot authorize a rollback; rollback needs its
   own proposal and token.
4. **RBAC** (`deploy/rbac.yaml`) - the server's own identity can read the OCM API
   and create/delete ManifestWorks and manage add-ons. RBAC cannot scope this to
   "only objects it created", so ownership of a specific ManifestWork is enforced in
   the application (the `managed-by` label plus the approved UID checked before
   rollback), not by RBAC. RBAC grants no Secret read, no exec, and no arbitrary
   delete, so even a bug in this server cannot read a Secret.

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
| approval replay of an unchanged token | single-use token id, recorded as spent |
| token minted for another deployment | issuer + audience binding |
| unlabeled ManifestWork skipping policy | Kyverno policy matched on the server SA identity |
| stolen approval token | TTL + single-proposal binding + one-time use |
| crafted/late CSR on the accept path | signer + group + usage + cluster-bound username, re-checked at apply |
| compromised server host | RBAC scope; no Secrets/exec; off-box signer cannot be read to mint |
| audit tampering by the agent | append-only hash chain (`audit-verify`) outside the tool surface |
