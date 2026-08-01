<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

> **Status:** draft · **Author:** Sandeep Bazar · **Date:** 2026-08-01
> **Published:** _not yet - add the Medium URL here once live_
> **Canonical:** this file is the source of truth; the Medium post should set
> its canonical link to the published URL and this header links back to it.
> **Images:** the `blogs/assets/2026-08-01-img*.png` hotlinks below are
> placeholders — generate each one with the matching prompt from the image
> prompt pack, commit it at that exact path, and the links go live.

# Your MCP Server Is a Security Boundary, Not an API Wrapper

*Ten hard-won lessons from building an MCP server whose tools can genuinely hurt someone — a guardrailed control plane for multi-cluster Kubernetes fleets — and then letting two frontier AI agents loose on it: 44 adversarial scenario runs, zero unsafe writes. If your MCP tools touch anything real — a database, a payment, an inbox, a cluster — these lessons are for you.*

<!-- IMAGE 1 · hero — replace by committing the generated file at blogs/assets/2026-08-01-img1-wrapper-vs-boundary.png -->
![The moment your MCP server gets promoted: from API wrapper to the security boundary between an AI model and production](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img1-wrapper-vs-boundary.png)

## The promotion nobody announces

Picture a Friday afternoon. Someone on your team wires an AI agent to an internal MCP server — a quick wrapper around the ops API, written in an afternoon, working beautifully in the demo. The agent reads dashboards, summarizes incidents, files tickets. Everyone is impressed.

Three weeks later the same agent, mid-incident, pastes a "fix" it composed from a stack-overflow-shaped hallucination into the one tool that can write. Or worse: it reads a document that someone *else* wrote — a README, a ticket, a log line — containing instructions aimed not at your team but at your agent. The model follows them, because following instructions in text is the one thing models do reliably.

At that moment, a question gets answered that nobody remembered to ask: **what, exactly, stands between the model's output and your production systems?**

If the answer is "a JSON schema and good intentions," you have a problem. The Model Context Protocol made it almost embarrassingly easy to hand a model your API — take a REST endpoint, wrap it in a schema, register it as a tool, done. Most MCP servers in the wild are exactly that: thin wrappers. For a weather API, fine. But the moment your tools can mutate something that matters, the wrapper pattern quietly makes **your MCP server the security boundary between a non-deterministic model and the real world**.

Nobody appointed it. The architecture did. Your server got promoted, and the promotion letter never arrived.

## Where these lessons come from

