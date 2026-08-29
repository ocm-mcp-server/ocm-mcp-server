# Contributing

Thanks for your interest - issues, discussion, and PRs are all welcome.

## Development setup

```bash
git clone https://github.com/ocm-mcp-server/ocm-mcp-server.git
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

This is enforced, not merely requested: the `dco` job in CI fails any pull request
with a commit missing the trailer. If you have already pushed, `git rebase --signoff`
over your branch and force-push with lease.

### Sign-off and signing are different things

`Signed-off-by` is a text trailer asserting you have the right to submit the change -
that is the DCO, and it is what CI checks. GitHub's green **Verified** badge is
something else: a cryptographic signature proving the commit came from a key you hold.
Neither implies the other, and this project wants both.

SSH signing is the least ceremonious way to get the badge:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

Then add that **public** key to GitHub a second time, at
Settings -> SSH and GPG keys -> New SSH key, with **Key type: Signing key**. An
authentication key and a signing key are separate entries even when the key is
identical; a commit signed with a key GitHub does not know as a signing key shows
`Unverified` rather than `Verified`.

## Releases are immutable

A published version tag is never deleted, moved, or re-cut. If a release fails
partway (CI, PyPI, image publish), the fix rolls forward to the **next** patch
version; the failed tag stays as history. This keeps the Git tag, the PyPI
artifact, the GHCR image, and the MCP Registry listing traceable to one commit
per version, forever.

The `ReleaseTag-Immutability` repository ruleset enforces this on the server: deleting
or force-moving a `v*` tag is rejected, whichever tool is used.

## What lives outside the repository

Branch protection, the tag-immutability ruleset, the site publishing deploy key, and the
three release services keyed to the repository owner (PyPI, the MCP Registry, GHCR) are
settings rather than files, so cloning does not reproduce them. They are listed in
[docs/repository-setup.md](docs/repository-setup.md) - read that before forking or
transferring the repository, not after the first workflow breaks.

## Reporting security issues

Please do not open public issues for security reports - see [SECURITY.md](SECURITY.md).
