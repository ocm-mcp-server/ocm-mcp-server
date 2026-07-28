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
| `guardrails.py` | layer-1 static checks (exact GVK allow-list, namespaces, Restricted Pod Security, volume/service allow-lists, image pinning, per-proposal limits) |
| `approvals.py` | proposal store + one-time Ed25519 approval tokens binding the content hash, operation, issuer/audience, and TTL (server holds only the public key) |
| `tracing.py` | OTel span + hash-chained audit line per tool call |
| `metrics.py` | optional Prometheus `/metrics` endpoint |
| `filelock.py` | advisory file locks (atomic proposal writes, spent-token ledger, per-proposal apply lock) |
| `cli.py` | `ocm-mcp` - the human approval terminal (approve/reject/audit-verify/doctor/rotate-secret) |
| `deploy/policies/` | Kyverno ClusterPolicies validating **inside** the ManifestWork envelope |
| `deploy/rbac.yaml` | hub ServiceAccount: read across the OCM API (cluster/placement/addon/operator/policy/HyperShift/ManagedClusterInfo), create/delete ManifestWorks and add-ons, patch ManagedClusters, approve OCM join CSRs. No Secret reads, no exec, no arbitrary delete. Ownership of a work is enforced in-app, not by RBAC |

## Low-level design - the full internals, vertically

Everything below is the same system, cut four ways: the full component stack, the
anatomy of one read call, the complete gated write sequence, and the integrity
machinery (state, keys, audit). File references are to `src/ocm_mcp_server/`.

### 1. The full vertical stack

Every box is a real component; every arrow is a real call path or protocol.

```mermaid
flowchart TD
    subgraph CLIENT["AGENT SIDE - any MCP client (Claude Code, Codex, Gemini, ...)"]
        A["AI agent<br/>sees ONLY: 34 tools + 10 prompts + 6 resources<br/>never: kubeconfig, Secrets, exec, raw kubectl"]
    end

    A -- "MCP: JSON-RPC 2.0 over stdio<br/>(initialize / tools/list / tools/call /<br/>resources/read / prompts/get)" --> B

    subgraph SERVER["SERVER PROCESS - ocm-mcp-server (Python, single process)"]
        B["FastMCP dispatch (server.py)<br/>schema validation of tool arguments<br/>annotations: readOnlyHint / destructiveHint per tool"]
        B --> C["@traced_tool wrapper (tracing.py)<br/>1. optional OTel span (OTLP/HTTP exporter)<br/>2. classify outcome: ok / rejected / failed / error / unavailable<br/>3. append hash-chained audit line (seq, prev, hash)<br/>4. metrics.record(tool, outcome, duration_ms)"]
        C --> D{"toolset?"}
        D -- "reads (27 tools, 6 resources)" --> E["_read() wrapper (server.py)<br/>FeatureNotInstalled/LookupError -> 'UNAVAILABLE: ...'<br/>ApiException -> clear message, never a stack trace"]
        D -- "writes (7 tools)" --> F["gate chain (server.py + guardrails.py + approvals.py)<br/>read-only backstop -> size cap -> schema -> static guardrails<br/>-> Kyverno dry-run -> proposal store -> human token -> apply"]
        E --> G["ocm.py - typed OCM operations<br/>summarizes raw CRs to operator-relevant fields<br/>paged_list(): limit=500 + continue tokens, 5000-item ceiling"]
        F --> G
        G --> H["k8s.py - client factory<br/>per-context ApiClient cache (TTL 600 s,<br/>so rotated/exec-refreshed creds are picked up)<br/>hub: CustomObjectsApi + CertificatesV1Api<br/>spokes: CoreV1Api + AppsV1Api (bounded, timed reads)"]
    end

    subgraph STATE["LOCAL STATE - $OCM_MCP_HOME (0600/0700, flock + fsync)"]
        S1["proposals/&lt;uuid4-hex&gt;.json<br/>status: pending -> approved/rejected -> applied -> rolled_back<br/>(forward-only transitions)"]
        S2["audit.jsonl - hash chain<br/>+ audit_anchors.jsonl - Ed25519-signed heads"]
        S3["approval_ed25519.pub (+ .pub.prev during rotation)<br/>public VERIFIER key only - the server can never sign"]
        S4["used_tokens.jsonl - spent jti ledger<br/>O(1) append, compacted at 2000 lines"]
    end
    F -.-> S1
    C -.-> S2
    F -.-> S3
    F -.-> S4

    subgraph HUMAN["TRUSTED TERMINAL - ocm-mcp CLI (cli.py) - never reachable by the agent"]
        T1["ocm-mcp pending / show &lt;id&gt;<br/>human reviews the EXACT manifests"]
        T2["ocm-mcp approve &lt;id&gt;<br/>signs claims with the Ed25519 PRIVATE key<br/>(OCM_MCP_SIGNER_KEY - ideally off-box/KMS)"]
        T3["ocm-mcp audit-anchor / audit-verify<br/>signs + verifies the audit chain head"]
    end
    T1 -. reads .-> S1
    T2 -- "token handed to the agent out-of-band" --> A
    T3 -.-> S2

    H -- "HTTPS to hub kube-apiserver<br/>(kubeconfig context, OCM_MCP_HUB_CONTEXT)" --> I

    subgraph HUB["OCM HUB CLUSTER"]
        I["kube-apiserver"]
        I --> J["Kyverno admission webhooks<br/>9 ClusterPolicies match ManifestWork<br/>foreach over spec.workload.manifests<br/>label-scoped: app.kubernetes.io/managed-by=ocm-mcp-server<br/>+ requester-identity rule closing the unlabeled bypass<br/>dry-run create (dryRun=All) = layer-2 gate at PROPOSE time"]
        J --> K["RBAC (deploy/rbac.yaml)<br/>read OCM API groups; create/delete manifestworks;<br/>patch managedclusters; scoped CSR approval<br/>NO secrets, NO pods/exec, NO arbitrary delete"]
        K --> L["OCM control plane CRs<br/>ManagedCluster / Placement / PlacementDecision<br/>ManifestWork / ManifestWorkReplicaSet<br/>ManagedClusterAddOn / Policy / CSR"]
    end

    L -- "OCM registration + work agents<br/>(klusterlet on each spoke, pull model)" --> M

    subgraph SPOKES["MANAGED CLUSTERS (spokes)"]
        M["klusterlet work agent applies the<br/>embedded manifests; status feeds back<br/>into ManifestWork .status (Applied/Available)"]
        N["ocm-mcp-reader SA (read-only RBAC)<br/>used by get_cluster_health / query_events /<br/>get_pod_logs via OCM_MCP_SPOKE_CONTEXTS<br/>(production path: OCM cluster-proxy instead)"]
    end
    H -- "HTTPS, bounded reads<br/>(limit=500, timeout 5s/30s)" --> N
```

