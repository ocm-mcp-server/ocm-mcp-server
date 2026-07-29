# Contributing

Thanks for your interest - issues, discussion, and PRs are all welcome.

## Development setup

```bash
git clone https://github.com/sandeepbazar/ocm-mcp-server.git
cd ocm-mcp-server
make install     # editable install with dev + tracing extras
make test        # unit tests (no cluster required)
make lint        # ruff
make bootstrap   # full local fleet, if you want end-to-end
```

## Ground rules

- **Small tool surface is a feature.** New MCP tools need a written rationale
  covering why the capability is safe to expose and which guardrail layers
  cover it. "It would be convenient" is not sufficient.
- **Every write path change needs tests** for the guardrail and approval
  behavior it touches.
- **Policies** follow the [kyverno/policies](https://github.com/kyverno/policies)
  conventions: descriptive dash-named files, `policies.kyverno.io/*` annotations,
  one policy per concern.

## Commit conventions

- Conventional-style subjects: `feat: ...`, `fix: ...`, `docs: ...`, `test: ...`.
- One logical change per commit; keep diffs reviewable.

## Sign-off

Contributions are expected to be signed off under the
[Developer Certificate of Origin](https://developercertificate.org/) (DCO): by signing
off you certify you wrote the change, or otherwise have the right to submit it under the
project's license. Add the `Signed-off-by` trailer with:

```bash
git commit -s
```

Do not add any other trailers to commit messages.

## Releases are immutable

A published version tag is never deleted, moved, or re-cut. If a release fails
partway (CI, PyPI, image publish), the fix rolls forward to the **next** patch
version; the failed tag stays as history. This keeps the Git tag, the PyPI
artifact, the GHCR image, and the MCP Registry listing traceable to one commit
per version, forever.

## Reporting security issues

Please do not open public issues for security reports - see [SECURITY.md](SECURITY.md).
