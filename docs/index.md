# ocm-mcp-server

**AgentOps for Kubernetes fleets - done safely.**

An [MCP](https://modelcontextprotocol.io/) server that lets AI agents operate a
multi-cluster Kubernetes fleet through an
[Open Cluster Management](https://open-cluster-management.io/) hub, with four
guardrail layers between the model and your clusters. The agent never holds a
kubeconfig; every write is policy-checked, human-approved, and traced.

**[→ Get started on GitHub](https://github.com/sandeepbazar/ocm-mcp-server)**

## Documentation

- [Architecture](architecture.md) - the choke-point idea, components, and the
  design decisions worth arguing about
- [Guardrails](guardrails.md) - the four layers, deliberate absences, what we
  refuse to automate, and the threat model
- [Demo script](demo-script.md) - the 3-act live demo, timed, with fallbacks
- [Upstream notes](upstream-notes.md) - gaps found while building this and
  what we're raising with MCP, OCM, and Kyverno

## In one picture

```
agent ──typed MCP tools──▶ ocm-mcp-server ──▶ OCM hub ──▶ fleet
              │                  │                │
              │           static guardrails   Kyverno dry-run
              │           audit + tracing     human approval token
              └── approval token ◀── human    least-privilege RBAC
```

## Author

**Sandeep Bazar** - 
[LinkedIn](https://www.linkedin.com/in/sandeepbazar/) ·
[YouTube: Tech Horizon Hub](https://www.youtube.com/@techhorizonhub) ·
sponsorship & support via [LinkedIn](https://www.linkedin.com/in/sandeepbazar/)
