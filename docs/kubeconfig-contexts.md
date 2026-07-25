# Finding your kubeconfig context names

This server is configured with **kubeconfig context names**, like `kind-hub` or
`cluster1=kind-cluster1`. If you have not seen these before, this page explains
exactly what they are and the commands to find yours. No prior background is
assumed.

## What is a context?

`kubectl` talks to clusters using a config file at `~/.kube/config`. That file
holds one or more **contexts**. A context is just a saved shortcut that bundles
three things: which cluster to talk to, which user/credentials to use, and a
default namespace. When you run `kubectl`, it uses one context at a time.

A context has a **name**. That name is the only thing this server needs. You do
not edit the kubeconfig file by hand; you just tell the server which context
names to use.

## The one command to see all your context names

```bash
kubectl config get-contexts
```

Example output:

```
CURRENT   NAME            CLUSTER         AUTHINFO        NAMESPACE
*         kind-hub        kind-hub        kind-hub
          kind-cluster1   kind-cluster1   kind-cluster1
          kind-cluster2   kind-cluster2   kind-cluster2
          kind-cluster3   kind-cluster3   kind-cluster3
```

The values you need are in the **NAME** column. The `*` marks your current
context. That is all there is to it. (`kubectl config current-context` prints
just the current one.)

## Case 1: the laptop quickstart (kind)

If you ran `make bootstrap`, you do not have to find anything, the script
creates the clusters and **prints the exact values to copy** at the end.

For reference, [kind](https://kind.sigs.k8s.io/) always names its context
`kind-<cluster-name>`. Since bootstrap creates clusters named `hub`,
`cluster1`, `cluster2`, `cluster3`, the context names are:

```bash
export OCM_MCP_HUB_CONTEXT=kind-hub
export OCM_MCP_SPOKE_CONTEXTS=cluster1=kind-cluster1,cluster2=kind-cluster2,cluster3=kind-cluster3
```

See your kind clusters any time with:

```bash
kind get clusters          # hub, cluster1, cluster2, cluster3
```

## Case 2: real clusters (how a context gets created when you log in)

For real clusters, a context is added to your kubeconfig **when you log in or
fetch credentials**. You do this once per cluster, with whatever tool matches
where the cluster runs:

| Where the cluster runs | Command that adds a context |
|---|---|
| Amazon EKS | `aws eks update-kubeconfig --name <cluster> --region <region>` |
| Google GKE | `gcloud container clusters get-credentials <cluster> --region <region>` |
| Azure AKS | `az aks get-credentials --resource-group <rg> --name <cluster>` |
| OpenShift | `oc login <api-url> --token=<token>` (or `--username`) |
| A kubeconfig file someone gave you | `export KUBECONFIG=/path/to/that/file` |
| Rancher / other | download the cluster's kubeconfig from its UI, then `export KUBECONFIG=...` |

After running the relevant command, list your contexts again to see the new
name and use it:

```bash
kubectl config get-contexts
# copy the NAME of your hub cluster into OCM_MCP_HUB_CONTEXT
```

Context names from these tools can be long (for example
`arn:aws:eks:us-east-1:123456789:cluster/prod-hub`). You can rename a context to
something short:

```bash
kubectl config rename-context <long-name> prod-hub
```

Then use `prod-hub`.

## Filling in the two settings

**`OCM_MCP_HUB_CONTEXT`** is a single context name: the one for your **hub**
cluster (where Open Cluster Management runs). Verify you picked the right one:

```bash
kubectl --context <your-hub-context> get managedclusters
# should list your fleet's clusters
```

**`OCM_MCP_SPOKE_CONTEXTS`** is a comma-separated list of `name=context` pairs,
one per managed cluster. There are two different names in each pair, and getting
them straight is the one thing people trip on:

```
OCM_MCP_SPOKE_CONTEXTS = <managed-cluster-name> = <kubeconfig-context-name> , ...
                          ▲                        ▲
     the name the HUB knows the cluster by         the context in YOUR kubeconfig
     (left side)                                   (right side)
```

- **Left side** (the managed-cluster name) comes from the hub:

  ```bash
  kubectl --context <your-hub-context> get managedclusters
  # NAME       HUB ACCEPTED   AVAILABLE
  # prod-tokyo true           True
  # prod-osaka true           True
  ```

- **Right side** (the kubeconfig context) comes from your own machine:

  ```bash
  kubectl config get-contexts     # pick the NAME for each cluster
  ```

So if the hub calls a cluster `prod-tokyo` and your kubeconfig context for it is
`tokyo-reader`, the pair is `prod-tokyo=tokyo-reader`.

For the laptop quickstart both names happen to line up simply
(`cluster1=kind-cluster1`), which is why it looks repetitive there.

> `OCM_MCP_SPOKE_CONTEXTS` is only needed for reading events and logs from the
> managed clusters. The hub-level tools (`list_clusters`,
> `get_cluster_health` hub view, proposals, apply) work with just
> `OCM_MCP_HUB_CONTEXT`. You can start with only the hub and add spokes later.

For the read-only spoke ServiceAccounts referenced on the right side of real-fleet
pairs, see [Path B in the deployment guide](deployment.md#path-b-an-existing-ocm-fleet).

## Quick checklist

- [ ] `kubectl config get-contexts` shows the contexts I expect
- [ ] `OCM_MCP_HUB_CONTEXT` is the hub's context name
- [ ] `kubectl --context $OCM_MCP_HUB_CONTEXT get managedclusters` lists my fleet
- [ ] each `OCM_MCP_SPOKE_CONTEXTS` pair is `hub-name=my-context-name`
- [ ] (kind users) I just copied what `make bootstrap` printed