### 2. Anatomy of one read call - `list_clusters`

What actually happens, function by function, for the simplest tool:

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent (MCP client)
    participant FM as FastMCP (server.py)
    participant TR as traced_tool (tracing.py)
    participant OC as ocm.py
    participant K8 as k8s.py
    participant API as hub kube-apiserver

    AG->>FM: JSON-RPC tools/call {name:"list_clusters"}
    FM->>FM: validate arguments against generated schema
    FM->>TR: list_clusters()
    TR->>TR: start OTel span "tool.list_clusters" (if OTLP endpoint set)
    TR->>OC: _read(ocm.list_managed_clusters)
    OC->>OC: paged_list(list_fn) - page loop
    OC->>K8: hub_custom() -> cached ApiClient for OCM_MCP_HUB_CONTEXT<br/>(rebuilt if older than OCM_MCP_CLIENT_TTL=600s)
    K8->>API: GET /apis/cluster.open-cluster-management.io/v1/managedclusters?limit=500
    API-->>K8: page 1 (+ metadata.continue if more)
    K8->>API: ...follow continue tokens until done or 5000 items (then explicit "truncated")
    API-->>OC: raw ManagedCluster list
    OC->>OC: summarize: name, labels, Available/Joined conditions,<br/>kubernetes version, cpu/memory capacity (nothing else)
    OC-->>TR: list[dict]
    TR->>TR: classify_outcome -> "ok"
    TR->>TR: audit append under flock: {tool,args,outcome,duration_ms,<br/>actor,ts,seq=N,prev=hash(N-1),hash=sha256(prev+canonical)} + fsync
    TR->>TR: metrics.record("list_clusters","ok",ms)
    TR-->>FM: JSON string
    FM-->>AG: JSON-RPC result (content: text)
