<!--
SPDX-FileCopyrightText: 2026 Sandeep Bazar
SPDX-License-Identifier: Apache-2.0
-->

# MCP client configs

Ready-made configuration for connecting an MCP client to `ocm-mcp-server`.
Copy the one for your client, change the two context variables, and you are
connected. Nothing here is vendor-specific — the server speaks standard MCP
over stdio.

| Client | File | Where it goes |
| --- | --- | --- |
| Claude Code | [`claude-code.mcp.json`](claude-code.mcp.json) | `.mcp.json` in your project, or `claude mcp add` |
| VS Code (Copilot Chat) | [`vscode-mcp.json`](vscode-mcp.json) | `.vscode/mcp.json` in your workspace |
| Codex CLI | [`codex-config.toml`](codex-config.toml) | `~/.codex/config.toml` |
| Gemini CLI | [`gemini-settings.json`](gemini-settings.json) | `~/.gemini/settings.json` |
| Anything else | [`generic-mcp.json`](generic-mcp.json) | wherever your client keeps MCP servers |

There is also [`system-prompt.md`](system-prompt.md): a production-shaped system
prompt that tells an agent how to behave against a real fleet — investigate
freely, propose rather than apply, and never try to route around a rejection.

## The two variables that matter

```jsonc
"OCM_MCP_HUB_CONTEXT": "kind-hub",
"OCM_MCP_SPOKE_CONTEXTS": "cluster1=kind-cluster1,cluster2=kind-cluster2"
```

The name on the **left** of each `=` must match a cluster as the hub knows it
(`kubectl --context <hub> get managedclusters`); the name on the **right** is a
context in your kubeconfig. Getting these the wrong way round is the single
most common setup mistake — [kubeconfig contexts](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/docs/kubeconfig-contexts.md)
walks through both.

Spoke contexts are optional. Without them the hub-side tools all work; the ones
that read from a spoke (`get_pod_logs`, `query_events`, spoke-side health) are
what need them.

## A note on VS Code

VS Code uses `"servers"` as the top-level key. Claude Code and Gemini CLI use
`"mcpServers"`. Copying one into the other's file fails **silently** — no error,
the server simply never appears — so use the file for your own client rather
than adapting a neighbour's.

## Verify the connection

```sh
ocm-mcp doctor
```

Runs the read path against your live hub and reports per-check status, so you
find a misconfigured context here rather than mid-incident. Full setup guide:
[deployment](https://github.com/sandeepbazar/ocm-mcp-server/blob/main/docs/deployment.md).
