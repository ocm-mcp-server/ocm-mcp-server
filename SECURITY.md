# Security policy

This project's whole purpose is safety at the AI/infrastructure boundary, so
security reports get first-class attention.

## Reporting

Please report vulnerabilities privately via GitHub Security Advisories at
https://github.com/sandeepbazar/ocm-mcp-server/security/advisories/new

Please do **not** open a public issue, pull request, or discussion for a
suspected vulnerability — filing one is itself a disclosure, and it starts the
clock for everyone running the server before a fix exists.

In scope, especially:

- any way for an MCP tool call to mutate cluster state without a valid
  approval token (approval bypass)
- approval-token forgery, replay against changed content, or TTL bypass
- static-guardrail or policy-evaluation bypasses (e.g. manifest shapes that
  smuggle privileged settings past `guardrails.py` or the Kyverno policies)
- privilege escalation beyond the RBAC in `deploy/rbac.yaml`
- audit-log evasion (tool calls that leave no audit line)

## Disclosure process

This is a single-maintainer project, so the timelines below are honest targets
rather than a contractual SLA. Each one is measured from the moment a report
arrives, and you will be told if a stage is going to slip:

- **Acknowledgement — within 3 business days.** Confirmation that the report
  was received and is being looked at, nothing more.
- **Triage — within 10 days.** A severity assessment and an accept-or-reject
  decision, with reasoning either way. A rejected report still gets an
  explanation of why the behaviour is considered in-design.
- **Fix or documented mitigation — within 30 days** for an accepted high or
  critical issue. Lower-severity issues are batched into the next release.
- **Public disclosure — 90 days after the report**, or as soon as a fix ships,
  whichever comes first. That window moves earlier or later by mutual
  agreement, and moves immediately if the issue is being exploited.

Accepted vulnerabilities are published as a GitHub Security Advisory with a
CVE requested through GitHub, and the fix release notes link back to it.
Reporters are credited by name unless they ask not to be.

Note the split between the two halves of this project when judging severity: a
flaw in the **server** (guardrail bypass, token forgery, audit evasion) is a
vulnerability, whereas a Kubernetes RBAC grant that a cluster administrator
chose to widen beyond `deploy/rbac.yaml` is a deployment decision. Reports
about the latter are welcome as issues rather than advisories.

## Supported versions

Security fixes land on the latest released minor version only. There are no
long-term-support branches; please upgrade before reporting an issue that is
already fixed on the current release.

## Threat model

See https://github.com/sandeepbazar/ocm-mcp-server/blob/main/docs/guardrails.md
for the layer model and abridged threat table. The standing assumptions: the
agent is untrusted, the model provider is semi-trusted, the human approval
terminal and the hub's RBAC are the trust anchors.