```

Spoke-touching reads (`get_cluster_health`, `query_events`, `get_pod_logs`) differ
in one step: `k8s.spoke_core(cluster)` resolves the per-cluster read context and
every list is bounded (`limit=OCM_MCP_HEALTH_LIMIT`, request timeout `(5, 30)`s),
with an explicit note when the cluster has more than the limit.

### 3. The gated write path - every check, in order

Nothing in this sequence is advisory; each numbered gate refuses on its own.

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant SV as server.py (write tools)
    participant GR as guardrails.py
    participant AP as approvals.py
    participant ST as $OCM_MCP_HOME
    participant HU as Human (ocm-mcp CLI)
    participant API as hub apiserver (+ Kyverno)

    Note over AG,API: PROPOSE - nothing is applied
    AG->>SV: propose_manifestwork(cluster, name, summary, manifests_json)
    SV->>SV: read-only backstop (OCM_MCP_READ_ONLY -> refuse)
    SV->>SV: raw byte cap BEFORE parsing (256 KiB) - no JSON bomb
    SV->>GR: validate_manifests(manifests)
    GR->>GR: list + count cap (max 10 manifests)
    GR->>GR: per-manifest schema check first (malformed = clean violation, never a crash)
    GR->>GR: exact (apiVersion, kind) in ALLOWED_GVK - group spoofing blocked
    GR->>GR: namespace required + protected list + kube-*/openshift-*/ocm prefixes
    GR->>GR: Restricted PSS on every container role (regular/init/ephemeral):<br/>runAsNonRoot, no runAsUser 0, allowPrivilegeEscalation=false,<br/>drop ALL, no added caps, seccomp, automountServiceAccountToken=false
    GR->>GR: volume ALLOW-list (configMap/emptyDir/downwardAPI/projected),<br/>no projected serviceAccountToken/secret sources
    GR->>GR: no env secretKeyRef / envFrom secretRef (no path to Secret contents)
    GR->>GR: image pinned - no :latest, no tagless, @sha256 digest in strict mode
    GR->>GR: Service type ClusterIP only, no externalIPs - HPA maxReplicas capped at 100
    GR-->>SV: ok, or GuardrailViolation with EVERY problem listed (agent self-corrects)
    SV->>API: create ManifestWork with dryRun=All (server-side)
    API->>API: Kyverno admission: 9 ClusterPolicies foreach embedded manifest (layer 2,<br/>independent re-check of the same invariants + org policies)
    API-->>SV: admitted (dry-run) or denied with the policy's own message
    SV->>ST: Proposal.save(): uuid4-hex id, content_hash = sha256(canonical<br/>cluster+name+manifests+kind+action+params), status=pending,<br/>atomic write + fsync + chmod 0600
    SV-->>AG: proposal_id + "ask a human to run ocm-mcp approve with this id"

    Note over HU,ST: APPROVE - happens OUTSIDE the agent's reach
    HU->>ST: ocm-mcp show id - reviews the exact manifests
    HU->>AP: mint_token(proposal, operation="apply")
    AP->>AP: claims: jti (random), iss, aud, id, hash=content_hash,<br/>op, approver, iat/nbf/exp (TTL 3600 s)
    AP->>AP: Ed25519 sign with PRIVATE key (CLI side only)
    HU-->>AG: token handed over out-of-band

    Note over AG,API: APPLY - the token is proven, then burned
    AG->>SV: apply_manifestwork(proposal_id, approval_token)
    SV->>ST: proposal_lock(id) - flock serializes concurrent applies
    SV->>SV: _valid_id (32-hex only - path traversal blocked), load, status must be pending
    SV->>SV: TOCTOU defense: re-hash stored content, re-run ALL static guardrails NOW
    SV->>AP: verify_token(proposal, token, operation="apply")
    AP->>AP: signature valid under verifier .pub (or .pub.prev during planned rotation)?
    AP->>AP: iss/aud match? now within nbf..exp? claims.id == proposal.id?
    AP->>AP: claims.hash == re-computed content hash? claims.op == "apply"?<br/>(an apply token can NEVER authorize a rollback)
    AP->>ST: jti already in used_tokens.jsonl? -> replay refused
    AP->>ST: consume: append jti (compact ledger at 2000 lines)
    SV->>API: create ManifestWork (real this time) with<br/>label app.kubernetes.io/managed-by=ocm-mcp-server
    API-->>SV: created (Kyverno + RBAC enforce again, for real)
    SV->>ST: status pending -> applied, record approver + work UID
    SV-->>AG: applied (agent verifies via get_manifestwork status feedback)
```

### 4. Rollback and lifecycle actions - the same gate, different verbs

