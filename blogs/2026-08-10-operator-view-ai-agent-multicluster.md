<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!--
Status: draft
Published: (pending)
Canonical: (pending)
-->

# I Gave an AI Agent the Keys to 40 Kubernetes Clusters. Here Is What I Actually Do All Day Now.

*Not the security story. Not the architecture deep-dive. Just an honest account from the person sitting in front of the screen - what changed, what stayed the same, and the one incident that made me stop second-guessing the audit log.*

---

![HERO IMAGE PLACEHOLDER](./images/03-hero-operator-chair.png)
<!-- IMAGE 1: HERO
Prompt for ChatGPT image generation:
"A human operator sitting in a dimly lit operations center, facing a large curved monitor wall showing a live Kubernetes multi-cluster fleet map. Hexagonal cluster nodes glow in teal and blue. A chat interface on the right shows an AI assistant conversation. The operator's hand hovers over a physical hardware key on the desk. Calm authority, late night, cinematic. Photorealistic digital art, dark theme, teal and blue accent lighting. No text overlays."
-->

---

My pager went off at 2:47am last Tuesday.

By the time I had my laptop open - about ninety seconds - I already had the answer. Three clusters showing elevated pod restart counts, one degraded deployment in the `payments` namespace on `ocp-frankfurt-01`, root cause pointing at a memory limit that was too tight for the new release. No guessing. No grepping through YAML. Just a structured summary sitting in my AI assistant chat, ready before my coffee was.

Six months ago that same investigation would have taken me twenty minutes and a second terminal window.

