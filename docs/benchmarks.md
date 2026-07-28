# Fleet-scale benchmarks

Two questions this answers: does the hub-side paged list (`ocm.paged_list`)
stay fast as a fleet grows into the thousands of `ManagedCluster` objects, and
does concurrent spoke fan-out (`ocm.fleet_health`, `OCM_MCP_FANOUT_WORKERS`)
actually beat scanning spokes one at a time? Run it yourself with
`hack/bench_fleet.py`; nothing below is invented - every number is from a real
run on the machine and versions listed under Method.

> **Scale caveat**: 1000 = hub-scale simulation (CRs only), ~20 = fan-out scale
> (real apiservers via kwok); a 1000-apiserver fleet does not fit a
> laptop/CI runner.

## Method

**Machine**: Apple M4 Max, 36 GiB RAM, macOS 26.5.2 (Darwin 25.5.0), arm64.

**Versions**: Python 3.14.0 · kind v0.32.0 · kwokctl v0.8.0 (go1.26.4,
darwin/arm64) · kubectl client v1.34.1 · clusteradm v1.3.1 · podman 6.0.2
(container engine used for kind's nodes; kwok spokes ran with
`--runtime binary`, so they needed no container engine at all).

**Fleet under test**: the same kind hub `hack/bootstrap.sh` builds for
everything else in this repo (1 hub + 3 real kind spoke clusters, OCM joined
via `clusteradm`, Kyverno + guardrail policies installed). The benchmark adds
its own fixtures on top and always removes them:

- **hub phase**: 1000 fake `ManagedCluster` CRs (`bench-0` .. `bench-999`,
  label `bench=true`) applied directly to the kind hub - CRs only, no backing
  apiserver, no klusterlet. This is a hub-side API-storage/pagination stress
  test, not a "1000 real clusters" claim.
- **fanout phase**: 20 real, independent kube-apiservers, one per simulated
  spoke, created with `kwokctl create cluster --runtime binary --name
  bench-spokeN`. Each gets a fake `kwok.x-k8s.io/node: fake` Node so the
  scheduler has somewhere to place pods, then ~50 pods (kwok's controller
  simulates them straight to `Running` - no real kubelet or container
  runtime). Each spoke is registered as a `ManagedCluster` on the hub (label
  `bench-fanout=true`) and wired into `OCM_MCP_SPOKE_CONTEXTS` so
  `ocm._spoke_health` does a real pod/deployment list against a real
  apiserver, not a mock.

**Commands** (exactly what produced the tables below):

```bash
bash hack/bootstrap.sh                                   # kind hub + 3 spokes, once
OCM_MCP_HUB_CONTEXT=kind-hub ./.venv/bin/python hack/bench_fleet.py --phase hub
OCM_MCP_HUB_CONTEXT=kind-hub ./.venv/bin/python hack/bench_fleet.py --phase fanout
OCM_MCP_HUB_CONTEXT=kind-hub ./.venv/bin/python hack/bench_fleet.py --phase all
```

`--phase all` runs fanout setup before the hub phase (both share one Python
process, and `OCM_MCP_SPOKE_CONTEXTS` has to be set before `ocm_mcp_server` is
first imported - see the module docstring in `hack/bench_fleet.py`), so the
hub-only row explicitly restricts `fleet_health` to the 1000 fake `bench-N`
clusters rather than "every cluster currently on the hub", keeping the
hub-only measurement honest even when fanout spokes are already registered.
Each number is `min`/`median` of 5 repetitions (`BENCH_REPS`). `--keep` skips
teardown for debugging; without it, the script deletes its 1000 `bench-*`
CRs, its ~20 `bench-spokeN` CRs, and the ~20 kwok clusters, leaving the kind
hub + 3 spokes untouched.

## Results

### Hub phase - 1000 fake `ManagedCluster` CRs

| scenario | best (s) | median (s) |
|---|---|---|
| list_clusters @ 1023 clusters | 0.079 | 0.083 |
| fleet_health (hub only) @ 1000 clusters | 0.083 | 0.087 |

(`list_clusters @ 1023` because this row ran as part of `--phase all`, after
the 20 fanout spokes were already registered on the same hub; a standalone
`--phase hub` run measured `@ 1003 clusters` - 1000 fake + the 3 real
bootstrap spokes - at 0.076s best / 0.081s median, statistically the same.)

Either way: a fleet two-plus orders of magnitude larger than this project's
real kind test fleet reads back in well under a tenth of a second, because
`ocm.paged_list` follows the apiserver's own `continue` tokens instead of
materializing the whole collection at once.

### Fanout phase - 20 real kwok spoke apiservers, ~50 pods each

| scenario | best (s) | median (s) |
|---|---|---|
| fleet_health sequential (workers=1) @ 20 spokes | 0.356 | 0.367 |
| fleet_health concurrent (workers=8) @ 20 spokes | 0.299 | 0.302 |

Speedup: **~1.2x** (median 0.367s -> 0.302s; best 0.356s -> 0.299s) with the
default `OCM_MCP_FANOUT_WORKERS=8` versus sequential (`=1`).

That is a real but modest number, and it is honestly reported rather than
rounded up: all 20 kwok apiservers run as local processes on the same
machine, so per-spoke round-trip latency here is near zero and the
sequential path is never far behind the concurrent one. The fanout
(`concurrent.futures.ThreadPoolExecutor`) exists for the case this benchmark
cannot simulate on a laptop - spokes spread across real networks/regions,
where each `_spoke_health` call pays tens to hundreds of milliseconds of
round-trip latency. There, sequential scan time is `sum(latency)` while
concurrent scan time is close to `max(latency)`; with `N >= workers` spokes at
comparable latency, the expected speedup approaches `workers` (8x at the
default), not the ~1.2x measured here against zero-latency localhost
apiservers. Re-run this benchmark against real geographically distributed
spokes to measure that regime; this repo's CI/laptop environment cannot host
one.

## Caveats

- **1000 = hub-scale simulation (CRs only), ~20 = fan-out scale (real
  apiservers via kwok); a 1000-apiserver fleet does not fit a laptop/CI
  runner.**
- kwok simulates node/pod status server-side; it proves the API-call and
  fan-out path works end-to-end against a real (if minimal) apiserver, not
  real kubelet/container-runtime behavior.
- The fanout speedup measured here is a localhost lower bound, not an upper
  bound - see "Fanout phase" above. Real multi-region fleets should see
  materially more benefit from `OCM_MCP_FANOUT_WORKERS`, not less.
- Numbers are single-machine, single-run-per-phase measurements on a
  developer laptop, not averaged across independent hardware; treat them as
  directional, and re-run `hack/bench_fleet.py` yourself before relying on an
  exact figure.