```mermaid
flowchart TD
    R0["propose_rollback(applied_proposal_id)"] --> R1["loads the APPLIED proposal;<br/>creates a DISTINCT rollback proposal binding<br/>target work name + current UID + origin id"]
    R1 --> R2["human approves it separately:<br/>token claims op=rollback"]
    R2 --> R3["rollback_manifestwork(rollback_id, token)"]
    R3 --> R4{"ownership checks<br/>BEFORE the token is burned"}
    R4 -- "managed-by label missing" --> RX["REJECTED - never deletes<br/>a work it did not create"]
    R4 -- "UID changed since approval" --> RX2["REJECTED - the work was<br/>re-created; re-propose"]
    R4 -- ok --> R5["verify + consume rollback-scoped token<br/>-> DELETE ManifestWork<br/>-> rollback proposal: applied<br/>-> origin proposal: rolled_back"]

    C0["propose_cluster_action(cluster, action, params)"] --> C1["action allow-list: cordon / uncordon /<br/>set_label / accept / enable_addon / disable_addon<br/>- nothing else is even proposable"]
    C1 --> C2["server-side dry-run of the exact patch/create<br/>at PROPOSE time (fails early, clearly)"]
    C2 --> C3["same store -> same human token -> apply_cluster_action"]
    C3 --> C4["cordon/uncordon/set_label/accept: merge-patch ManagedCluster<br/>accept also approves ONLY the CSRs captured (name+uid+<br/>request-hash+CN verified) at approval time<br/>enable/disable_addon: create/delete ManagedClusterAddOn"]
```

### 5. Integrity machinery - audit chain, anchors, keys, state

```mermaid
flowchart TD
    subgraph AUD["audit.jsonl - tamper-evident hash chain"]
        A1["entry N-1<br/>hash H1"] --> A2["entry N<br/>prev=H1<br/>hash H2 = sha256(H1 + canonical(entry))"]
        A2 --> A3["entry N+1<br/>prev=H2 ..."]
    end
    A3 --> V1["verify_audit_chain (ocm-mcp audit-verify)<br/>recomputes every hash -> catches edit,<br/>reorder, mid-log deletion"]
    V1 --> V2["blind spot of a bare chain:<br/>tail truncation + full rewrite"]
    V2 --> V3["closed by ANCHORS: ocm-mcp audit-anchor<br/>(trusted terminal) signs (seq, hash, ts)<br/>with the approval PRIVATE key -> audit_anchors.jsonl"]
    V3 --> V4["audit-verify also fails unless the log still<br/>EXTENDS every anchored head (verifier key only)"]

    subgraph KEYS["key custody"]
        K1["PRIVATE approval_ed25519<br/>CLI / trusted terminal / KMS<br/>signs tokens + anchors"]
        K2["PUBLIC approval_ed25519.pub (+ .pub.prev)<br/>server side - verify only<br/>compromised server cannot mint"]
    end

    subgraph FILES["$OCM_MCP_HOME on disk"]
        F1["proposals/*.json (0600, fsync, forward-only status)"]
        F2["audit.jsonl + audit_anchors.jsonl (0600, flock)"]
        F3["used_tokens.jsonl (replay ledger)"]
    end
```

### 6. Where each guarantee is enforced (quick index)

| Guarantee | Enforced in | Independent backstop |
|---|---|---|
| Only 8 exact GVKs enter a proposal | `guardrails.py` `ALLOWED_GVK` | Kyverno `restrict-manifestwork-gvk` |
| No system/platform namespaces | `guardrails.py` prefixes | Kyverno `protect-system-namespaces` (wildcards) |
| Restricted Pod Security incl. init/ephemeral, no uid 0 | `guardrails._check_pod_security` | Kyverno `restrict-manifestwork-pod-security` |
| No path to Secret contents (env/volume/projected) | `guardrails.py` | Kyverno `disallow-manifestwork-secret-access` |
| ClusterIP-only Services, HPA ceiling | `guardrails.py` | Kyverno `restrict-manifestwork-service-hpa` |
| Pinned images, kind allow-list | `guardrails.py` | Kyverno `restrict-manifestwork-kinds` |
| <= 10 manifests, <= 256 KiB | `guardrails.py` / `server.py` | Kyverno `limit-manifestwork-manifests` |
| Change needs a human | `approvals.verify_token` (sig, hash, op, jti, TTL) | RBAC: server cannot escalate |
| Approval binds exact content | content hash in claims + TOCTOU re-hash at apply | signature breaks on any mutation |
| Every call on the record | `traced_tool` hash chain | signed anchors catch truncation |
| The two layers agree | `hack/parity_contract.py` in CI | 39-case offline `kyverno test` |

The parity between the left and middle columns is not aspirational: CI runs the same
fixture corpus through both layers and fails on any verdict mismatch.

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