This is not a post about AI being magical. It is a post about what actually changed for me - someone who runs 40 Kubernetes clusters across on-prem OpenShift, ROSA on AWS, and HyperShift Hosted Control Planes - after I wired an AI agent into Open Cluster Management through [ocm-mcp-server](https://github.com/sandeepbazar/ocm-mcp-server).

Spoiler: most of my job looks the same. But the parts that used to drain me quietly? Those are gone.

---

## The 2:47am thing is not the point

Everyone leads with the on-call story. I get it - it is dramatic. But the real change was not the 2:47am page.

It was the 9:15am Monday morning. The routine check. The "nothing is on fire but I need to know the state of everything" scan that used to eat the first thirty minutes of every day.

Before this setup, my morning looked like:

1. `clusteradm get clusters` - scroll, scroll, scroll
2. `kubectl get pods --all-namespaces` on three different hub contexts
3. Open the ACM dashboard, wait for it to load
4. Open another tab for policy violations
5. Open another tab for alerts
6. Try to hold all of it in my head at once

After:

1. Type "fleet health" in the chat
2. Read the summary for thirty seconds
3. Know exactly where to look

The underlying data is identical. The same hub API, the same cluster conditions, the same pod counts. What changed is that I stopped being the one who has to parse it. The agent calls `get_fleet_health`, `query_events`, and `list_policy_violations` and hands me something I can actually act on.

Thirty seconds versus thirty minutes. Every single morning.

![FLEET HEALTH BEFORE AFTER PLACEHOLDER](./images/03-fleet-health-before-after.png)
<!-- IMAGE 2: BEFORE/AFTER
Prompt for ChatGPT image generation:
"Split-screen illustration. LEFT: a stressed operator at a terminal, surrounded by walls of raw YAML and kubectl output on a dark screen, multiple browser tabs open, overwhelmed expression. RIGHT: the same operator looking calm and focused at a clean AI chat summary showing color-coded cluster health cards - green, amber, red - with clear bullet points. Label the panels 'Before' and 'After'. Dark background, teal and green accent colors. Flat editorial illustration style."
-->

---

## The placement debugging that used to ruin my Tuesdays

Every platform team has that one thing that eats time for no good reason. For me it was placement debugging.

Write a `Placement`. Check the `PlacementDecision`. Notice it picked the wrong clusters. Try to figure out which label selector is wrong. Adjust. Wait for reconciliation. Repeat. On a bad day, two hours gone.

Here is that same workflow now:

> **Me:** Why is `ocp-amsterdam-03` not getting workloads from the `production-eu` placement?
>
> **Agent:** `ocp-amsterdam-03` is excluded because it is cordoned. Taint `ocm-mcp-server.io/cordoned` was applied 4 days ago. The approval record shows the reason: "network instability during maintenance window, pending validation." No uncordon proposal exists. The other three clusters - `ocp-frankfurt-01`, `ocp-paris-02`, `rosa-dublin-01` - all match the `region=eu` and `environment=production` label requirements and are currently selected.
>
> **Me:** Can you propose uncordoning Amsterdam?
>
> **Agent:** Proposed - ID `prop-0089`. Summary: "Remove cordon from ocp-amsterdam-03; maintenance window resolved, NOC ticket OPS-4471 closed." Run `ocm-mcp approve prop-0089` to generate the approval token.

That last line is important. The agent proposes. I approve. I run `ocm-mcp approve prop-0089` from my own terminal - the one with the signing key on it. The token it generates is bound to that exact change on that exact cluster. It expires in an hour. Nothing moves without me saying so.

The agent does not have the key. The agent cannot approve anything. And that is precisely why I trust it with the proposals in the first place.

![APPROVAL FLOW PLACEHOLDER](./images/03-approval-flow-operator.png)
<!-- IMAGE 3: APPROVAL FLOW
Prompt for ChatGPT image generation:
"A clean four-stage flow diagram on a dark navy background. Stage 1: AI Agent with a robot icon and a document (proposal). Stage 2: Proposal Store with a locked safe/vault icon. Stage 3: Human Operator at a keyboard with a physical key icon - this stage is highlighted in amber/gold. Stage 4: OCM Hub with a Kubernetes helm wheel and cluster nodes. Arrows connect each stage. Arrow from Stage 2 to 3 labeled 'Human Review'. Arrow from Stage 3 to 4 labeled 'Signed Token'. Teal accents throughout, amber highlight on the human stage. Flat technical diagram, no shadows, clean labels."
-->

---

## The Frankfurt incident

Six weeks in, a deployment on `ocp-frankfurt-01` rolled back without warning. My stomach dropped. I had introduced a new actor into my environment three months earlier and now something had gone wrong.

I ran `ocm-mcp get-audit-trail --last 50`.

What came back was a hash-chained JSON log - every tool call the agent had made, with arguments, outcome, timestamp, and a SHA-256 hash linking each entry to the previous one. I could see exactly what happened and in what order. The agent had made three read calls in the window around the incident: `get_cluster_health`, `list_manifestworks`, `query_events`. No proposals. No applies. Nothing.

The rollback had a completely different cause. A resource quota that had been silently too tight for the new replica count. Nothing to do with the agent at all.

But here is what I took from that incident: the audit log was not a box I checked for compliance. It was the fastest debugging tool I had. Forty seconds from "what happened" to "the agent did not touch it." That is the kind of confidence that makes you stop second-guessing the tool and start using it properly.

The hash chain matters here. I cannot edit an entry after the fact. I cannot convince myself something did or did not happen. The record is the record. And if you run `ocm-mcp audit-anchor` from your terminal after a significant change, the chain head gets cryptographically signed - so even if someone tried to rewrite the whole log file, you would know.

---

## If you run OpenShift, a few things are specifically yours

I have seen people assume this only works for vanilla Kubernetes. It does not. Here is what is different if you run OpenShift or ROSA.

**The guardrails know about OpenShift namespaces.** The deny list covers `openshift`, `openshift-config`, `openshift-monitoring`, `openshift-ingress`, `openshift-apiserver`, and the entire `openshift-*` prefix. An agent cannot write into any of those namespaces - not through a misphrased prompt, not through a crafted manifest, not at all. The rejection happens before Kyverno even sees the proposal.

**ROSA and HCP clusters work without spoke credentials.** `get_cluster_info` reads from `ManagedClusterInfo` on the hub - the ACM/MCE extended inventory object. For ROSA clusters and HyperShift Hosted Control Planes, it gives you the OCP version, node count, and console URL without the agent ever touching the spoke's API server. This is a bigger deal than it sounds. Spoke credentials never leave the hub boundary.

**HyperShift NodePools are proper first-class objects.** `list_hosted_clusters` and `list_node_pools` give you the full HyperShift object graph. I monitor NodePool replica counts and upgrade status across all my hosting clusters in a single call. Previously that was three different `oc get` commands cross-referenced by hand.

![OPENSHIFT FLEET MAP PLACEHOLDER](./images/03-openshift-fleet-map.png)
<!-- IMAGE 4: OPENSHIFT FLEET MAP
Prompt for ChatGPT image generation:
"A network topology diagram showing a multi-cluster OpenShift fleet. Central node labeled 'OCM Hub' with an OpenShift logo and a shield icon. Connected to 5 cluster nodes: 2 on-premise OpenShift clusters (server rack icons, dark teal), 2 ROSA cloud clusters (cloud with AWS symbol, blue), 1 HyperShift HCP cluster (nested box icon, purple). Connecting lines show hub-to-cluster management. Dark space-like background with a subtle grid. Slight glow on nodes. Clean flat technical diagram style."
-->

---

## Three surprises

I expected the fleet health thing. I did not expect these.

**Version queries stopped being a production blocker.** Before every maintenance window I need to know what version is running on every cluster and which ones are eligible for the upgrade path. That used to take fifteen minutes of `clusteradm` and `kubectl` output parsing. Now it is: "what versions are running across the fleet?" The agent reads the `ClusterClaims` across all clusters and gives me a clean breakdown. Thirty seconds. I do this every week now.

**Cordon/uncordon became my standard maintenance gate.** My old workflow was: update labels, update placement, wait, verify, document somewhere. My new workflow is: ask the agent to propose a cordon with a stated reason, approve it, let it land, do the maintenance, propose the uncordon, approve that too. Every step is in the audit log with timestamps and stated reasons. The next time someone asks why Frankfurt was out of rotation for four days, I do not have to dig through Slack or Confluence. I run `get-audit-trail` and the answer is right there.

**Policy violations surfaced things I had missed.** On day two of using `list_policy_violations` properly, it showed me three non-compliant cluster-policy pairs I had not noticed. Two were stale label mismatches from a cluster rename three months earlier. One was a live misconfiguration in a NetworkPolicy. My dashboard was tuned to workload health. The agent does not make that distinction.

---

## The things it deliberately cannot do

No `kubectl exec`. No reading logs from arbitrary namespaces. No `Secret` reads. No shell access to nodes. If you ask the agent to pull environment variables from a running pod, it cannot. If you ask it to check what credentials are mounted in a deployment, it cannot. The tools do not exist.

I know that sounds like a limitation. From a security standpoint it is actually the whole point. The surface area is small enough that I can reason about it. I handed this thing access to forty clusters. The reason I sleep fine about that is because I know exactly what it can and cannot reach - and "everything I would not want a misbehaving model to touch" is firmly in the cannot column.

You cannot prompt your way to a capability that was never registered. That is not a guardrail. That is an absence.

---

## What actually changed vs what stayed the same

**Changed:**
- Morning fleet triage (30 minutes down to 90 seconds)
- Placement debugging (hours down to minutes)
- Maintenance-window coordination (manual, fragile process to audited, reproducible workflow)
- Version distribution queries (manual parsing to instant)
- Policy compliance (invisible to surfaced and actionable)
- Post-incident review (memory-dependent to log-backed)

**Stayed the same:**
- Every remediation decision is still mine
- Every write still needs my signed approval token
- Deep log dives and exec sessions still happen in my terminal
- The thing that is broken still needs a human to fix it

The agent is not a replacement. It is the part of the job that used to be parsing, now handed to something that is very good at parsing.

---

## Getting started

```bash
pip install ocm-mcp-server
ocm-mcp keygen
OCM_MCP_HUB_CONTEXT=your-hub-context ocm-mcp-server
```

`keygen` generates the Ed25519 keypair under `~/.ocm-mcp/`. The server needs read access to the hub - the RBAC manifest is in `deploy/rbac.yaml`. Point your MCP client at it and start with `list_clusters` to confirm things are working.

One thing I wish I had done from day one: set `OCM_MCP_AUDIT_ECHO=1`. It streams every audit entry to stderr so your log collector picks it up. I turned it on after the Frankfurt incident. I have not turned it off.

The [demo](https://github.com/sandeepbazar/ocm-mcp-server/tree/main/demo) is a real, unedited end-to-end run - refused writes, approved writes, the full approval flow. Worth watching before you wire this into a production hub.

---

*Sandeep Bazar ships infrastructure tooling at the AI/cluster boundary. Everything described here is open source at [github.com/sandeepbazar/ocm-mcp-server](https://github.com/sandeepbazar/ocm-mcp-server).*
