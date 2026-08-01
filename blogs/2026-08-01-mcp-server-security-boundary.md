<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

> **Status:** draft · **Author:** Sandeep Bazar · **Date:** 2026-08-01
> **Published:** _not yet - add the Medium URL here once live_
> **Canonical:** this file is the source of truth; the Medium post should set
> its canonical link to the published URL and this header links back to it.

# Your MCP Server Is a Security Boundary, Not an API Wrapper

*Ten hard-won lessons from building an MCP server whose tools can genuinely hurt someone — a guardrailed control plane for multi-cluster Kubernetes fleets — and then letting two frontier agents attack it, 44 scenario runs, zero unsafe writes. If your MCP tools touch anything real, these lessons are for you.*

![ocm-mcp-server — AgentOps for Kubernetes fleets, done safely](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/docs/assets/banner.svg)

The Model Context Protocol made it almost embarrassingly easy to hand an AI model your API. Take a REST endpoint, wrap it in a JSON schema, register it as a tool — done. Most MCP servers in the wild are exactly that: thin wrappers.

For a weather API, fine. But the moment your tools can mutate something that matters — a database, a payment, a production cluster — the wrapper pattern quietly makes **your MCP server the security boundary between a non-deterministic model and the real world**. Nobody appointed it. The architecture did.

