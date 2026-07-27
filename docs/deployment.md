# Deployment guide

Three paths, in increasing order of seriousness: a laptop fleet for trying the
pattern, a real OCM fleet, and a hardened production setup. Troubleshooting is
at the end.

## Path A: laptop fleet (kind)

### Prerequisites

| Tool | Install (macOS) | Install (Linux) |
|---|---|---|
| docker | Docker Desktop / colima | distro package |
| kind | `brew install kind` | [kind releases](https://kind.sigs.k8s.io/docs/user/quick-start/) |
| kubectl | `brew install kubectl` | distro package |
| clusteradm | `curl -L https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh \| bash` | same |
| helm | `brew install helm` | [helm.sh](https://helm.sh/docs/intro/install/) |
| Python 3.11+ | `brew install python` | distro package |

Plan for roughly 8 GB of free RAM for the 4-cluster fleet. With less, run
`SPOKES=1 ./hack/bootstrap.sh` for a 2-cluster variant.

### Steps

```bash
git clone https://github.com/sandeepbazar/ocm-mcp-server.git
cd ocm-mcp-server
make bootstrap        # ~10-15 min on first run (image pulls)
make install
```

What bootstrap does, in order: creates the kind clusters; `clusteradm init` on
the hub; joins and accepts each spoke; installs Kyverno via helm; applies the
guardrail policies and RBAC; creates a read-only ServiceAccount on each spoke;
starts a Jaeger container (skip with `--no-jaeger`); deploys the demo app.

Verify:

```bash
kubectl --context kind-hub get managedclusters
# NAME       HUB ACCEPTED   AVAILABLE
# cluster1   true           True
# cluster2   true           True
# cluster3   true           True

kubectl --context kind-hub get clusterpolicies
# five policies, all READY
```

Export the environment bootstrap printed (if you are unsure what those context
names mean, the [context names guide](kubeconfig-contexts.md) explains them),
register the server with your MCP client ([examples/](../examples/)), and run
the smoke test from the [worked examples](examples.md).

Tear down with `make teardown`.

## Path B: an existing OCM fleet

Works with any conformant hub: upstream OCM, or distributions built on it.
Product distributions usually run the same hub APIs
(`cluster.open-cluster-management.io`, `work.open-cluster-management.io`), which
is all this server touches.

### 1. Hub-side identity and policies

```bash
kubectl --context <hub-context> apply -f deploy/rbac.yaml
kubectl --context <hub-context> apply -f deploy/policies/
```

Review `deploy/policies/` against your org's standards first; the files are
small on purpose. If you already run Kyverno with your own policy set, the
dry-run gate picks those up automatically as well.

### 2. Read-only spoke access (optional but recommended)

For `query_events`, `get_pod_logs`, and spoke-side health, the server needs a
read-only context per cluster. On each spoke:

```bash
kubectl create serviceaccount ocm-mcp-reader -n default
kubectl apply -f - <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ocm-mcp-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "namespaces", "services"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ocm-mcp-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ocm-mcp-reader
subjects:
  - kind: ServiceAccount
    name: ocm-mcp-reader
    namespace: default
EOF

# a kubeconfig context from the ServiceAccount token:
TOKEN=$(kubectl create token ocm-mcp-reader -n default --duration=8760h)
kubectl config set-credentials <cluster>-reader --token="$TOKEN"
kubectl config set-context <cluster>-reader \
  --cluster=<cluster-entry-in-kubeconfig> --user=<cluster>-reader
```

### 3. Run the server

```bash
pip install ocm-mcp-server   # released on PyPI; or: uvx ocm-mcp-server

export OCM_MCP_HUB_CONTEXT=<hub-context>
export OCM_MCP_SPOKE_CONTEXTS=prod-tokyo=prod-tokyo-reader,prod-osaka=prod-osaka-reader
ocm-mcp-server
```

Cluster names on the left must match `kubectl --context <hub> get managedclusters`
exactly; the context names on the right come from your kubeconfig. If that
left-vs-right distinction is unfamiliar, read the
[context names guide](kubeconfig-contexts.md) first, it walks through both.

## Path C: Docker

Use the signed image published on every release (or build your own with
`docker build -t ocm-mcp-server .`):

```bash
docker run -i --rm \
  -v ~/.kube/config:/kube/config:ro \
  -e KUBECONFIG=/kube/config \
  -e OCM_MCP_HUB_CONTEXT=<hub-context> \
  -e OCM_MCP_SPOKE_CONTEXTS=... \
  ghcr.io/sandeepbazar/ocm-mcp-server
```

Point your MCP client's `command` at `docker` with those args (stdio passes
through `-i`). Mount a dedicated volume for `OCM_MCP_HOME` if you want the
audit log and proposals to survive container restarts.

### Verify what you run

Every published image is signed keyless with [Cosign](https://docs.sigstore.dev/) from
this repository's CI, with an SBOM and SLSA provenance attached. Before trusting an
image, verify the signature was produced by this repo's release workflow:

```bash
cosign verify \
  --certificate-identity-regexp '^https://github.com/sandeepbazar/ocm-mcp-server/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/sandeepbazar/ocm-mcp-server:latest
```

## Path D: in-cluster via Helm (or raw manifests)

A reference [Deployment](../deploy/deployment.yaml) and a Helm chart
([`deploy/charts/ocm-mcp-server`](../deploy/charts/ocm-mcp-server)) run the server as a
workload on the hub, with a Restricted pod security context, resource limits, a
read-only verifier-key mount, a NetworkPolicy, and a PodDisruptionBudget.

```bash
# 1. Apply the least-privilege RBAC (ServiceAccount + ClusterRole/Binding).
kubectl apply -f deploy/rbac.yaml

# 2. Provide ONLY the public approval verifier key (the private signer stays off-cluster).
kubectl -n open-cluster-management create secret generic ocm-mcp-approval-pub \
  --from-file=approval_ed25519.pub=$HOME/.ocm-mcp/approval_ed25519.pub

# 3. Install. Defaults to OCM_MCP_READ_ONLY=1 - a safe, inspection-only posture.
helm install ocm-mcp deploy/charts/ocm-mcp-server -n open-cluster-management \
  --set image.digest=sha256:<pin-me> \
  --set persistence.enabled=true      # a PVC; otherwise proposals/ledger/audit are lost on restart
```

Transport note: the server speaks MCP over stdio today, so an in-cluster Deployment is
normally attached by a client (sidecar or `kubectl exec`); a standalone authenticated HTTP
transport is on the roadmap. With `persistence.enabled=false` (the default) state lives in an
`emptyDir` and does **not** survive a restart - enable the PVC and ship the audit log to an
external sink before any write-enabled use.

## Production hardening checklist

- [ ] **Spoke transport:** replace direct spoke contexts with the OCM
      cluster-proxy add-on so the server host holds hub credentials only.
- [ ] **Dedicated identities:** one server instance and one hub ServiceAccount
      per agent, so RBAC and the audit log separate them.
- [ ] **Off-box signer:** keep the private Ed25519 signing key off the server via
      `OCM_MCP_SIGNER_KEY` (a separate account/device); the server needs only the
      public verifier (`OCM_MCP_VERIFIER_KEY`, mounted read-only). Co-located, the
      "a compromised server cannot mint tokens" property is only a filesystem
      convention. Rotate with `ocm-mcp rotate-secret`; open proposals then need
      re-approval, the safe failure mode.
- [ ] **State directory:** put `OCM_MCP_HOME` on encrypted, persistent disk (a PVC in
      the chart); it holds proposals, the spent-token replay ledger, and the audit log,
      all of which are lost on restart with `emptyDir`.
- [ ] **Audit shipping:** tail `audit.jsonl` (hash-chained; verify with
      `ocm-mcp audit-verify`) into your log pipeline, or set `OCM_MCP_AUDIT_ECHO=1` to
      stream it to stderr for a collector. Tail truncation needs external anchoring.
- [ ] **Metrics:** set `OCM_MCP_METRICS_PORT` for Prometheus `/metrics` (binds
      localhost unless `OCM_MCP_METRICS_HOST` is set).
- [ ] **Tracing:** set `OTEL_EXPORTER_OTLP_ENDPOINT` at your collector; spans
      carry tool names and redact approval tokens.
- [ ] **Token TTL:** drop `OCM_MCP_APPROVAL_TTL` below the default hour if
      your change windows are short.
- [ ] **Policies:** extend `deploy/policies/` with org-specific rules; run
      `make policy-test` in your CI with your own test resources added.
- [ ] **Upgrades:** pin the package version; read the [CHANGELOG](../CHANGELOG.md)
      before bumping; the tool surface is the compatibility contract.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `clusteradm join` hangs | Spoke cannot reach the hub API. On kind, keep `--force-internal-endpoint-lookup` (bootstrap does). On real networks, check the hub API address is reachable from the spoke. |
| Policies not rejecting anything | Kyverno webhooks not ready yet (`kubectl -n kyverno get pods`), or the ManifestWork lacks the `app.kubernetes.io/managed-by: ocm-mcp-server` label that scopes the policies. |
| `No read context configured for cluster 'X'` | The name before `=` in `OCM_MCP_SPOKE_CONTEXTS` must match the ManagedCluster name on the hub, not the kind cluster name. |
| Dry-run passes but apply fails | Policy set changed between propose and apply, or RBAC differs for create vs dry-run. Re-propose; the fresh dry-run reports the current policy verdict. |
| `Approval token has expired` | TTL passed between `ocm-mcp approve` and the agent's apply. Approve again; tokens are single-proposal and cheap to re-mint. |
| Agent claims success but nothing changed | Check `ocm-mcp audit`: if `apply_manifestwork` is absent or errored, the model narrated an outcome it never achieved. This is exactly what the audit log is for. |
