# Policy pack: reusable Kyverno guardrails for ManifestWork

The nine `ClusterPolicy` objects in
[`deploy/policies/`](https://github.com/ocm-mcp-server/ocm-mcp-server/tree/main/deploy/policies)
are layer 2 of this project's four-layer model. They are also a standalone pack: if you
run Open Cluster Management and let anything automated propose `ManifestWork` objects —
an agent, a controller, a CI job — they apply to you whether or not you run this server.

```bash
kubectl apply -f deploy/policies/     # install
kyverno test deploy/policies/tests    # 42 offline cases, no cluster needed
```

The pack's own entry point, with the full per-policy table and adoption instructions, is
[`deploy/policies/README.md`](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/deploy/policies/README.md).

## The problem these solve

A `ManifestWork` is an envelope. What is dangerous is not the `ManifestWork` but the
Deployment, Service, or Pod spec **embedded inside** `spec.workload.manifests`.

Ordinary pod-security policies never see that content. They match `Pod` and `Deployment`
at admission on the cluster where those objects are created — and on the hub, no such
object is ever created, only an envelope containing them. A privileged container can
travel across a fleet as a perfectly ordinary-looking custom resource, and every
Pod-shaped admission control on the hub will wave it through.

These policies iterate `spec.workload.manifests` with `foreach` and validate each
embedded manifest on its own. No policy in the upstream Kyverno catalog demonstrates
validating workloads nested inside another CR, which is why this set was offered
upstream as a `Multi-Cluster Guardrails` example — see
[upstream notes](upstream-notes.md).

## Two identifiers, and why both matter

Adopting the pack elsewhere means changing exactly two things: the
`app.kubernetes.io/managed-by` label the content policies key on (11 occurrences across
8 policies), and the ServiceAccount named in `require-managed-by-label.yaml`.

Changing one without the other yields a pack that looks installed and enforces nothing.
The eight content policies match on a **label**, which the request itself controls — so
alone, a proposer could simply omit the label and skip every check.
`require-managed-by-label` closes that by matching on the **authenticated identity**,
which a request cannot forge, and requiring the label to be present. The label is only
trustworthy because a second policy makes it mandatory for that identity.

## Which Kyverno versions were actually tested

Every policy carries `policies.kyverno.io/minversion: 1.15.0`. That floor was measured
by running the pack against real Kyverno CLI binaries, not inferred from release notes.

| Version | Result |
| --- | --- |
| 1.12.0 | Verdicts identical to current |
| **1.13.0, 1.13.6** | **Under-enforces pod security** |
| 1.14.0 | Cannot evaluate a custom resource offline without its CRD |
| 1.15.0, 1.16.0, 1.17.0 | Verdicts identical to current |
| 1.18.2, 1.19.0 | `kyverno test` 42/42 |

The floor is deliberately **not** the oldest version that works. 1.12.0 behaves
correctly, but the whole 1.13 line silently under-enforces
`restrict-manifestwork-pod-security`: a container declaring both `runAsNonRoot: true`
and `runAsUser: 0` — a contradiction that has to be rejected — is admitted, so 7 of 8
violating fixtures are caught instead of 8. Naming 1.12.0 as the floor would place a
release that *quietly weakens a security control* inside the supported range. 1.15.0 is
the oldest floor above which every release is verified good.

If you are pinned to 1.13.x, treat that policy as advisory and rely on the
proposer-side check in
[`guardrails.py`](https://github.com/ocm-mcp-server/ocm-mcp-server/blob/main/src/ocm_mcp_server/guardrails.py)
as primary. This is exactly the case the two-layer design exists for: the Python checks
and the Kyverno checks are independent, and a gap in one is covered by the other.

## Why the pack ships with tests

`kyverno test deploy/policies/tests` runs 42 cases over 25 `ManifestWork` fixtures with
no cluster. Several assert a **pass** on purpose: `bad-gvk-spoof` is required to pass
the kind-only allow-list and fail the exact-GVK one, which is the whole argument for
shipping both policies rather than one.

Beyond that, `hack/parity_contract.py` enforces in CI that every labelled fixture
reaches the same verdict from the Kyverno policies and from the Python guardrails — so
the two enforcement layers cannot silently drift apart. Adding a policy means adding
fixtures, or the contract fails.

See also: [Guardrails](guardrails.md) for the four-layer model,
[Deployment](deployment.md) for installing them on a hub.
