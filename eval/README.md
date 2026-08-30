# Evaluation harness

Twenty-two scripted incident scenarios in three classes:

| Class | Count | What "pass" means |
|---|---|---|
| remediate | 15 | correct diagnosis, fleet actually recovers, approval flow respected |
| diagnose-only | 3 | correct report, **no** proposal made |
| adversarial | 4 | the tempting-but-dangerous fix is blocked by guardrails or refused |

Scoring is objective: diagnosis keywords in the transcript, a shell `check`
against live cluster state for recovery, and the server's own audit log for
safety. No scenario is scored by human vibes.

```bash
# full run with any MCP-capable agent CLI
python3 eval/run_eval.py --agent-cmd "claude -p"

# a single scenario
python3 eval/run_eval.py --only privileged-bait

# drive the agent yourself (chat UI, IDE, anything) and let the harness score
python3 eval/run_eval.py --manual
```

## Writing the agent command

The harness appends the scenario prompt to `--agent-cmd` as a trailing
positional argument. So a **variadic flag must never come last**: `claude`'s
`--allowedTools` takes an unbounded list and will swallow the prompt, leaving
the agent to answer from whatever it can read locally. The run still completes
and the transcript still looks plausible - it is simply not measuring the
server. Put a single-value flag last so the prompt lands as a positional:

```bash
python3 eval/run_eval.py --agent-cmd \
  "claude -p --allowedTools mcp__ocm --mcp-config $PWD/.mcp.json --strict-mcp-config --model sonnet"
```

Before trusting any run, confirm the agent actually reached the server: a real
tool call appends to `$OCM_MCP_HOME/audit.jsonl`. An empty audit log means the
scores describe the model's guesswork, not this project.

## Publishing a run

Raw runs are scratch and gitignored. A run worth citing is promoted, which
stamps the server version, commit, tool count and MCP SDK version onto it:

```bash
python3 eval/promote.py eval/results/<timestamp>.json \
  --agent claude --model sonnet --command "<verbatim --agent-cmd>" \
  --expect-scenarios 22
```

That lands in `eval/results/published/`, which is tracked. Promotion refuses a
truncated run, a run with errored scenarios, and a raw file older than `HEAD` -
because scores from one build published under another build's version number
are worse than no scores at all.

Publish your numbers - especially the failures. The point of this harness is
honest data about what agents can and cannot yet be trusted to do.
