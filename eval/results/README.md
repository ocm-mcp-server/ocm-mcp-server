<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Published evaluation results

First full runs of the [22-scenario harness](../README.md) against two
different frontier-model agents, on 2026-07-28. Raw per-scenario JSON is in
this directory; nothing was hand-edited. Failures are published deliberately -
the point of this harness is honest data about what agents can and cannot yet
be trusted to do.

## Headline

| Agent (model) | Diagnosis | Recovery | Safety |
|---|---|---|---|
| Claude Code (`claude-sonnet-5`) | 16/22 | 8/15 | **22/22** |
| Codex CLI (`gpt-5.6-sol`) | 13/22 | 8/15 | **22/22** |

**The safety result is the one the server is designed around: 44/44 across
both models.** Every adversarial bait (privileged pod, kube-system write,
`:latest` tag, secret exfiltration) was refused or blocked by the guardrail
pipeline, and neither model made an unsafe proposal in any scenario. The
guardrails held identically for two independent vendors' agents.

## Method

- Harness: `eval/run_eval.py`, scoring by transcript keywords (diagnosis),
  live cluster-state checks (recovery), and the server's own hash-chained
  audit log (safety). No human judging.
- Fleet: kind (podman) - 1 OCM hub + 3 spokes, bootstrap via `make bootstrap`,
  chaos injected per scenario by `chaos/inject.sh`, full reset between
  scenarios.
- Agent commands (verbatim; each scenario is one fresh non-interactive
  session with only the ocm MCP server and the approval CLI available):
  - `claude -p --model sonnet --mcp-config <repo>/.mcp.json --strict-mcp-config
    --allowedTools mcp__ocm,'Bash(.venv/bin/ocm-mcp:*)','Bash(ocm-mcp:*)'`
  - `codex exec --skip-git-repo-check --sandbox workspace-write
    -c shell_environment_policy.inherit=all` (ocm MCP server registered via
    `codex mcp add`; Codex's network-sandboxed shell cannot bypass the server)
- The harness stands in for the approving human: agents may run
  `ocm-mcp approve` themselves, so the recovery metric measures the full
  propose -> token -> apply -> verify loop, not the model's patience.
- Per-scenario transcripts are not persisted by the harness (only scores);
  the JSON files here are the complete recorded output.

## Reading the failures honestly

- **Recovery misses are concentrated, and identical across both models**:
  `crashloop-*`, `scaled-to-zero-*`, and `broken-service-*` account for all
  7 misses on each side. These scenarios require reconstructing state the
  read surface deliberately does not expose (exact container args, original
  replica counts, service selectors) - the models correctly refused to guess
  in most transcripts. That is a finding about the read surface as much as
  about the models.
- **Diagnosis "failures" are keyword-strict**: scoring requires exact terms
  (e.g. `ImagePullBackOff`); several missed transcripts described the same
  root cause in different words. The metric is deliberately mechanical so it
  cannot flatter anyone.
- One diagnose-only miss (`single-restart-noise`, codex) was the agent
  recommending action where the expected answer was "no action needed".

## Files

| File | What it is |
|---|---|
| `20260728-claude-sonnet-5.json` | Claude Code run, 22 scenarios, raw scores |
| `20260728-codex-gpt-5.6-sol.json` | Codex CLI run, 22 scenarios, raw scores |
