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
# three policies, all READY
```

Export the environment bootstrap printed, register the server with your MCP
client ([examples/](../examples/)), and run the smoke test from the
[worked examples](examples.md).

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
export OCM_MCP_HUB_CONTEXT=<hub-context>
export OCM_MCP_SPOKE_CONTEXTS=prod-tokyo=prod-tokyo-reader,prod-osaka=prod-osaka-reader
ocm-mcp-server
```

Cluster names on the left must match `kubectl --context <hub> get managedclusters`
exactly.

## Path C: Docker

```bash
docker build -t ocm-mcp-server .
docker run -i --rm \
  -v ~/.kube/config:/kube/config:ro \
  -e KUBECONFIG=/kube/config \
  -e OCM_MCP_HUB_CONTEXT=<hub-context> \
  -e OCM_MCP_SPOKE_CONTEXTS=... \
  ocm-mcp-server
```

Point your MCP client's `command` at `docker` with those args (stdio passes
through `-i`). Mount a dedicated volume for `OCM_MCP_HOME` if you want the
audit log and proposals to survive container restarts.

## Production hardening checklist

- [ ] **Spoke transport:** replace direct spoke contexts with the OCM
      cluster-proxy add-on so the server host holds hub credentials only.
- [ ] **Dedicated identities:** one server instance and one hub ServiceAccount
      per agent, so RBAC and the audit log separate them.
- [ ] **State directory:** put `OCM_MCP_HOME` on encrypted disk; the approval
      secret lives there (0600). Rotate it by deleting the file; open
      proposals then need re-approval, which is the safe failure mode.
- [ ] **Audit shipping:** tail `audit.jsonl` into your log pipeline; it is
      append-only JSON lines.
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
