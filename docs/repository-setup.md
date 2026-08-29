# Repository setup: what is not in the code

Most of this project is reproducible from the repository alone: clone it, install the
dependencies, run `make ci-local`, and everything works. A handful of things are not,
because they live in GitHub settings or in external services rather than in a file.

They are written down here because they are otherwise invisible — a fork, a transfer to
a new owner, or a second maintainer would each discover them one broken workflow at a
time. That is exactly what happened to this project once already: transferring the
repository from a personal account to an organization silently broke releases, because
the PyPI publisher, the registry namespace and the container path are all keyed to the
owner and none of them follow a transfer.

Everything below is settings, not secrets. The one secret is named, not printed.

## Organization

| Setting | Value | Why |
| --- | --- | --- |
| `deploy_keys_enabled_for_repositories` | `true` | Without it, adding the site publishing key fails with *"Deploy keys are disabled for this repository"*. It is an **organization** setting, not a repository one, which makes it easy to misdiagnose. |

## This repository

| Setting | Value | Why |
| --- | --- | --- |
| Branch protection on `main` | 8 required checks, strict, 1 approving review | `test` on 3.11–3.14, `policy-test`, `secret-scan`, `dependency-review`, `dco`. Strict means a branch must be current before merging. |
| Ruleset `MainBranch-Protection` | `deletion`, `non_fast_forward` on the default branch | Branch protection alone does **not** prevent a force-push; the API silently ignores `allow_force_pushes: false`. The ruleset is the only lever that works. |
| Ruleset `ReleaseTag-Immutability` | `deletion`, `non_fast_forward` on `refs/tags/v*` | Published versions are immutable. A failed release rolls forward to the next patch version rather than re-cutting a tag. |
| Secret `SITE_PUBLISH_SSH_KEY` | private half of the site deploy key | Lets `publish-root-site.yaml` write the built site to the root site repository. |
| Pages | source: GitHub Actions | Serves the redirect built by `pages.yaml`, not a second copy of the site. |

## The root site repository

`ocm-mcp-server.github.io` exists for one reason: GitHub serves an organization's root
Pages site **only** from a repository with exactly that name. No workflow in this
repository can publish to `https://ocm-mcp-server.github.io/` directly, which is why the
site is built here and pushed there.

| Setting | Value |
| --- | --- |
| Deploy key `publish-root-site (CI)` | write access; public half of `SITE_PUBLISH_SSH_KEY` |
| Pages | deploy from branch `main`, path `/` |

A deploy key is used rather than a personal access token deliberately: it is bound to
that one repository by construction rather than by policy, it cannot reach anything else
in the account, and it does not expire, so it cannot lapse unnoticed between releases.

## External services, all keyed to the repository owner

These three do **not** follow a repository transfer, and `hack/release.sh` refuses to cut
a release until a human confirms them.

| Service | Required |
| --- | --- |
| PyPI | Trusted publisher for project `ocm-mcp-server`, pointing at this repository, environment `pypi`. No API token is stored anywhere. |
| MCP Registry | Namespace `io.github.ocm-mcp-server`, matching the `mcp-name` comment at the top of README.md and the name in `server.json`. |
| GHCR | Package `ocm-mcp-server` under the organization, **public**. The registry publish step refuses an image that is not anonymously pullable. |

## Local development

The versions below are what CI uses; anything close works.

| Tool | Note |
| --- | --- |
| Python 3.11+ | 3.11 through 3.14 are all tested |
| podman | **not** Docker — the scripts prefer podman and start its VM if stopped. Docker is the fallback, which is what CI runners use |
| kind, kubectl, clusteradm, helm | only for the end-to-end fleet |
| kyverno CLI | 1.15+ for the policy tests; see [policy pack](policy-pack.md) for why that floor |

Two local-only files are untracked on purpose and are not in the repository:
`hack/githooks/commit-msg`, which enforces the commit identity rules, and
`.local-context/`, which holds working notes. Neither is required to build or test.

## Reproducing this setup elsewhere

If you fork this repository, the code works immediately and CI mostly works. What will
not work until you configure it:

1. **Releases** — you need your own PyPI trusted publisher, registry namespace and
   container path. `hack/release.sh` will stop and tell you.
2. **Site publishing** — create a deploy key on your own site repository and store its
   private half as `SITE_PUBLISH_SSH_KEY`, or delete `publish-root-site.yaml`.
3. **Rulesets and branch protection** — none of this is in the repository; recreate it
   from the tables above, or accept weaker guarantees.

Nothing else is hidden. Every dependency is pinned by hash, every action by SHA, and
every quoted number in the documentation is checked against the source by
`hack/docs_stats.py` in CI.
