# Security policy

This project's whole purpose is safety at the AI/infrastructure boundary, so
security reports get first-class attention.

## Reporting

Please report vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the repository's Security tab). Expect an
acknowledgement within a few days.

In scope, especially:

- any way for an MCP tool call to mutate cluster state without a valid
  approval token (approval bypass)
- approval-token forgery, replay against changed content, or TTL bypass
- static-guardrail or policy-evaluation bypasses (e.g. manifest shapes that
  smuggle privileged settings past `guardrails.py` or the Kyverno policies)
- privilege escalation beyond the RBAC in `deploy/rbac.yaml`
- audit-log evasion (tool calls that leave no audit line)

## Threat model

See [docs/guardrails.md](docs/guardrails.md) for the layer model and abridged
threat table. The standing assumptions: the agent is untrusted, the model
provider is semi-trusted, the human approval terminal and the hub's RBAC are
the trust anchors.
