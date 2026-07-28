#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Fleet-scale benchmark. Phase 'hub': 1000 fake ManagedCluster CRs on the kind
hub, time hub-path reads. Phase 'fanout': N real kwok spoke apiservers, time
fleet_health with workers=1 vs the concurrent default. Prints a markdown table.

Method notes (see docs/benchmarks.md for the full write-up and measured numbers):

- "hub" scale (default 1000) means CR-only ManagedCluster objects on the kind
  hub - no real kubelet/apiserver behind them. It exercises the hub-side paged
  list path (ocm.paged_list) at a size no real OCM install would reach without
  ACM-scale infrastructure.
- "fanout" scale (default 20) means real, independent kube-apiservers, one per
  simulated spoke, run via kwokctl (kwok simulates node/pod status server-side,
  so pods report Running without a real kubelet or container runtime). This
  exercises the concurrent spoke-scan fanout in ocm.fleet_health / _spoke_health.
- 1000 = hub-scale simulation (CRs only), ~20 = fan-out scale (real apiservers
  via kwok); a 1000-apiserver fleet does not fit a laptop/CI runner.

kubernetes.client Settings (ocm_mcp_server.config.Settings) are read ONCE at
first import of ocm_mcp_server, so OCM_MCP_HUB_CONTEXT / OCM_MCP_SPOKE_CONTEXTS
must be exported (or set in os.environ) BEFORE that first import happens -
this is why setup_fanout() runs, and OCM_MCP_SPOKE_CONTEXTS is populated,
before bench_hub()/bench_fanout() perform their deferred `from ocm_mcp_server
import ocm`. OCM_MCP_FANOUT_WORKERS, by contrast, is read per-call, so it can
be flipped between timed() runs within the same process.
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time

HUB_N = int(os.environ.get("BENCH_HUB_CLUSTERS", "1000"))
KWOK_N = int(os.environ.get("BENCH_KWOK_SPOKES", "20"))
REPS = int(os.environ.get("BENCH_REPS", "5"))
PODS_PER_SPOKE = int(os.environ.get("BENCH_PODS_PER_SPOKE", "50"))
# kwokctl runtime for the spoke apiservers: "binary" needs no container engine
# (lightest for ~20 clusters); "podman"/"docker"/"kind-podman" also work if a
# container engine is available. See docs/benchmarks.md Method for what was
# actually measured on this machine.
KWOK_RUNTIME = os.environ.get("BENCH_KWOK_RUNTIME", "binary")
HUB_CTX = os.environ.get("OCM_MCP_HUB_CONTEXT", "kind-hub")

MC = """apiVersion: cluster.open-cluster-management.io/v1
kind: ManagedCluster
metadata:
  name: bench-{i}
  labels: {{bench: "true"}}
spec:
  hubAcceptsClient: false
"""

# Fan-out spokes get their own name pattern and label so hub-phase and
# fanout-phase ManagedCluster CRs never collide and can be torn down separately.
SPOKE_MC = """apiVersion: cluster.open-cluster-management.io/v1
kind: ManagedCluster
metadata:
  name: {name}
  labels: {{bench-fanout: "true"}}
spec:
  hubAcceptsClient: false
"""

# A single fake kwok Node so the kube-scheduler has somewhere to place pods;
# kwok-controller then simulates the node/pod lifecycle (Ready/Running) without
# a real kubelet or container runtime.
KWOK_NODE = """apiVersion: v1
kind: Node
metadata:
  name: kwok-node-0
  labels: {type: kwok}
  annotations:
    node.alpha.kubernetes.io/ttl: "0"
    kwok.x-k8s.io/node: fake
spec:
  taints:
  - effect: NoSchedule
    key: kwok.x-k8s.io/node
    value: fake
status:
  allocatable: {cpu: "32", memory: 256Gi, pods: "1000"}
  capacity: {cpu: "32", memory: 256Gi, pods: "1000"}
  nodeInfo: {architecture: amd64, kubeletVersion: fake}
  phase: Running
"""

KWOK_POD = """apiVersion: v1
kind: Pod
metadata:
  name: bench-pod-{i}
  namespace: default
  labels: {{bench: "true"}}
spec:
  tolerations:
  - key: kwok.x-k8s.io/node
    operator: Exists
    effect: NoSchedule
  nodeSelector: {{type: kwok}}
  containers:
  - name: c
    image: fake
"""