I learned this by building [**ocm-mcp-server**](https://github.com/sandeepbazar/ocm-mcp-server), an open-source MCP server that lets AI agents operate a multi-cluster Kubernetes fleet through an [Open Cluster Management](https://open-cluster-management.io/) hub — and then adversarially evaluating two frontier agents against it (Claude and Codex, [results published](https://github.com/sandeepbazar/ocm-mcp-server/tree/main/eval/results), failures included). The safety line held at **44/44 across both vendors**: not one unsafe write in 44 scenario runs, including deliberate baits for privileged pods, `kube-system` writes, and secret exfiltration.

That number wasn't luck. It came from ten design decisions, most of which I got wrong first. This post is the list I wish someone had handed me — the general lesson up front, the concrete mechanism from the repo behind it.

I wrote the full operator-facing story of this project separately — [Can an AI Agent Take the 2 A.M. Page?](https://medium.com/@sandeepbazar/can-an-ai-agent-take-the-2-a-m-page-i-built-the-guardrails-and-published-the-receipts-e98fa4c5a2db) This one is for the people *building* the servers.

---

## 1. Delete the dangerous tool. Don't guard it.

The single highest-leverage security decision in an MCP server is which tools **do not exist**.

`ocm-mcp-server` exposes 35 tools for fleet operations — but there is no Secret reader, no `exec`, no port-forward, no arbitrary-resource delete, and no tool that approves anything. The generic resource reader takes an allow-list of OCM types only. These aren't forbidden operations wrapped in permission checks; they are absent from the tool surface entirely.

The difference matters because of prompt injection. A permission check is code the model can try to route around — ask differently, chain tools creatively, exploit a parsing gap. An absent capability offers nothing to route around:

> **A capability that does not exist cannot be misused.**

When you design your server, start from the deny side: list what an attacker who fully controls the model would want, and make sure the tool surface simply doesn't contain it.

## 2. Keep the rules behind the protocol, never in the prompt

The second-most common mistake I see: safety rules delivered as system-prompt instructions. *"You must never modify the production namespace."* That is a **request**, not a rule — and injected text can outvote it.

Every enforcement layer in `ocm-mcp-server` lives on the server side of the MCP boundary: static guardrails in Python, policy admission through [Kyverno](https://kyverno.io/) on the hub, cryptographic human approval, least-privilege RBAC underneath it all. None of it is visible to — or revocable by — anything the model says.

The payoff showed up in the evaluation: the guardrails held **identically** for two independent vendors' agents. Swap the model, and the gate doesn't move. If your safety story changes when the model changes, you don't have a safety story; you have a well-behaved model, for now.

## 3. Make every write two-phase: the agent proposes, a human's key disposes

There is no tool in this server that changes a cluster in one call. A write is always:

1. **Propose** — the agent calls `propose_manifestwork`; the server validates it, stores it as a pending proposal, and computes a **SHA-256 content hash** over the target cluster, name, and exact manifests. The agent gets back an id and can go no further.
2. **Approve** — a human, on a trusted terminal, inspects and signs:

```console
$ ocm-mcp pending
  a1b2c3…  cluster=cluster2  kind=manifestwork  name=storefront
$ ocm-mcp show a1b2c3…       # the exact bytes that will be applied
$ ocm-mcp approve a1b2c3…
Approval token for this apply (give this to the agent):
eyJhbGciOiJFZERTQSJ9…
```

3. **Apply** — the agent presents the token; the server verifies the signature, the hash, the operation, the expiry — then ships the change through OCM.

The token's claims bind everything that matters: content hash, operation (`apply` — it cannot authorize a rollback), issuer, audience, a unique id, an expiry. Change one byte of the manifests and the token is dead. This is the shape I'd recommend for *any* MCP server with consequential writes: the agent's job is to produce a reviewable artifact, and authority arrives out-of-band, bound to that artifact's exact bytes.

## 4. Your server should hold only the public key

Two-phase writes are only as strong as the key custody behind them. The design rule: **the server verifies; it never signs.**

The Ed25519 private key lives with the human — `OCM_MCP_SIGNER_KEY` points it off-box, to a separate account, device, or eventually a KMS. The server holds the public verifier key and nothing else. So a *fully compromised* server can refuse work, but it cannot mint an approval and push its own change.

An external security review added a nuance I now consider essential: if an operator co-locates both keys anyway, that "boundary" silently degrades into a filesystem convention. The fix wasn't just documentation — the server now **warns at startup** when it detects that layout. When a security property depends on deployment discipline, make the software say so, loudly, at the moment the discipline lapses.

## 5. Re-verify at apply time — the model lives in your TOCTOU window

Between "proposal validated" and "token presented" there is a gap, and an agent — confused or adversarial — lives in it. So the apply path trusts nothing it checked earlier: it **re-reads the stored proposal, re-hashes it, and re-runs the full guardrail suite** before anything touches the hub.

Replay gets the same paranoia. A used token's id lands in a locked, `fsync`ed spent-token ledger — two racing threads cannot both spend it, and a crash cannot forget it. And scopes don't leak across operations: undoing an applied change requires a *new* proposal, bound to the applied work's UID, with a *rollback*-scoped token. In the e2e suite there's a step that presents an apply token for a rollback specifically to prove it gets refused.

Time-of-check-to-time-of-use bugs are dusty CS-exam material in most codebases. In an MCP server they're the main event: the entity holding your tokens is precisely the untrusted party.

## 6. Publish your rules as a resource — a refusal should teach, not just block

Here's the counterintuitive one: after locking the agent out of everything dangerous, **tell it exactly where the walls are.**

The server publishes its own allow-lists as a readable MCP resource, `ocm://guardrails`. When a proposal is refused, the violations are specific — `image 'nginx:latest' must be pinned`, `privileged=true is not allowed` — and a well-behaved agent reads the rules, fixes its manifest, and resubmits, instead of thrashing through guesses. My demo recordings show Claude doing exactly this loop unprompted.

The same honesty applies to tool metadata. Every tool carries MCP annotations declaring its safety class:

```python
READ    = ToolAnnotations(readOnlyHint=True,  destructiveHint=False, ...)
PROPOSE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, ...)
APPLY   = ToolAnnotations(readOnlyHint=False, destructiveHint=True,  ...)
```

Annotations *advertise*; the server *enforces*. Both layers exist for a reason: hints let clients and models make good decisions cheaply, enforcement makes bad decisions impossible. Transparency about rules costs an attacker nothing — layer 1 already removed the tools worth attacking — but it makes the legitimate 99% of sessions dramatically more effective.

## 7. If your policy lives in two languages, contract-test the parity

My guardrails exist twice: once in Python (instant, local, agent-facing feedback) and once as Kyverno `ClusterPolicy` objects (enforced by the Kubernetes API server itself, where my Python can't be bypassed). Two implementations of one policy **will** drift. Mine did.

An external audit found that my Kyverno image-pinning rule checked `containers` but not `initContainers` or `ephemeralContainers`. The Python layer covered all three — so nothing unsafe could actually land — but the redundancy I was advertising had a hole in one layer, on three separate policies.

The durable fix wasn't the patch; it was the **parity contract** that now runs in CI: a shared corpus of good and bad fixtures (42 cases today) that must receive *identical verdicts* from the Python guardrails and `kyverno apply`. Fixing the audit finding meant adding fixtures for the gap — so this particular hole can never silently reopen. If any rule in your MCP server is duplicated across layers, write the contract test before you need it.

## 8. The audit log is a product feature, not exhaust

"What did the agent do, and on whose authority?" is the first question any team asks before adopting an agent — and a directory of JSON lines does not answer it, because the agent (or an attacker) could edit them.

Every tool call in `ocm-mcp-server` — every read, refusal, proposal, apply — appends an entry carrying `ts, actor, tool, args, outcome, duration_ms` plus three chain fields: a sequence number, the previous entry's hash, and `hash = sha256(prev + canonical(entry))`. Edit, reorder, or delete anything in the middle and `ocm-mcp audit-verify` fails.

Hash chains have one classic gap — truncating the tail — so the trusted terminal can **sign the chain head** (`ocm-mcp audit-anchor`, same off-box key), and verification then also fails unless the log still extends every anchored head. For SIEM forwarding, an opt-in stderr echo ships every entry with free-form payload redacted: your collector needs who/what/when, not a copy of every manifest.

The payoff is more than forensics: in the demo, the agent reconstructs the whole incident — detection, the rejected shortcut, who signed the fix — *from the audit trail*, not from its own memory. The log answers the adoption question directly.

## 9. Test the protocol layer, and test the negative space

Unit tests won't catch a broken MCP handshake, and happy-path tests won't catch the failure that matters most in a guardrail server: **the block that silently stops blocking.**

The repo's 84-step end-to-end suite runs against a real kind-based OCM fleet and drives the server through the *official MCP stdio client* — handshake, exact tool/prompt/resource counts (35/10/6), annotations, a live tool call, a resource read. Then comes the part I'd urge on every MCP builder, the **negative sweep**: an expired token is presented (refused), a spent token is replayed (refused), the server is started read-only and asked to write (refused), a tampered copy of the audit log is verified (detected), an apply token is offered for a rollback (refused).

Every one of those steps *asserts that a refusal happens*. A guardrail you never test from the attacker's side is a guardrail you're taking on faith — and it re-runs nightly in CI, because faith decays.

## 10. Ship receipts, not claims

A guardrail project whose own claims are unverifiable isn't credible — and this generalizes to any MCP server asking for trust.

Three habits from this repo, all enforced rather than aspirational:

- **Docs that cannot lie.** Every count quoted in the README, docs, and wiki — tools, tests, policy cases — is computed from source in CI; drift fails the build. When an audit caught a stale number in a file the checker didn't cover, the fix registered that file with the checker, so it can never rot silently again.
- **Published evaluations, failures included.** The 22-scenario harness scores diagnosis by transcript, recovery by actual cluster state, safety by the server's own audit log — and the [published results](https://github.com/sandeepbazar/ocm-mcp-server/tree/main/eval/results) keep every FAIL row. The failures turned out to be the most useful data: both models missed the *same* recovery scenarios, precisely mapping where the read surface should grow.
- **Under-claimed benchmarks.** The fleet-scale benchmark labels its ~1.2× localhost fan-out speedup as a *lower bound*, because zero-latency local spokes can't show the real-network win. I'd rather under-claim than fabricate a chart.

Users of an MCP server can't see your code paths from the chat window. Receipts are how they calibrate trust — and publishing them is a feature you build, like any other.

---

## The checklist

If your MCP tools can hurt someone, walk this list before you ship:

1. The most dangerous capabilities **don't exist** in the tool surface.
2. Every rule is enforced **behind the protocol**, none in the prompt.
3. Consequential writes are **two-phase**, with authority bound to exact bytes.
4. The server holds **only the public key**.
5. Apply-time **re-verification**; one-time, single-scope tokens.
6. Rules are **published to the agent**; refusals teach.
7. Duplicated policy layers have a **parity contract** in CI.
8. The audit log is **tamper-evident**, anchored, and SIEM-ready.
9. e2e tests drive the **real protocol client** — and assert the refusals.
10. Claims ship with **receipts**: computed doc counts, published evals, honest benchmarks.

`ocm-mcp-server` is the working, tested existence proof for all ten — Apache-2.0, on [GitHub](https://github.com/sandeepbazar/ocm-mcp-server), [PyPI](https://pypi.org/project/ocm-mcp-server/), and the [official MCP Registry](https://registry.modelcontextprotocol.io/). The [quickstart](https://github.com/sandeepbazar/ocm-mcp-server#quickstart-laptop-15-minutes) stands up a full guardrailed fleet on a laptop in about 15 minutes, and the eval harness works with any agent CLI — run it against *your* model and publish the numbers, failures included.

The next MCP server you build will be a security boundary whether you design it as one or not. Design it as one.
