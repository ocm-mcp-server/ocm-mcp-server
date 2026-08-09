<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
Status: draft
Published: (pending)
Canonical: (pending)
-->

# The Operator's Chair: What It Actually Feels Like When an AI Agent Manages Your Kubernetes Fleet

*A practitioner walkthrough - not the agent's side, but yours. Placement decisions, fleet health at 3am, the approval token, and what the audit log hands you when something goes wrong.*

---

![HERO IMAGE PLACEHOLDER](./images/03-hero-operator-chair.png)
<!-- IMAGE 1: HERO
Prompt for ChatGPT image generation:
"A human operator sitting in a dimly lit operations center, facing a large curved monitor wall displaying a live Kubernetes multi-cluster fleet map. Multiple hexagonal cluster nodes glow in teal and blue across a dark topology map. On a separate panel to the right, a chat interface shows an AI assistant conversation. The operator's hand is hovering over a physical hardware token/key on the desk. Atmosphere: calm authority, late night, cinematic. Style: photorealistic digital art, dark theme with teal and blue accent lighting. No text overlays."
-->

---

Most writing about AI agents and Kubernetes focuses on the agent. What it can do. What it tries to do. What you have to stop it from doing. That framing makes sense when you are designing the guardrails.

But once the guardrails exist, someone still has to sit in the operator's chair. That person is not building the agent. They are running a fleet - today 12 clusters, next quarter probably 40 - and the question they are asking is much more practical: does this thing actually make my job easier, or does it just add a new thing I have to watch?

This is that story.