def sh(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    """Run a command from an argument list - never shell=True (injection-safe)."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)  # type: ignore[call-overload]
    except subprocess.CalledProcessError as exc:
        print(f"$ {' '.join(cmd)}\n{exc.stderr}", file=sys.stderr)
        raise


def _wait_for_default_serviceaccount(ctx: str, tries: int = 20, delay: float = 1.0) -> None:
    """Pod admission looks up the 'default' ServiceAccount even when a pod spec
    doesn't name one; the SA controller creates it a beat after namespace/cluster
    creation, so a pod applied immediately after `kwokctl create cluster` can hit
    a transient "serviceaccount ... not found" 403. Poll instead of racing it."""
    for _ in range(tries):
        if (
            subprocess.run(
                ["kubectl", "--context", ctx, "get", "serviceaccount", "default", "-n", "default"],
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
        ):
            return
        time.sleep(delay)
    raise RuntimeError(f"default ServiceAccount never appeared on {ctx}")


def timed(fn: object, reps: int = REPS) -> tuple[float, float]:
    xs = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()  # type: ignore[operator]
        xs.append(time.perf_counter() - t)
    return min(xs), statistics.median(xs)


def bench_hub() -> list[tuple[str, float, float]]:
    docs = "---\n".join(MC.format(i=i) for i in range(HUB_N))
    sh(["kubectl", "--context", HUB_CTX, "apply", "-f", "-"], input=docs)
    # Deferred import: see module docstring for why this must happen after any
    # OCM_MCP_* env setup, not before.
    from ocm_mcp_server import ocm

    # Real (not hardcoded) count: with --phase all, setup_fanout() runs first,
    # so the hub may already carry the fanout spokes' ManagedCluster CRs too.
    total = len(ocm.list_managed_clusters())
    rows = []
    best, med = timed(ocm.list_managed_clusters)
    rows.append((f"list_clusters @ {total} clusters", best, med))
    # Scope fleet_health to ONLY the fake bench-N CRs (never present in
    # OCM_MCP_SPOKE_CONTEXTS) so this stays a true hub-only measurement even
    # when --phase all has already registered real kwok fanout spokes on the
    # same hub - those would otherwise get scanned too via the fanout-driven
    # default "sorted(hub)" and silently inflate this number.
    bench_clusters = ",".join(f"bench-{i}" for i in range(HUB_N))
    best, med = timed(lambda: ocm.fleet_health(bench_clusters))
    rows.append((f"fleet_health (hub only) @ {HUB_N} clusters", best, med))
    sh(
        [
            "kubectl",
            "--context",
            HUB_CTX,
            "delete",
            "managedclusters",
            "-l",
            "bench=true",
            "--wait=false",
        ]
    )
    return rows


def _spoke_name(i: int) -> str:
    return f"bench-spoke{i}"


def _spoke_ctx(i: int) -> str:
    return f"kwok-{_spoke_name(i)}"


def _existing_kwok_clusters() -> set[str]:
    return set(sh(["kwokctl", "get", "clusters"]).stdout.split())


def setup_fanout() -> str:
    """Create KWOK_N real kwok spoke apiservers, register each as a fake
    ManagedCluster on the hub, seed ~PODS_PER_SPOKE kwok-simulated pods per
    spoke, and return the comma-separated cluster-name list for fleet_health.

    Sets OCM_MCP_SPOKE_CONTEXTS in the environment. This MUST run before the
    first `from ocm_mcp_server import ocm` in the process (see module docstring).
    """
    existing = _existing_kwok_clusters()
    spoke_pairs = []
    for i in range(1, KWOK_N + 1):
        name, ctx = _spoke_name(i), _spoke_ctx(i)
        if name not in existing:
            sh(
                [
                    "kwokctl",
                    "create",
                    "cluster",
                    "--name",
                    name,
                    "--runtime",
                    KWOK_RUNTIME,
                    "--wait",
                    "2m",
                ]
            )
        sh(["kubectl", "--context", ctx, "apply", "-f", "-"], input=KWOK_NODE)
        _wait_for_default_serviceaccount(ctx)
        pods = "---\n".join(KWOK_POD.format(i=j) for j in range(PODS_PER_SPOKE))
        sh(["kubectl", "--context", ctx, "apply", "-f", "-"], input=pods)
        sh(["kubectl", "--context", HUB_CTX, "apply", "-f", "-"], input=SPOKE_MC.format(name=name))
        spoke_pairs.append(f"{name}={ctx}")
    os.environ["OCM_MCP_SPOKE_CONTEXTS"] = ",".join(spoke_pairs)
    return ",".join(_spoke_name(i) for i in range(1, KWOK_N + 1))


def teardown_fanout() -> None:
    sh(
        [
            "kubectl",
            "--context",
            HUB_CTX,
            "delete",
            "managedclusters",
            "-l",
            "bench-fanout=true",
            "--wait=false",
        ]
    )
    for i in range(1, KWOK_N + 1):
        sh(["kwokctl", "delete", "cluster", "--name", _spoke_name(i)])


def bench_fanout(clusters: str) -> list[tuple[str, float, float]]:
    # Deferred import: see module docstring - OCM_MCP_SPOKE_CONTEXTS must
    # already be set (by setup_fanout) before this first import in the process.
    from ocm_mcp_server import ocm

    rows = []
    for workers, label in [("1", "sequential (workers=1)"), ("8", "concurrent (workers=8)")]:
        os.environ["OCM_MCP_FANOUT_WORKERS"] = workers
        best, med = timed(lambda: ocm.fleet_health(clusters), reps=REPS)
        rows.append((f"fleet_health {label} @ {KWOK_N} spokes", best, med))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["hub", "fanout", "all"], default="all")
    ap.add_argument(
        "--keep",
        action="store_true",
        help="skip fanout teardown (leave kwok spokes + their ManagedCluster CRs up, for debugging)",
    )
    args = ap.parse_args()
    os.environ.setdefault("OCM_MCP_HUB_CONTEXT", HUB_CTX)

    rows: list[tuple[str, float, float]] = []
    run_fanout = args.phase in ("fanout", "all")
    # setup_fanout (which sets OCM_MCP_SPOKE_CONTEXTS) MUST run before any
    # ocm_mcp_server import in this process - including the one inside
    # bench_hub() below - or the spoke contexts would never take effect.
    clusters = setup_fanout() if run_fanout else ""
    try:
        if args.phase in ("hub", "all"):
            rows += bench_hub()
        if run_fanout:
            rows += bench_fanout(clusters)
    finally:
        if run_fanout and not args.keep:
            teardown_fanout()

    print("| scenario | best (s) | median (s) |\n|---|---|---|")
    for label, best, med in rows:
        print(f"| {label} | {best:.3f} | {med:.3f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
