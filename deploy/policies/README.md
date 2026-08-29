<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Multi-Cluster Guardrails: a Kyverno policy pack for ManifestWork

Nine `ClusterPolicy` objects that validate the workload **inside** an Open Cluster
Management `ManifestWork`, on the hub, before it is ever distributed to a spoke.

They are the hub-side backstop in [ocm-mcp-server](https://github.com/ocm-mcp-server/ocm-mcp-server)'s
four-layer model, and they are written to be lifted out and used on their own. If you
run OCM and let anything automated propose `ManifestWork` objects — an agent, a
controller, a CI job — these apply to you whether or not you run this server.

```bash
kubectl apply -f deploy/policies/          # install the pack
kyverno test deploy/policies/tests         # 42 offline cases, no cluster needed
```

## Why a pack for this exists at all

A `ManifestWork` is an envelope. The dangerous content is not the `ManifestWork`
itself — it is the Deployment, Service, or Pod spec **embedded inside**
`spec.workload.manifests`, as a list of arbitrary objects.

Ordinary pod-security policies never see that content. They match `Pod` and
`Deployment` at admission on the cluster where those objects are created, and on the
hub no such object is ever created — only an envelope containing them. A privileged
container can therefore travel across a fleet as a completely ordinary-looking
custom resource.

These policies iterate `spec.workload.manifests` with `foreach` and validate each
embedded manifest individually. That is the pattern worth stealing, and it is why
this set was contributed upstream: the Kyverno catalog has no example of validating
workloads nested inside another CR.

Verbatim from [`disallow-privileged-manifestwork.yaml`](disallow-privileged-manifestwork.yaml):

```yaml
validate:
  foreach:
    - list: request.object.spec.workload.manifests
      deny:
        conditions:
          any:
            - key: "{{ length(element.spec.template.spec.containers[?securityContext.privileged == `true`] || `[]`) }}"
              operator: GreaterThan
              value: 0
```

Two details there are load-bearing. `element` is the embedded manifest for this
iteration, so the JMESPath after it is an ordinary Pod-spec path.

The empty-list fallback matters far more than it looks. A manifest carrying no
`containers` key yields null, and `length()` of null is an error rather than zero.
Deleting that one fallback from this policy and re-running it over the same fixtures
measures the damage:

| | pass | fail | error |
| --- | --- | --- | --- |
| as written | 20 | 3 | 0 |
| fallback removed | 0 | 2 | 21 |

21 of 23 evaluations stop evaluating, and one violation that was being rejected is no
longer caught. Copy this pattern if you write your own `foreach` rules: without it a
rule degrades on exactly the malformed input you most want to reject.

## The policies

| Policy | Sev | What it refuses |
| --- | --- | --- |
| [`require-managed-by-label`](require-managed-by-label.yaml) | high | A `ManifestWork` created by the server's ServiceAccount **without** the `managed-by` label. Closes the bypass where dropping a label skips every policy below. |
| [`restrict-manifestwork-gvk`](restrict-manifestwork-gvk.yaml) | high | Any embedded manifest whose exact `apiVersion`/`kind` pair is not allow-listed. Stops group spoofing (`evil.example/v1, kind: Deployment`). |
| [`restrict-manifestwork-kinds`](restrict-manifestwork-kinds.yaml) | medium | Unlisted workload kinds, and images that are not pinned — including `initContainers` and `ephemeralContainers`, not just `containers`. |
| [`restrict-manifestwork-pod-security`](restrict-manifestwork-pod-security.yaml) | high | Embedded workloads that miss a Restricted Pod Security baseline: root, privilege escalation, undropped capabilities, missing seccomp, mounted service-account tokens. |
| [`disallow-privileged-manifestwork`](disallow-privileged-manifestwork.yaml) | high | Privileged containers, host namespaces, and `hostPath` volumes in any embedded spec. |
| [`disallow-manifestwork-secret-access`](disallow-manifestwork-secret-access.yaml) | high | Every indirect route to Secret contents: `secretKeyRef`, `envFrom.secretRef`, projected `serviceAccountToken`. Volume types are an **allow**-list, so exotic sources are refused too, not only enumerated bad ones. |
| [`protect-system-namespaces`](protect-system-namespaces.yaml) | high | Embedded manifests with no namespace, or targeting `kube-system`, `kube-public`, `kube-node-lease`, `open-cluster-management*`, or `kyverno`. |
| [`restrict-manifestwork-service-hpa`](restrict-manifestwork-service-hpa.yaml) | medium | Services that are not `ClusterIP`, any `externalIPs`, and autoscalers above 100 replicas. |
| [`limit-manifestwork-manifests`](limit-manifestwork-manifests.yaml) | medium | More than 10 embedded manifests, so an approval stays small enough for a human to actually review. |

## Adopting the pack outside this project

There are exactly **two** identifiers to change. Kyverno `ClusterPolicy` has no native
parameterisation, so these are deliberately left as plain values you edit rather than
templated — templating them would break the offline test suite, which is the most
useful thing in this directory.

**1. The label the content policies key on** — 11 occurrences across the eight content
policies:

```yaml
selector:
  matchLabels:
    app.kubernetes.io/managed-by: ocm-mcp-server   # <- your proposer's label
```

**2. The requester identity** in `require-managed-by-label.yaml`, which is what makes
the label trustworthy:

```yaml
subjects:
  - kind: ServiceAccount
    name: ocm-mcp-server                # <- your proposer's ServiceAccount
    namespace: open-cluster-management  # <- and its namespace
```

That second one carries the whole design. The eight content policies match on a
**label**, which the request itself controls — so on its own, a proposer could omit the
label and skip every check. `require-managed-by-label` matches on the **authenticated
identity** instead, which the request cannot forge, and requires the label to be
present. Change one without the other and you have a pack that looks installed and
enforces nothing.

## Tested Kyverno versions

Every policy carries `policies.kyverno.io/minversion: 1.15.0`. That floor was
established by running the pack against real CLI binaries, not by reading release
notes:

| Version | Result |
| --- | --- |
| 1.12.0 | Verdicts identical to current |
| **1.13.0, 1.13.6** | **Under-enforces — see below** |
| 1.14.0 | Cannot evaluate a custom resource offline without its CRD |
| 1.15.0, 1.16.0, 1.17.0 | Verdicts identical to current |
| 1.18.2, 1.19.0 | `kyverno test` 42/42 |

The floor is **not** simply the oldest version that works. 1.12.0 does behave
correctly, but the entire 1.13 line silently under-enforces
`restrict-manifestwork-pod-security`: a container declaring both `runAsNonRoot: true`
and `runAsUser: 0` — a contradiction that must be rejected — is admitted, 7 fixtures
caught instead of 8. Declaring 1.12.0 as the floor would place a version that
*quietly weakens a security control* inside the supported range. 1.15.0 is the oldest
floor above which every release is verified good.

If you must run 1.13.x, treat this policy as advisory and rely on the proposer-side
check as primary.

## The test suite

```bash
kyverno test deploy/policies/tests    # 42 cases, offline, no cluster
```

25 `ManifestWork` fixtures in [`tests/resources.yaml`](tests/resources.yaml) covering
good proposals, each specific bypass, and human-created (unlabelled) work that must be
**skipped** rather than passed. Several cases exist to document *why a second policy is
needed* — `bad-gvk-spoof` is asserted to **pass** the kind-only allow-list and **fail**
the exact-GVK one, which is the entire argument for having both.

Adding a policy means adding fixtures: `hack/parity_contract.py` enforces that every
labelled fixture here reaches the same verdict as the proposer-side checks in
`src/ocm_mcp_server/guardrails.py`, and it runs in CI.

## Upstream

Contributed to [kyverno/policies](https://github.com/kyverno/policies) as a
`Multi-Cluster Guardrails` category example set — see
[docs/upstream-notes.md](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/docs/upstream-notes.md).
Apache-2.0; take them, adapt them, no attribution required.