I run a mixed fleet: production OpenShift clusters on-prem, a handful of ROSA clusters in AWS, and several development clusters on bare-metal kind nodes that the platform team spins up for testing. Open Cluster Management (OCM) sits as the hub layer. I recently started routing agent requests through [ocm-mcp-server](https://github.com/sandeepbazar/ocm-mcp-server) - an MCP server that gives AI assistants a read/write interface to OCM, with every write gated behind static guardrails, a Kyverno dry-run, and a human approval token that only I can sign.

What follows is not a pitch. It is a log of what the operator's side of this actually looks like.

---

## The thing that changed first: the morning briefing

Before: I open a terminal, run `clusteradm get clusters`, look at the output, grep for anything that looks wrong, open the hub dashboard, cross-reference alerts. This takes about fifteen minutes and still misses things, because "looks wrong" is a fuzzy standard and my eyes are not perfect.

After: I open my AI assistant, type "fleet health", and get back a structured summary. Clusters sorted by problem severity, degraded deployments with namespace context, unhealthy pods with their restart counts, conditions from the hub, and a diff from yesterday's scan when one is available. The whole thing takes about thirty seconds of reading.

![FLEET HEALTH COMPARISON PLACEHOLDER](./images/03-fleet-health-before-after.png)
<!-- IMAGE 2: FLEET HEALTH COMPARISON
Prompt for ChatGPT image generation:
"A split-screen comparison. LEFT side: a dark terminal window showing raw kubectl and clusteradm command output - walls of YAML and JSON text, status fields buried in noise. RIGHT side: a clean structured AI chat response showing a fleet health summary with color-coded cluster cards - green healthy clusters, amber warning clusters, red critical clusters with clear bullet-point descriptions. Style: flat illustration, dark background, teal/green/amber/red status colors. Label the sides 'Before' and 'After'. No real cluster names."
-->

The underlying tools are `get_fleet_health` and `query_events`. The agent calls them, formats the result, and surfaces what matters. I verified that the raw data matches what I would get from `kubectl` directly - it does, because the server reads from the same hub API. What changed is not the data. It is the time cost of parsing it.

That might sound like a small thing. It is not. When you run forty clusters and get paged at 3am, the difference between fifteen minutes to understand the blast radius and forty seconds is real.

---

## Placement: the question I used to answer by hand

OCM's placement API is elegant in theory. In practice, the loop of "write a Placement, check which PlacementDecision it produced, notice it selected the wrong clusters, figure out why, adjust the label selectors, repeat" used to eat an hour easily.

A typical session now looks like this:

> **Me:** Which clusters does the `production-eu` placement currently select?
>
> **Agent:** The `production-eu` placement selects 3 clusters: `ocp-frankfurt-01`, `ocp-paris-02`, `rosa-dublin-01`. All three meet the `region=eu` and `environment=production` label requirements. `ocp-amsterdam-03` is excluded because it is cordoned - taint `ocm-mcp-server.io/cordoned` was applied 4 days ago.
>
> **Me:** Why is Amsterdam cordoned?
>
> **Agent:** The cordon proposal (ID `prop-0042`) was applied on 2026-08-05. The approval record shows the reason: "network instability during maintenance window, pending validation." No uncordon proposal exists.
>
> **Me:** Can you propose uncordoning it?
>
> **Agent:** PROPOSED - proposal ID `prop-0089`. Summary: "Remove cordon from ocp-amsterdam-03; maintenance-window network issue resolved per NOC ticket OPS-4471." Run `ocm-mcp approve prop-0089` to generate the approval token.

That last step is the one that matters. The agent produces a proposal. The proposal is stored. To apply it, I run `ocm-mcp approve prop-0089` from my terminal - the CLI that holds the Ed25519 signing key. The token is content-bound: it will only authorize that exact change on that exact cluster. It expires in one hour.

The agent never gets the key. The agent cannot approve its own proposals. The chain of custody is: model output, then proposal, then human review, then human-signed token, then apply.

![APPROVAL FLOW PLACEHOLDER](./images/03-approval-flow-operator.png)
<!-- IMAGE 3: APPROVAL FLOW
Prompt for ChatGPT image generation:
"A clear linear flow diagram on a dark background. Four distinct stages connected by arrows: (1) 'AI Agent' icon proposing a change, shown as a robot/AI symbol with a document; (2) 'Proposal Store' shown as a locked filing cabinet with a padlock; (3) 'Human Operator' shown as a person at a terminal typing an approve command, with a physical key icon; (4) 'OCM Hub' shown as a Kubernetes wheel/helm symbol with clusters beneath it receiving the change. The arrow from stage 2 to 3 is labeled 'Review Required', the arrow from 3 to 4 is labeled 'Signed Token'. Color scheme: dark navy background, teal accents, amber for the human operator stage. Style: clean technical diagram, flat design."
-->

---

## The incident that made me trust the audit log

Six weeks in, a deployment on `ocp-frankfurt-01` rolled back unexpectedly. My first instinct was to check whether the agent had done something. That is a reasonable first instinct when you have introduced a new actor into your environment.

I ran `ocm-mcp get-audit-trail --last 50`. The output is a hash-chained JSON log: every tool call, with the arguments, the outcome, the actor identity, and the timestamp. Each entry carries the SHA-256 hash of the previous entry, so you can verify the chain has not been tampered with.

The agent had made three read calls in the relevant window - `get_cluster_health`, `list_manifestworks`, `query_events` - and nothing else. No write proposals. No applies. The rollback had a different cause: a resource quota that had silently been too low for the new pod count.

What struck me was not the exoneration. It was how quickly I had a definitive answer. The audit log is not a nice-to-have compliance artifact. It is the primary debugging tool for "what did the agent do, and when." The hash chain means I cannot convince myself that an entry was modified after the fact. And the chain head can be cryptographically anchored with `ocm-mcp audit-anchor`, so even wholesale rewrites of the log are detectable later.

---

## What OpenShift operators notice specifically

If you run OpenShift rather than vanilla Kubernetes, a few things are worth calling out.

**The namespace protections are OpenShift-aware.** The guardrail layer has an explicit deny list of protected namespaces: not just `kube-system` and `default`, but `openshift`, `openshift-config`, `openshift-monitoring`, `openshift-ingress`, `openshift-apiserver`, and the entire `openshift-*` prefix family. An agent proposal that targets any of these is rejected before it reaches Kyverno. There is no way for a misphrased request to land a ConfigMap in `openshift-etcd`.

**ManagedClusterInfo works across ROSA and HCP.** The `get_cluster_info` tool reads from `ManagedClusterInfo` on the hub - the extended inventory object that the ACM/MCE `multicloud-operators-foundation` add-on populates. For ROSA clusters and Hosted Control Planes (HyperShift), this gives you the OCP version, node count, and console URL without needing a spoke context. The agent can answer "what version is running on rosa-dublin-01" without ever touching the spoke's API server.

**HyperShift NodePools are first-class.** If you run HCP spokes, `list_hosted_clusters` and `list_node_pools` surface the full HyperShift object graph. I use this to monitor replica counts and upgrade status of NodePools across control-plane hosting clusters. The agent can describe a degraded NodePool and the HostedCluster conditions in one call - something that previously required cross-referencing three separate `oc get` outputs.

![OPENSHIFT FLEET MAP PLACEHOLDER](./images/03-openshift-fleet-map.png)
<!-- IMAGE 4: OPENSHIFT FLEET MAP
Prompt for ChatGPT image generation:
"A topology map of a multi-cluster OpenShift fleet managed by Open Cluster Management. A central 'Hub' node in the center labeled 'OCM Hub' with the OpenShift logo. Surrounding it: 4-5 cluster nodes of different types - on-premise clusters (server rack icon), ROSA cloud clusters (cloud icon with AWS symbol), HyperShift Hosted Control Plane clusters (nested box icon). Connecting lines show management relationships. Color code: on-prem clusters in dark teal, cloud clusters in blue, HCP clusters in purple. The hub has a shield icon indicating the MCP server guardrail layer. Background: dark space-like with subtle grid. Style: clean technical network diagram, flat design with slight glow effects on nodes."
-->

---

## Three things I did not expect

**1. I stopped dreading the "how many clusters have this version?" question.**

Before, answering version distribution across the fleet required iterating every cluster and parsing `ManagedCluster` status. Now it is a single query. The agent synthesises the `ClusterClaims` - version, platform, region - into a readable summary. I run this before every maintenance window.

**2. The cordon/uncordon workflow became the preferred way to gate maintenance.**

Before I started using the agent, my maintenance workflow was: update a label, update a placement, wait, verify. Now it is: ask the agent to propose a cordon, approve it with `ocm-mcp approve`, verify the Placement excluded the cluster, do the maintenance, then propose and approve the uncordon. Each step has a record. The audit log entry for the cordon includes my process identity and the stated reason. When someone asks "why was Frankfurt out of rotation for four days," the answer is one `get-audit-trail` call away.

**3. Policy compliance surfaced problems I did not know existed.**

The `list_policy_violations` tool reads from the OCM governance policy add-on. On my second day of use, it surfaced three non-compliant policy-cluster pairs I had not noticed in the dashboard. Two were stale label mismatches from a cluster rename three months ago. One was a genuine misconfiguration in a NetworkPolicy. My usual dashboard workflow was tuned to workload health, not policy compliance. The agent looks at both.

---

## What it does not do, and why that is the right call

The server does not expose `kubectl exec`, log reads from arbitrary namespaces, or `Secret` reads. There is no tool that can pull a running pod's environment variables, read a mounted kubeconfig, or exec a shell command on a node.

For an operator used to having all of these things in their terminal, this feels like a constraint. It is. But the constraint is load-bearing. The agent's value here comes entirely from the fact that you can hand it to a model without lying awake wondering if it will exec its way into a secret mount and exfiltrate a database password.

The tools that exist are the ones that can read cluster state and propose controlled writes. Everything else is simply absent from the tool surface - not disabled, not guarded, just not there. You cannot prompt your way to a capability that was never registered.

---

## Six months in: the honest balance sheet

**What got easier:** Morning fleet triage. Placement debugging. Maintenance-window choreography. Cross-cluster version queries. Policy compliance monitoring. Incident post-mortems - the audit log is genuinely useful here.

**What did not change:** The actual remediation work. When a workload is broken, the agent can tell me it is broken and propose a change to the Deployment spec. I still review the manifest, I still approve the token, and I still watch the rollout. The agent accelerates the diagnosis and drafting. The judgment and authorization stay with me.

**What I would do differently:** I would have enabled `OCM_MCP_AUDIT_ECHO=1` from day one. Streaming the audit log to stderr and forwarding it to the team's SIEM gives you a live feed of every agent action. I turned it on after the Frankfurt incident and found it immediately useful - not for catching the agent doing something wrong, but for building confidence in the team that the record is clean.

---

## Getting started on your own fleet

If you want to try this on your own OCM hub:

```bash
pip install ocm-mcp-server
ocm-mcp keygen
OCM_MCP_HUB_CONTEXT=your-hub-context ocm-mcp-server
```

The `keygen` command generates the Ed25519 keypair under `~/.ocm-mcp/`. The server needs read access to the hub (the RBAC manifest is in `deploy/rbac.yaml`). Point your MCP-capable client at the running server and start with `list_clusters` to confirm connectivity.

The full [demo](https://github.com/sandeepbazar/ocm-mcp-server/tree/main/demo) shows a real unedited `e2e-local.sh` run - refused writes and approved ones - if you want to see the approval flow end to end before running it yourself.

---

*Sandeep Bazar builds infrastructure tooling at the AI/cluster boundary. The server described here is open source at [github.com/sandeepbazar/ocm-mcp-server](https://github.com/sandeepbazar/ocm-mcp-server). Questions and issues welcome.*
