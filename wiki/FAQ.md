# 11. FAQ

## Which "OCM" is this?

**Open Cluster Management** (open-cluster-management.io), the CNCF multi-cluster
project. Not the OpenShift Cluster Manager, which shares the acronym. Red Hat
publishes a separate `ocm-mcp` container that manages OpenShift clusters through
the OpenShift Cluster Manager API; different system, same three letters. In this
project, OCM always means Open Cluster Management.

## How is this different from other OCM MCP servers?

[`yanmxa/multicluster-mcp-server`](https://github.com/yanmxa/multicluster-mcp-server)
also bridges agents to Open Cluster Management, and it is capability-first: it
can generate a kubeconfig bound to a ClusterRole (cluster-admin by default) and
run `kubectl` commands. That maximizes what the agent can do.

This project is the opposite trade-off, safety-first: no kubeconfig exposure, no
`kubectl`, a fixed and small tool surface, and mandatory policy plus human
approval on every write. Choose by how much you need to trust the agent and how
regulated your environment is.

## Does the agent ever have real cluster credentials?

No. The server holds the kubeconfig. The agent only calls typed tools. There is
no tool that hands out credentials, execs, or reads Secrets.

## What if the model ignores its instructions?

The safety does not live in the model's instructions. It lives in the four
guardrail layers, which are outside the prompt: static checks, Kyverno policy,
human approval tokens, and RBAC. The model can be as wrong as it likes; a
dangerous change still cannot reach a cluster. See
[Guardrails Deep Dive](Guardrails-Deep-Dive).

## Can it work without OCM?

The tool surface is OCM-specific (ManagedCluster, ManifestWork). The *pattern*
(static checks, policy dry-run, human token, RBAC) is not, and can be ported to
any declarative multi-cluster delivery API. OCM is the reference implementation.

## Does it only work with Claude?

No. It speaks standard MCP over stdio. Ready-made configs ship for Claude Code,
Codex CLI, and Gemini CLI, and any MCP-capable client works. See
[Getting Started](Getting-Started).

## What does it cost to run?

The server itself is a small Python process. The laptop fleet is free (kind).
For real fleets you already have the hub and clusters; this adds a process and a
ServiceAccount. There is no paid dependency.

## How do I get support?

Community help through [GitHub issues](https://github.com/ocm-mcp-server/ocm-mcp-server/issues).
Commercial support, deployment reviews, sponsored features, and talks:
[LinkedIn](https://www.linkedin.com/in/sandeepbazar/).

Back to [Home](Home).