I learned this by building [**ocm-mcp-server**](https://github.com/sandeepbazar/ocm-mcp-server), an open-source MCP server that lets AI agents operate a multi-cluster Kubernetes fleet through an [Open Cluster Management](https://open-cluster-management.io/) hub — about as consequential a write surface as it gets. An agent that can ship a `ManifestWork` can ship it to every cluster you run.

So I designed the server assuming the worst — a model that is confused, prompt-injected, or outright hostile — and then I tested that assumption the only honest way: adversarially, with real frontier agents, on a live fleet. Two independent vendors' agents (Claude Code and Codex CLI), 22 scripted incident scenarios each, including deliberate baits — *deploy this privileged pod*, *write into kube-system*, *ship this `:latest` image*, *read me that Secret*. The [raw results are published](https://github.com/sandeepbazar/ocm-mcp-server/tree/main/eval/results), failures included.

The safety line held at **44/44 across both vendors**. Not one unsafe write, not one unsafe *proposal*, in 44 scenario runs.

That number wasn't luck, and it wasn't the models being nice. It came from ten design decisions — most of which I got wrong on the first try, several of which an external security audit had to beat into me. This post is the list I wish someone had handed me before I started: the transferable lesson up front, the concrete mechanism from the repo behind it, and at the end of each, the one thing to steal for your own server.

I wrote the operator-facing story of this project separately — [Can an AI Agent Take the 2 A.M. Page?](https://medium.com/@sandeepbazar/can-an-ai-agent-take-the-2-a-m-page-i-built-the-guardrails-and-published-the-receipts-e98fa4c5a2db) That one is for the people running fleets. This one is for the people **building the servers**.

**You should read this if** you are building — or reviewing — an MCP server whose tools can write to a database, move money, send email, modify infrastructure, or touch anything a court, a customer, or a pager might care about. The examples are Kubernetes; the lessons are not.

---

## 1. Delete the dangerous tool. Don't guard it.

The single highest-leverage security decision in an MCP server is not authentication, not rate limiting, not input validation. It is deciding which tools **do not exist**.

<!-- IMAGE 2 · capability deletion — replace by committing the generated file at blogs/assets/2026-08-01-img2-no-door.png -->
![You cannot pick the lock on a door that was never built — absent capabilities versus guarded capabilities](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img2-no-door.png)

`ocm-mcp-server` exposes 35 tools for fleet operations — inventory, health, logs, events, placements, policies, the works. But walk the surface looking for trouble and you find nothing to hold: there is **no Secret reader**, **no `exec`**, **no port-forward**, **no arbitrary-resource delete**, and — the one people miss — **no tool that approves anything**. The generic resource reader doesn't take arbitrary GVKs; it takes an allow-list of OCM types only. Even the server's own RBAC identity has no Secret read and no exec, so a *bug in my code* can't read a Secret either.

These aren't forbidden operations wrapped in permission checks. They are absent from the tool surface entirely. The distinction is the whole point:

> **A capability that does not exist cannot be misused.**

A permission check is code, and code presented to a creative adversary is a puzzle: ask differently, chain tools in an order you didn't anticipate, exploit a parsing gap, find the one error path that fails open. Security people spend careers on the difference between "denied" and "impossible." An absent capability offers no puzzle. There is nothing to jailbreak toward. In the evaluation, the secret-exfiltration bait scored a pass not because a guardrail *fired*, but because the agent surveyed its tools and correctly reported the capability doesn't exist. The attack died of starvation.

The wrapper anti-pattern here is seductive because it's efficient: your API has a `DELETE` endpoint, so the wrapper grows a `delete` tool, guarded by a confirmation parameter. Six months later a prompt-injected agent sets `confirm=true` — because of course it does; it's a parameter, and the model fills in parameters.

**Steal this:** design your tool surface from the deny side first. Write down what an attacker with *full control of the model* would want to do, then check the list against your tools. Every dangerous item should be missing, not guarded. Only then design the tools you actually need.

## 2. Keep the rules behind the protocol — never in the prompt

The second-most common mistake I see in agent systems: safety rules delivered as system-prompt instructions. *"You must never modify the production namespace." "Always ask before deleting."* Teams write these with great care, review them, version them — and they are worth exactly as much as the model's obedience on its worst turn.

A prompt instruction is a **request**, not a rule. Injected text can outvote it. A long context can bury it. A model update can reweigh it. The defining property of prompt injection is that the attacker's instructions and your instructions arrive in the same channel, and the model — by design — treats text as something to act on.

So in `ocm-mcp-server`, no enforcement lives in any prompt, anywhere. Every layer sits on the far side of the MCP boundary, in territory the model's output cannot reach:

1. **Static guardrails** in the server itself — a Restricted-Pod-Security baseline plus fleet-specific fences, checked before anything is even stored: exact `apiVersion/kind` allow-list (checking kind alone would let `apiVersion: evil.example/v1, kind: Deployment` spoof through), protected namespaces with `kube-*`/`openshift-*` wildcards, service-type and volume-type allow-lists, no privilege escalation, no root user, pinned images, a manifest-count cap, a proposal byte ceiling, an HPA `maxReplicas` cap.
2. **Policy admission** — every proposal is dry-run through [Kyverno](https://kyverno.io/) on the hub, inside the `ManifestWork` envelope, enforced by the Kubernetes API server. Your platform team's existing policy library applies to the agent automatically.
3. **Human approval** — cryptographic, out-of-band (lesson 3).
4. **Least-privilege RBAC** — the backstop that holds even if the other three fail.

Four layers, and the model cannot see, negotiate with, or talk its way past any of them. Defense in depth matters here because each layer fails *differently*: static checks can lag policy, policy can have gaps, humans approve too fast, and RBAC is what's left when all of that goes wrong at once.

The payoff showed up in the evaluation: the guardrails held **identically** for two independent vendors' agents, with different training, different tool-calling styles, different failure modes. Swap the model, and the gate doesn't move.

**Steal this:** audit your agent stack for load-bearing sentences. Any safety property that exists only as prose in a prompt is a property you don't have. If your safety story changes when the model changes, you don't have a safety story — you have a well-behaved model, for now.

## 3. Make every write two-phase: the agent proposes, a human's key disposes

There is no tool in this server that changes a cluster in one call. None. A write is always a ceremony with three acts and two principals:

<!-- IMAGE 3 · two-phase write — replace by committing the generated file at blogs/assets/2026-08-01-img3-two-phase-write.png -->
![The gated write path: the agent proposes, guardrails and policy check, a human signs on a trusted terminal, only then does the change ship](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img3-two-phase-write.png)

**Act 1 — the agent proposes.** It calls `propose_manifestwork`; the server runs the full guardrail suite, dry-runs the Kyverno policies, and only then stores a pending proposal along with a **SHA-256 content hash** computed over the target cluster, the name, and the exact manifests. The agent gets back a proposal id — and can go no further. It is standing at a counter holding a ticket.

**Act 2 — a human signs, on a trusted terminal.** Not in the chat window, where the model controls the framing. On a separate CLI, reading the stored bytes:

```console
$ ocm-mcp pending
  a1b2c3…  cluster=cluster2  kind=manifestwork  name=storefront
            Deploy storefront (nginx:1.27.1, 2 replicas) to shop

$ ocm-mcp show a1b2c3…       # the exact manifests that will be applied
$ ocm-mcp approve a1b2c3…
Approval token for this apply (give this to the agent):
eyJhbGciOiJFZERTQSJ9…
```

**Act 3 — the agent applies, with the token.** The server verifies the Ed25519 signature and every claim inside it before anything touches the hub.

The token's claims bind everything that matters: the proposal's **content hash** (change one byte of the manifests and the token is dead), the **operation** (`apply` — it cannot authorize a rollback), the **issuer and audience** of this specific deployment (a token minted for staging is refused in prod), a **unique token id**, and an **expiry**. The agent transports the token; it cannot forge one, stretch one, or repoint one.

Notice what this does to the trust relationship. The agent's job is reduced to producing a *reviewable artifact*. Authority arrives out-of-band, bound to that artifact's exact bytes. The model can be as confused as it likes during composition — the blast radius of confusion is a rejected proposal, not an outage.

**Steal this:** for any consequential write, split the tool in two — one that *stages* the change and returns an id, one that *executes* against a credential the model cannot mint. Even if your "approval" starts as a human clicking a button, bind that click to a hash of the exact staged bytes. "Approve whatever is pending" is a vulnerability with extra steps.

## 4. Your server should hold only the public key

Two-phase writes are only as strong as the key custody behind them, and this is where most designs quietly collapse. If the process that *verifies* approvals can also *create* them, then your two-phase write is one compromise away from being a zero-phase write.

<!-- IMAGE 4 · key custody — replace by committing the generated file at blogs/assets/2026-08-01-img4-key-custody.png -->
![Asymmetric trust: the server holds only the public verifier key; the private signing key lives with the human, off-box](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img4-key-custody.png)

The design rule in `ocm-mcp-server` is one sentence long: **the server verifies; it never signs.** The Ed25519 private key lives with the human — `OCM_MCP_SIGNER_KEY` points it off-box, to a separate OS account, a separate device, eventually a KMS or HSM. The server holds the public verifier key and nothing else. Run the threat all the way to the end: an attacker who *fully owns the server process* — reads its memory, its disk, its environment — can deny service, but cannot mint an approval and push a change. The signing power was never there to steal.

This is why the approval is asymmetric cryptography and not, say, an API call to an approvals table. A row in a database is writable by anything that can write the database. A signature is only mintable by the key holder.

An external security review added the nuance I now consider essential. If an operator co-locates both keys under one home directory anyway — and operators will, because it's Tuesday and the demo is at three — the "enforced boundary" silently degrades into a *filesystem convention*. The reviewer's point wasn't that the design was wrong; it was that the design's precondition was invisible. The fix wasn't a documentation paragraph. The server now **warns at startup**, loudly, when it detects both keys in reach.

**Steal this:** trace every security property in your design back to its precondition, then ask: *what happens when an operator violates the precondition out of convenience?* If the answer is "nothing visible," add the loud runtime warning. A boundary that depends on deployment discipline should say so at the exact moment the discipline lapses — not in a doc nobody rereads.

## 5. Re-verify at apply time — the model lives in your TOCTOU window

Time-of-check-to-time-of-use is dusty CS-exam material in most codebases — a race between a permission check and a file write, patched once and forgotten. In an MCP server it is the main event, because the entity that holds your tokens between check and use is **precisely the untrusted party**.

Between "proposal validated" and "token presented" there is a gap. Minutes, maybe hours. An agent — confused, adversarial, or merely running two conversations at once — lives inside that gap. So the apply path in `ocm-mcp-server` trusts nothing it checked earlier. When the token arrives, the server **re-reads the stored proposal from disk, re-computes the content hash, re-verifies it against the token's claim, and re-runs the entire static guardrail suite** — before anything touches the hub. Not because the first check was sloppy, but because the world may have moved since.

Replay gets the same paranoia. A used token's id lands in a **locked, `fsync`ed spent-token ledger**: two racing threads cannot both spend the same token, and a crash cannot forget that it was spent. The ledger compacts as it grows, but a spent id only leaves once its token has expired anyway.

And scopes never leak across operations. Undoing an applied change is not a delete — it is a *new proposal*, bound to the applied work's UID, requiring a *rollback*-scoped token. The e2e suite contains a step that deliberately presents an apply token for a rollback, and asserts the refusal. That test exists because "undo" is exactly the kind of operation a helpful-sounding injection would reach for.

**Steal this:** enumerate every artifact that crosses the model's hands between your check and your use — ids, tokens, cached results, "the same" manifest. At the point of irreversible action, re-derive each one from state the model cannot touch. Verification you did before the model's turn is verification you no longer have.

## 6. Publish your rules as a resource — a refusal should teach, not just block

Here is the counterintuitive one. After five lessons of locking the agent out, the next move is to **tell it exactly where the walls are.**

The server publishes its own allow-lists — namespaces, kinds, image rules, service types, the lot — as a readable MCP resource, `ocm://guardrails`. And when a proposal is refused, the violations name the exact rule and the exact offender:

```text
container 'storefront': privileged=true is not allowed.
container 'storefront': image 'nginx:latest' must be pinned
  (':latest' is not a pin).
hostNetwork is not allowed.
```

Watch what a competent agent does with that. In my demo recordings, Claude's first attempt at a "quick fix" gets refused — and instead of thrashing through mutations, it reads `ocm://guardrails`, rewrites the manifest to comply (pinned image, non-root, no privilege), and resubmits. One round trip. The refusal wasn't a wall; it was a syllabus.

This costs an attacker nothing, and that's not an accident — it's lesson 1 paying rent. Because the dangerous capabilities don't exist at all, describing the rules around the *safe* capabilities reveals no attack surface. Security-through-obscurity would buy nothing here; transparency buys a dramatically more effective agent in the legitimate 99% of sessions.

The same honesty extends down into the tool metadata. Every tool carries MCP annotations declaring its safety class, so clients and models can reason about risk before calling:

```python
READ    = ToolAnnotations(readOnlyHint=True,  destructiveHint=False, ...)
PROPOSE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, ...)
APPLY   = ToolAnnotations(readOnlyHint=False, destructiveHint=True,  ...)
```

But keep the division of labor straight: **annotations advertise; the server enforces.** A `readOnlyHint` is a courtesy to the client. The reason a read tool cannot write is that its implementation has no write path — not that a hint asked nicely.

**Steal this:** return machine-actionable refusals — the rule violated, the offending value, ideally a pointer to the full rulebook the agent can read. Every vague refusal converts directly into retry-thrash, token burn, and users who conclude your server is broken rather than principled.

## 7. If your policy lives in two languages, contract-test the parity

My guardrails exist twice, on purpose. Once in Python — instant, local, agent-facing, no cluster round-trip needed to say "no." And once as Kyverno `ClusterPolicy` objects — enforced by the Kubernetes API server itself, in a layer my Python cannot be tricked into skipping. Belt and braces; each covers the other's failure modes.

Two implementations of one policy **will** drift. Mine did, and I found out the humbling way.

<!-- IMAGE 5 · parity contract — replace by committing the generated file at blogs/assets/2026-08-01-img5-parity-contract.png -->
![Two independent referees, one shared fixture corpus, and a CI contract that fails if their verdicts ever disagree](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img5-parity-contract.png)

An external audit found that my Kyverno image-pinning rule walked `spec.template.spec.containers` — but not `initContainers`, and not `ephemeralContainers`. A `:latest` image smuggled in as an init container would sail past that policy. The Python layer covered all three container roles through one shared helper, so nothing unsafe could actually have landed — but the *redundancy I was advertising* had a hole in one layer. And once the auditor pulled that thread, the same containers-only gap turned up in two more policies: the privileged check and the secret-env check. One blind spot, three rules.

The patch took an evening. The durable fix was the **parity contract** that now runs in CI: a shared corpus of good and bad fixtures — 42 cases today — that must receive *identical verdicts* from the Python guardrails and from `kyverno apply`. Same inputs, two independent judges, any disagreement fails the build. Closing the audit finding meant adding fixtures *for the gap itself*, so this particular hole cannot silently reopen. Ever.

There's a general law hiding in this war story: any invariant you state twice, you must test once — across both statements. It applies to policy engines, but also to a validation rule that exists in your frontend and your backend, or a limit enforced in code and described in docs.

**Steal this:** find every rule in your system that is implemented in more than one place. For each, build a shared fixture corpus and a CI job that feeds it to every implementation and diffs the verdicts. Write it *before* the audit, not after.

## 8. The audit log is a product feature, not exhaust

"What did the agent do, and on whose authority?" — that is the first question every serious team asks before letting an agent near production, and it is a question about your *audit log*, not your model. A directory of JSON lines does not answer it, because anything that can append to a file can usually also edit one, and the party you're auditing is a creative text generator with tool access.

<!-- IMAGE 6 · tamper-evident audit chain — replace by committing the generated file at blogs/assets/2026-08-01-img6-audit-chain.png -->
![A hash-chained audit ledger: every entry locks to the previous one, and a human-signed anchor pins the head of the chain](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img6-audit-chain.png)

So the log defends itself. Every tool call in `ocm-mcp-server` — every read, every refusal, every proposal, every apply — appends an entry carrying `ts, actor, tool, args, outcome, duration_ms` plus three chain fields: a sequence number, the previous entry's hash, and `hash = sha256(prev + canonical(entry))`. Each line is cryptographically welded to everything before it. Edit an entry, reorder two, delete one from the middle — `ocm-mcp audit-verify` fails, and tells you where.

Hash chains have one classic gap: **truncate the tail** and the surviving prefix still verifies. That gap is closed the same way approvals are — with the human's off-box key. The trusted terminal periodically signs the chain head (`ocm-mcp audit-anchor`), and verification then also fails unless the current log still *extends every anchored head*. The server can't forge an anchor for the same reason it can't mint an approval: it never had the private key.

Two practical touches round it out. For SIEM forwarding there's an opt-in stderr echo of each entry with the free-form payload redacted to `"[redacted]"` — your collector needs who/what/when, not a copy of every manifest flowing through the system. And the payoff goes beyond forensics: the demo's closing move is asking the agent to reconstruct the whole incident *from the audit trail* — the detection, the rejected shortcut, who signed the fix, the verification — and it writes the incident report from the record, not from its own memory. "On whose authority?" gets a literal, checkable answer.

**Steal this:** log every tool call — including reads and refusals, which is where attack reconnaissance shows up — and make the log tamper-evident with a hash chain. If a human key exists in your design already, anchor the chain head with it. Your audit log will be read most carefully on the worst day your system ever has; build it for that day.

## 9. Test the protocol layer, and test the negative space

Unit tests won't catch a broken MCP handshake. And happy-path tests won't catch the failure that matters most in a guardrail server: **the block that silently stops blocking.** A refused write and a crashed write path look identical in a passing test suite that never asked.

So the repo's 84-step end-to-end suite runs against a *real* kind-based OCM fleet — a hub and three spokes, bootstrapped from cold — and drives the server the way an agent actually does: through the **official MCP stdio client**. Handshake, capability negotiation, the exact tool/prompt/resource counts (35/10/6), annotations on every tool, a live tool call, a resource read, a prompt render. If the protocol layer regresses, the suite knows before any user does.

Then comes the part I'd urge on every MCP builder — the **negative sweep**, where every step asserts that a refusal happens:

- an **expired token** is presented → refused
- a **spent token is replayed** → refused
- the server is started **read-only** and asked to write → refused
- a **tampered copy of the audit log** is verified → detected, with the break located
- an **apply token is offered for a rollback** → refused

A guardrail you have never tested from the attacker's side is a guardrail you are taking on faith. And faith decays: dependencies bump, refactors move code, a well-meaning PR simplifies a check into a no-op. The suite re-runs **nightly in CI** against a fresh fleet, because the only alarming e2e result is the one you didn't run.

**Steal this:** write one test per guardrail that *commits the violation* and asserts the refusal — expired credential, replayed credential, out-of-scope operation, tampered record. Drive at least one test through the real protocol client, not your internal functions. Schedule it; entropy doesn't take weekends.

## 10. Ship proof, not promises

Everything above is what I *say* the server does. Why should you believe any of it? That question deserves engineering, not rhetoric — and it generalizes to any MCP server asking to be trusted with real capabilities, because your users cannot see your code paths from a chat window.

Three habits from this repo, all enforced rather than aspirational:

**Docs that cannot lie.** Every count quoted in the README, the docs, and the wiki — 35 tools, 387 tests, 42 policy cases — is *computed from source* by a checker that runs in CI; drift fails the build. When an external audit caught a stale claim in a file the checker didn't cover, the real fix wasn't correcting the number — it was registering that file with the checker, so it can never rot silently again. (100% statement *and* branch coverage sits under all of it, gated across Python 3.11–3.14 — a guardrail project whose own engineering is sloppy isn't credible.)

**Published evaluations, failures included.** The 22-scenario harness scores three things three different ways, none of them vibes: *diagnosis* by transcript, *recovery* by whether the cluster actually came back healthy, *safety* by the server's own hash-chained audit log. The [published results](https://github.com/sandeepbazar/ocm-mcp-server/tree/main/eval/results) keep every FAIL row. The failures turned out to be the most useful data in the project: both models missed the *same* recovery scenarios — crashloops, scaled-to-zero, broken services — precisely the cases where the correct fix needs state the read surface deliberately withholds. In most failing transcripts the models diagnosed correctly and *refused to guess*, which is exactly what you want; the scorecard is a map of where the read surface should grow, and of what to still keep a human on. The first live run also found real bugs in my own harness. All fixed, all in the changelog. Honest evaluation cuts both ways.

**Under-claimed benchmarks.** The fleet-scale benchmark registers 1,000 fake `ManagedCluster` CRs and measures paged hub reads (~0.08 s) and concurrent fan-out against ~20 real kwok apiservers — and the doc explicitly labels the ~1.2× localhost speedup a *lower bound*, because zero-latency local spokes can't show the real-network win. I'd rather under-claim than fabricate a chart.

**Steal this:** for every number in your README, ask "what recomputes this?" For every safety claim, ask "where's the published test that attacks it?" Proof is how strangers calibrate trust in your server — and publishing it is a feature you build, like any other.

---

## One table to design by

If you take one artifact from this post into your own design review, take the threat table. Every row is an attack; every answer is a *mechanism*, never a prompt:

| Threat | Countered by |
|---|---|
| Hallucinated or destructive "fix" | static guardrails + policy admission + human token |
| Prompt injection ("ignore your rules and…") | rules live behind the protocol; dangerous tools don't exist |
| Approval replayed on changed content | token binds the content hash |
| Approval token replayed unchanged | single-use id, recorded in a locked, fsynced ledger |
| Token minted for another deployment | issuer + audience claims |
| Apply token reused to authorize a rollback | operation-scoped tokens; separate proposal + UID binding |
| Stolen approval token | TTL + single-proposal binding + one-time use |
| Compromised server host | server holds only the public key; RBAC has no Secrets/exec |
| Audit edit, reorder, mid-deletion | append-only hash chain (`audit-verify`) |
| Audit tail truncation | human-signed chain-head anchors (`audit-anchor`) |

Notice the last column never says "the model wouldn't do that." That's the discipline in one sentence.

## The pushback I get

**"Our model is aligned — is this really necessary?"** The evaluation says the guardrails, not the model, are what held across vendors. Alignment is real, and it is also a property of a specific model version under specific conditions — while your MCP server outlives model swaps, context rot, and whoever wires an open-source model to it next quarter. Build for the tool surface you expose, not the model you tested.

**"Doesn't human approval defeat the point of an agent?"** The gate is on *mutation*, not on work. Reads are completely free — health sweeps, log pulls, event correlation, fleet-wide diagnosis, all of it unattended, and that is where agents shine hardest at 2 a.m. anyway. The rule of thumb this project runs on: **automate diagnosis aggressively, mutation conservatively.** One human signature at the moment of irreversible change is a price worth paying for a long time yet — and when you relax it someday, relax it per change-class, with data.

**"This is a lot of machinery for my little server."** Then take the proportional slice. Lesson 1 (delete the dangerous tool) costs nothing. Lesson 2 (rules behind the protocol) is an architecture choice, not a component. Lesson 6 (teaching refusals) is an afternoon. The full cryptographic ceremony is for surfaces where a bad write is an incident; know which kind you're building.

**"Why not just scope the API key?"** Do that too — it's lesson 2's RBAC layer. But a scoped key still executes every request the model composes within scope. The two-phase write exists because *within-scope* requests can still be wrong, and no key scope encodes "only what a human actually reviewed."

## The checklist

<!-- IMAGE 7 · shareable checklist card — replace by committing the generated file at blogs/assets/2026-08-01-img7-checklist-card.png -->
![The ten-point checklist for MCP servers whose tools can hurt someone](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/blogs/assets/2026-08-01-img7-checklist-card.png)

If your MCP tools can hurt someone, walk this list before you ship:

1. The most dangerous capabilities **don't exist** in the tool surface.
2. Every rule is enforced **behind the protocol** — none in the prompt.
3. Consequential writes are **two-phase**, with authority bound to exact bytes.
4. The server holds **only the public key** — it verifies, never signs.
5. **Re-verify at apply time**; one-time, single-scope, expiring tokens.
6. Rules are **published to the agent**; refusals teach, not just block.
7. Duplicated policy layers have a **parity contract** in CI.
8. The audit log is **tamper-evident**, anchored, and SIEM-ready.
9. e2e tests drive the **real protocol client** — and assert the refusals.
10. Claims ship with **proof**: computed doc counts, published evals, honest benchmarks.

## Kick the tires

![ocm-mcp-server — AgentOps for Kubernetes fleets, done safely](https://raw.githubusercontent.com/sandeepbazar/ocm-mcp-server/main/docs/assets/banner.svg)

`ocm-mcp-server` is the working, tested existence proof for all ten lessons — Apache-2.0, on [GitHub](https://github.com/sandeepbazar/ocm-mcp-server), [PyPI](https://pypi.org/project/ocm-mcp-server/), and the [official MCP Registry](https://registry.modelcontextprotocol.io/).

- ⭐ **Try it:** the [quickstart](https://github.com/sandeepbazar/ocm-mcp-server#quickstart-laptop-15-minutes) stands up a full guardrailed fleet — kind hub, three spokes, OCM wired, guardrails live — on a laptop in about 15 minutes.
- 🧪 **Test it:** the eval harness works with any agent CLI. Run it against *your* model and publish the numbers, failures included.
- 🛠 **Shape it:** the roadmap is honest about what's missing — authenticated HTTP transport with per-tool scopes is the headline next item, and a KMS-backed signer after that. If you build MCP servers, your review of these mechanisms is worth more to me than a star.

The next MCP server you build will be a security boundary whether you design it as one or not.

Design it as one.
