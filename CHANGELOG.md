# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-08-29

### Added

- **A documentation site at
  [ocm-mcp-server.github.io](https://ocm-mcp-server.github.io/)**,
  built by `hack/build_site.py` from `wiki/` and `docs/` — the same markdown
  those trees already hold, so nothing is duplicated and `hack/publish-wiki.sh`
  keeps feeding the GitHub wiki from the same files. Dark-first with a light
  toggle, a mega-menu that shows each section's chapters before you click,
  scroll-reveal and scrollspy, and click-to-zoom on every diagram. Mermaid is
  **vendored** rather than pulled from a CDN: a project that pins every action
  by SHA and every dependency by hash should not load an unpinned third-party
  script into its own homepage.
- **Two build-time invariants for the site**, in the spirit of the
  guardrail↔Kyverno parity contract: every markdown file under `wiki/` and
  `docs/` must be either navigated to or explicitly excluded with a reason, and
  every internal link must resolve to a generated page. Either failure exits
  non-zero and fails the Pages workflow, because both are silent once deployed.
- **A VS Code (Copilot Chat) client config** at `examples/vscode-mcp.json`,
  plus an `examples/README.md` index of which file goes where. VS Code keys its
  config under `servers`, not `mcpServers` as Claude Code and Gemini CLI do, so
  copying a neighbouring config fails silently — the difference is called out
  rather than left to be rediscovered.

### Changed

- **The project moved to the `ocm-mcp-server` organization.** The repository,
  the container image and the MCP Registry listing all move with it:
  `ghcr.io/ocm-mcp-server/ocm-mcp-server` and
  `io.github.ocm-mcp-server/ocm-mcp-server`. The documentation site is served
  from the organization root at https://ocm-mcp-server.github.io/ rather than a
  repository sub-path.

  A repository transfer carries almost everything with it, and the exceptions
  are the interesting part: **GitHub Pages URLs do not redirect**, container
  packages stay behind at the old owner, PyPI's trusted publisher is keyed to
  `owner/repo`, and the MCP Registry namespace is `io.github.<owner>`. Each had
  to be re-pointed by hand.

### Fixed

- **Supply-chain identifiers left pointing at the previous owner.** The URL
  sweep after the move matched `https://` patterns and missed identifiers that
  are not URLs: the Helm chart and deployment manifest still pulled
  `ghcr.io/<old-owner>/ocm-mcp-server`, and the MCP server name in the
  `Dockerfile` label and the publish workflow disagreed with `server.json`.
  The registry validates a listing against the repository and the published
  package, so that mismatch fails the publish. `hack/release.sh` now refuses to
  cut a release when any of these disagree with the repository's actual owner.
- **Secret scanning broke on the move to an organization.**
  `gitleaks/gitleaks-action` is free for repositories owned by a personal
  account and requires a paid `GITLEAKS_LICENSE` once the owner is an
  organization, failing closed without one. gitleaks itself is MIT-licensed, so
  CI now runs the binary directly — same scan, no licence, and one fewer
  third-party action in the supply chain. Pinned by version and sha256, with
  the checksum verified before the archive is unpacked.
- **A dispatched image build published only `:latest`.** `publish-image`
  derived its version with `type=semver`, which reads the git ref and produces
  nothing on a manual run. `server.json` pins an exact image, so the registry
  publish would then fail for a reason that looked unrelated. The version is now
  resolved explicitly and validated.
- **The container base image had silently drifted off `slim`.** `Dockerfile`
  pinned the base by digest alone (`FROM python@sha256:...`) with the tag only
  in a comment. Dependabot's docker ecosystem has no tag to track in that form,
  so it fell back to `python:latest` — moving the image from an 87-package slim
  base to the 469-package full one, complete with HEIF/AVIF image codecs
  (`libheif`, `libde265`, `dav1d`) that a Kubernetes control-plane server has no
  use for. Those packages carried most of the 64 HIGH CVEs that failed the Trivy
  gate on the v0.4.0 image publish. The base is now pinned by **tag and digest**
  (`python:3.14-slim@sha256:…`), so Dependabot tracks the slim tag and the digest
  still pins exactly. Verified by building the image: it runs, the `ocm-mcp` CLI
  works, and the OS package count drops 469 → 87.
- **The nightly end-to-end run had been red since 2026-08-15**, failing in
  "Install clusteradm" before a single test executed: upstream renumbered
  clusteradm to 1.x and deleted the `v0.9.x` tags, so the pinned installer URL
  404s permanently. Moved to `v1.3.1`. The same call sites also invoked the
  installer with no version argument, where it defaults to `latest` — so the tag
  pinned the installer script while the binary floated. The version is now
  passed through. A local run could not have caught this: `hack/e2e-local.sh`
  only downloads clusteradm when the binary is absent, so every machine that
  already had one skipped the broken URL entirely.
- **A mermaid sequence diagram in `wiki/How-It-Works.md` never rendered.** The
  message text `applied; verify with reads` contains a semicolon, which mermaid
  treats as a statement separator, so the diagram failed to parse — on the
  GitHub wiki as well as the new site. Now `applied, verify with reads`. All 22
  diagrams across the site parse.

## [0.4.0] - 2026-08-13

The supply-chain release. What this project asks of its users — verify before
you trust — it now applies to itself end to end: release artifacts you can
check, build tools that fail closed on a tampered index, a branch you cannot
rewrite, and a security policy that commits to dates rather than adjectives.
Twelve open code-scanning alerts went to four, and the four that remain are
honest ones no code change can close: repository age, a solo maintainer who
cannot approve their own pull requests, and a badge only a human can register.

### Security

- **CI build tools are now hash-pinned**, not just version-pinned. `pyyaml`
  (parity contract), `build` (release), and `pip` (bench) install from
  `hack/requirements/*.txt` with `--require-hashes`, so a compromised or
  re-uploaded PyPI artifact fails the build instead of running in it. A
  version pin trusts the index to keep serving the same bytes; a hash pin
  does not. Dependabot watches the new directory separately from the
  server's own runtime closure. Closes OpenSSF Scorecard Pinned-Dependencies
  findings on `ci.yaml`, `release.yaml`, and `bench.yaml`.
- **GitHub Releases now carry signed artifacts with build provenance.** A new
  `sign-release` job generates SLSA build provenance for the sdist and wheel,
  signs them keylessly with Sigstore (GitHub OIDC, no stored key), verifies
  the bundles it just produced, and attaches the artifacts plus their
  `.sigstore.json` bundles and a `provenance.intoto.jsonl` to the Release.
  Provenance is the stronger claim — a signature attests that this repository
  signed the bytes, provenance attests which workflow at which commit built
  them — and it is the same guarantee the container image already ships. The
  distributions handed to the signer are the exact bytes published to PyPI,
  passed between jobs as a build artifact rather than rebuilt. Previously the Releases page carried no
  downloadable artifact at all — the PEP 740 attestations lived on PyPI and
  the Cosign signature in the OCI registry, so anyone fetching from GitHub had
  nothing to verify against. `docs/deployment.md` documents verification.
- **Branch protection on `main` now requires status checks and forbids force
  pushes.** Previously protection carried no required checks at all, so a PR
  could merge with CI red, and `main` history was rewritable. The force-push
  block came from a repository ruleset that was active but targeting no
  branch; it now targets the default branch.
- **The security policy states a disclosure process.** `SECURITY.md` now
  commits to concrete windows — acknowledgement, triage, fix, and a 90-day
  coordinated-disclosure default — plus CVE handling, reporter credit, and
  which half of the system a severity judgement applies to. It previously
  promised only "an acknowledgement within a few days".

### Fixed

- **Loose API-group assertion in the reader tests**: `test_reader.py` checked
  the resolved group with a suffix match, which would also accept a lookalike
  such as `evil-open-cluster-management.io`. It now pins the exact expected
  group per kind, so a sub-group drift (cluster/work/addon) fails the test.
  Also clears a CodeQL `py/incomplete-url-substring-sanitization` finding.
- **MCP Registry OCI schema compliance**: the registry now requires OCI
  packages to carry the version in the identifier tag
  (`ghcr.io/...:X.Y.Z`) with no separate `version` field; `server.json`,
  `hack/release.sh`, and the release workflow's stamping and version gate
  all updated. This is what failed the v0.3.0 registry publish (PyPI,
  the GitHub Release, and the signed image all succeeded). A new
  manual-dispatch `publish-registry.yaml` workflow re-publishes the
  listing from main without ever moving a released tag.

## [0.3.0] - 2026-07-29

The evidence release. The claims this project makes are now backed by published
data: first multi-model evaluation results (safety 44/44 across two independent
frontier agents), a fleet-scale benchmark with real measured numbers, a one-call
concurrent fleet-health sweep as the 35th tool, two waves of external-audit
fixes (five security hardenings plus a closed init-container gap in the Kyverno
backstop), and a re-validated 84-step end-to-end suite. Also the first release
cut under the new tag-immutability policy: this version rolls forward from
v0.2.2 and its tag will never move.

### Security

- **Kyverno backstop now covers init and ephemeral containers**: the
  image-pinning, privileged-container, and secret-access policies checked only
  `spec.template.spec.containers`, so an unpinned or privileged
  **initContainer** could pass the policy layer (the Python guardrails already
  rejected it - defense-in-depth restored). Offline policy suite grows 39 -> 42
  cases and the guardrail-Kyverno parity contract now proves both layers agree
  on exactly this gap.
- **Five low-severity hardening fixes from an external security assessment**:
  the server now warns on stderr at startup if the approval **private** key is
  present in its own state directory (a compromised server could mint its own
  tokens - move it off-box with `OCM_MCP_SIGNER_KEY`) and separately if
  `OCM_MCP_ISSUER`/`OCM_MCP_AUDIENCE` are both still left at their defaults
  (content-hash binding still limits the blast radius, but set
  deployment-specific values for defense-in-depth); the optional
  `OCM_MCP_AUDIT_ECHO` stderr echo now redacts free-form payload (manifests,
  summaries, reasons, error text) to `"[redacted]"` via a new pure
  `tracing._echo_safe` helper, keeping only structural/identity fields
  (timestamps, chain fields, tool name, outcome, cluster/name/proposal-id-like
  arguments) - the audit **file** is unaffected, only the echo; the Kubernetes
  API client cache in `k8s.py` is now guarded by a `threading.Lock` around its
  read-check-build-store (duplicate builds under the fan-out were benign, the
  lock makes it a non-question); and `filelock.py` + `docs/deployment.md` now
  document that Windows is unsupported (the lock is `fcntl`-based and would be
  a silent no-op there) - use WSL2.

### Fixed

- **Eval/chaos harness, first live-run findings** - `chaos/scenarios/oom-loop.sh`
  patched the memory limit below the deployment's existing request (API rejects
  it; now patches both); `chaos/inject.sh reset` used `kubectl apply` alone,
  which never removes patched-in fields like `command`/`args`, so the demo app
  stayed broken after any crashloop scenario (now deletes the deployment before
  re-applying); `eval/run_eval.py` lost every scored scenario when one scenario
  errored (now isolates per-scenario errors as results and persists the results
  file after each scenario).

### Added

- **Published multi-model evaluation results** (`eval/results/`): first full
  22-scenario runs against two independent frontier agents - Claude Code
  (`claude-sonnet-5`) and Codex CLI (`gpt-5.6-sol`) - on a live kind fleet.
  Safety 22/22 for **both** models (every adversarial bait refused, zero unsafe
  proposals); diagnosis 16/22 and 13/22; recovery 8/15 each, with the misses
  identical across models and analyzed honestly in `eval/results/README.md`.
  `run_eval.py` now honors `OCM_MCP_HOME` for its audit reads so an agent whose
  server uses a non-default state directory can be scored.
- **Fleet-scale benchmark** (`hack/bench_fleet.py`, manual-dispatch `bench.yaml`,
  `docs/benchmarks.md`): real measured numbers, not projections. Hub phase applies
  1000 fake `ManagedCluster` CRs to the kind hub and times `ocm.paged_list` /
  `fleet_health` reads (1023 clusters read back in ~0.08s). Fanout phase creates
  ~20 real kwok-simulated spoke apiservers (`kwokctl --runtime binary`, ~50
  kwok-simulated pods each), registers them on the hub, and times
  `fleet_health` sequential vs. concurrent (`OCM_MCP_FANOUT_WORKERS`) - ~1.2x on
  zero-latency localhost spokes, with the expected larger real-network win
  documented, not fabricated. Setup/teardown (kwok clusters + their
  ManagedCluster CRs) are wired into the script itself with a `--keep` debug flag.
- **`get_fleet_health` tool**: whole-fleet health in one call instead of looping
  `get_cluster_health` per cluster - hub conditions from a single paged list plus
  concurrent spoke pod/deployment scans, fanned out on a bounded thread pool
  (`OCM_MCP_FANOUT_WORKERS`, default 8, floor 1). A slow or broken cluster becomes a
  per-cluster `error` entry instead of failing the whole sweep; unhealthy clusters
  sort first.
- **Tracing exercised end to end**: `make e2e` installs the `[tracing]` extra and a
  new step exports real OTel spans over OTLP/HTTP to a local sink, asserting the
  trace batch names the tool span and the service - so the "OTel spans -> Jaeger"
  path is tested, not just documented. Full observability documentation landed in
  three places: a README section (audit vs tracing vs metrics - what each answers,
  why spans are fail-soft, how to enable, how it is tested), an architecture
  low-level-design diagram of the three signals, and the deployment-guide how-to.
- **Root `ARCHITECTURE.md`** entry point, and a full low-level design section in
  `docs/architecture.md`: five vertical Mermaid diagrams (component stack, read-call
  anatomy, gated write sequence, rollback/lifecycle paths, audit/anchor/key
  machinery) plus a guarantee-to-enforcement index.

- **6 MCP resources**: `ocm://clusters`, `ocm://clusters/{cluster}`, `ocm://policies`,
  `ocm://proposals`, `ocm://audit/tail`, and `ocm://guardrails` (the exact allow-lists
  proposals are checked against, so an agent can self-correct before a rejection
  round-trip). Read-only, audited like tool calls.
- **Signed audit anchors**: `ocm-mcp audit-anchor` signs the audit chain head with the
  off-box approval key; `ocm-mcp audit-verify` now also fails unless the log still
  extends every anchored head - tail truncation and wholesale rewrites are detectable.
- **Kyverno full parity pack** (5 -> 9 policies): exact apiVersion/kind allow-list
  (closes group spoofing past the kind-only allowlist), ClusterIP-only Services with no
  externalIPs, HPA maxReplicas ceiling, no secret env refs or projected
  serviceAccountToken/secret sources, volume types as an allow-list, a 10-manifest cap,
  `runAsUser: 0` rejection, and `kube-*`/`openshift-*` namespace-prefix wildcards.
  Offline suite grows from 16 to 39 cases.
- **Guardrail <-> Kyverno parity contract in CI** (`make parity-test`): the shared
  fixture corpus must get identical verdicts from the Python guardrails and
  `kyverno apply`, making the two-layer defense-in-depth claim a tested invariant.
- **Property-based guardrail tests** (hypothesis): totality on arbitrary input shapes
  (pass or a clean violation, never a crash), secret refs and privileged containers
  rejected in every container role, namespace and GVK fences, and content-independent
  proposal bounds.
- **Nightly end-to-end CI job** (`e2e.yaml`) running the full `hack/e2e-local.sh`
  suite against a real kind-based OCM fleet, with the report as an artifact and a
  README badge.
- **e2e coverage**: the suite now also drives the real server binary over stdio
  JSON-RPC with the official MCP client, exercises the gated rollback flow (including
  an apply-scoped token being refused for rollback), every lifecycle action, all ten
  prompts, remaining read tools, and a negative sweep (expired token, replayed token,
  read-only mode, tampered audit log, signed anchor, `ocm-mcp doctor`).
- **Docs stats drift gate** (`hack/docs_stats.py`): tool/prompt/resource/policy/test
  counts quoted in README, docs, and wiki are computed from source and CI fails when
  they drift.
- **Recorded demo**: a real, unedited `./hack/e2e-local.sh` run (asciinema cast, GIF,
  MP4 in `demo/`), embedded in the README under "Try it end to end".

### Changed

- **Hub reads are paged**: all hub list calls follow `continue` tokens in pages of
  `OCM_MCP_LIST_PAGE_SIZE` (default 500) with an `OCM_MCP_LIST_MAX_ITEMS` ceiling
  (default 5000) that reports truncation explicitly, instead of one unbounded response.
- The release bump and CI version gate now also cover `__init__.__version__`, the Helm
  chart `version`/`appVersion`, and the chart's default image tag.

## [0.2.2] - 2026-07-27

A hardening and productization release addressing two follow-up enterprise-readiness
audits. It brings hub-side admission to parity with the server's guardrails, deepens CSR
and supply-chain integrity, reaches 100% statement and branch test coverage, and adds
release automation: PyPI trusted publishing and an official MCP Registry listing.

### Added

- **PyPI publishing** via OIDC trusted publishing on release tags: install with
  `pip install ocm-mcp-server`, or run directly with `uvx ocm-mcp-server`.
- **Official MCP Registry listing** as `io.github.ocm-mcp-server/ocm-mcp-server`:
  `server.json` metadata, ownership markers in the README (PyPI) and image
  annotations (OCI), and automated registry publish on every release tag.
- **OpenSSF Scorecard** workflow (weekly + on push to main) with published results,
  code-scanning upload, and a README badge.
- **`make test-report`**: refreshes a unit-tests-and-coverage wiki page, a Shields
  coverage badge served from the wiki, and a browsable per-line HTML coverage
  report; CI uploads all of it as an artifact on every run.
- CI test matrix extended to Python 3.13 and 3.14.

### Fixed

- `hack/bootstrap.sh` now retries transient `clusteradm init` failures
  ("unexpected watch event received") a bounded number of times, cleaning the
  half-initialized hub between attempts, so the end-to-end fleet test does not
  fail on an upstream watch flake.

### Security

- **Kyverno parity with the static guardrails.** A new `restrict-manifestwork-pod-security`
  policy enforces the Restricted Pod Security baseline (automountServiceAccountToken=false,
  default/empty service account, and - across regular AND init containers - runAsNonRoot,
  allowPrivilegeEscalation=false, drop-ALL, no added caps, not privileged, seccomp, and no
  Secret/hostPath/PVC/CSI/NFS volumes), plus a ban on ephemeral containers. So a compromised
  server cannot slip a labelled-but-unsafe ManifestWork - or a privileged init container -
  past admission. Verified by offline adversarial tests (17 Kyverno cases total).
- **CSR request binding (fail-closed).** The `accept` action captures a hash of the PKCS#10
  request at propose time, re-verifies it is unchanged at apply (an empty captured hash is
  refused, not skipped), and validates the parsed certificate subject Common Name is the OCM
  agent identity for the target cluster.
- **Cheaper, safer limits.** The proposal size limit is checked on the raw input before
  parsing; the spent-token replay ledger is append-only with occasional compaction (no full
  rewrite per apply); an optional stderr JSON audit echo (`OCM_MCP_AUDIT_ECHO`) forwards the
  audit stream to a SIEM.
- **Concurrency-safe apply.** Each proposal apply now runs under a per-proposal lock, so two
  separately-minted valid tokens can no longer race on the same pending proposal.
- **More guardrail limits.** Exact 64-hex `@sha256` digest validation, `runAsUser: 0`
  rejection, an expanded protected-namespace set (kube-*/openshift-*/default), a per-proposal
  byte ceiling, and an HPA `maxReplicas` cap.
- **Spent-token ledger** is created 0600 and pruned of expired ids so it cannot grow forever.

### Supply chain / CI

- All GitHub Actions are pinned to commit SHAs; the base image is pinned by digest and the
  container builds from the hash-pinned `requirements.lock`. Dependabot now also watches the
  docker ecosystem.
- The image-publish workflow triggers on the tag push (a Release created by GITHUB_TOKEN does
  not start it) and now runs a Trivy scan and verifies the Cosign signature it just created.
- CI type-checks the security modules strictly (`check_untyped_defs`), lints `hack/`, and
  enforces an 80% coverage floor. Unit tests: 222; branch coverage 85%.

### Fixed

- Documentation narrowed further: the audit hash chain is described as detecting edits,
  reordering, and mid-log deletion but not tail-truncation (which needs external anchoring);
  the deployment/Helm chart no longer defaults to `:latest`, supports a digest and a
  persistence PVC, ships a NetworkPolicy and PDB, and its service-account-token comment is
  corrected. The `.github/FUNDING.yml` and the e2e "ALL GREEN" wording (now noting
  expected-unavailable steps) are fixed.

## [0.2.1] - 2026-07-26

A hardening release addressing two independent external enterprise-readiness audits. It
strengthens the actual trust boundaries and narrows the security documentation to describe
only what is enforced.

### Security

- **Restricted Pod Security guardrails.** Embedded workloads (and their init and ephemeral
  containers) must now meet a Restricted baseline: `automountServiceAccountToken: false`,
  required `runAsNonRoot`, explicit `allowPrivilegeEscalation: false`, all capabilities
  dropped, and a seccomp profile. Added an allow-list of volume types (no PVC, CSI,
  hostPath, or secret) and Service types (no NodePort/LoadBalancer/ExternalName/externalIPs),
  optional digest-pinning (`OCM_MCP_REQUIRE_DIGEST`), rejection of `runAsUser: 0` (root),
  and schema validation so a malformed manifest is a clean rejection instead of a crash.
- **One-time, issuer/audience-bound approval tokens.** Tokens now carry a unique id, issuer,
  audience, and not-before; the id is recorded as spent (locked, fsynced) on first use, so a
  token cannot be replayed, and a token minted for one deployment cannot be used against
  another. The signer and verifier key paths are now independent (`OCM_MCP_SIGNER_KEY` /
  `OCM_MCP_VERIFIER_KEY`) so the private key can live off the server; a planned rotation can
  keep a previous verifier key valid until outstanding tokens expire.
- **Requester-bound Kyverno policy.** A new policy matches ManifestWorks by the server's
  ServiceAccount identity and requires the `managed-by` label, closing the bypass where an
  unlabeled ManifestWork would skip the label-keyed content policies. Verified by a new
  offline test with requester `userInfo`.
- **Stronger CSR validation.** The `accept` action now also rejects denied CSRs and requires
  an OCM group, `client auth` usage, and a bootstrap username bound to the target cluster,
  re-checked at apply.
- **Tamper-evident audit log.** Each entry carries an actor, a sequence number, and a hash
  chained to the previous entry (chain head derived from the log itself, not a sidecar);
  `ocm-mcp audit-verify` recomputes the chain and reports a broken chain rather than
  crashing on a corrupt line. Argument values are bounded so a large payload cannot bloat a
  line, and an audit-write failure is surfaced to stderr and never masks a tool result.
- **Hardened state store.** Proposal ids are validated (no path traversal), writes are locked
  and fsynced, and status advances only along legal transitions. Proposal/audit files are
  created 0600 and the proposals directory 0700.

### Added

- Reference `deploy/deployment.yaml` and a Helm chart (`deploy/charts/ocm-mcp-server`) with a
  Restricted pod shape and read-only verifier-key mount.
- Optional Prometheus `/metrics` endpoint (`OCM_MCP_METRICS_PORT`).
- `ocm-mcp audit-verify` command.
- Hash-pinned `requirements.lock`, Dependabot, and CI gates for `ruff format`, `mypy`, and a
  coverage floor; release images now ship an SBOM, provenance, and a keyless Cosign signature.

### Fixed

- Documentation narrowed to enforced boundaries: the "compromised server cannot mint" claim
  is now scoped to off-box signing; RBAC no longer claims per-object ownership (enforced in
  the app); the generic reader is described as returning full allow-listed objects. Removed
  the last HMAC/secret wording remnants. Corrected the invalid `.github/FUNDING.yml`.

## [0.2.0] - 2026-07-25

A security-focused release addressing an external security audit. The headline change
is that human approval is now cryptographically independent of the server.

### Security

- **Asymmetric, operation-bound approval (was shared HMAC).** The `ocm-mcp` CLI holds an
  Ed25519 private signing key; the MCP server loads only the public key. The server can
  verify a token but can never mint one, so a compromised server - or an agent that reads
  the server's key material - still cannot approve its own changes. Each token's claims
  bind the exact proposal hash, the operation (`apply` or `rollback`), and an expiry, so
  an apply token can never authorize a rollback.
- **Rollback is now a distinct, approvable operation.** `propose_rollback` creates a
  separate rollback proposal bound to the applied ManifestWork's name and UID;
  `rollback_manifestwork` verifies a rollback-scoped token, checks the work is still
  ours (managed-by label) with the approved UID, then deletes it. This fixes the old
  workflow where a fresh rollback token could not be minted and an apply token could
  authorize deletion.
- **Static guardrails hardened.** Manifests are matched against an exact
  `apiVersion/kind` allow-list (blocking group spoofing like `evil.example/v1, Deployment`),
  and now reject Secret access via `env.secretKeyRef`/`envFrom.secretRef`, secret and
  serviceAccountToken-projected volumes, and arbitrary `serviceAccountName`.
- **CSR approval is bound to exact CSRs.** The `accept` action captures the pending join
  CSRs (name, UID, signer, subject) at propose time and approves only those at apply time,
  re-verifying signer and username - it no longer sweeps every CSR with a matching label
  or approves CSRs created after the human reviewed.
- **Truthful audit.** The trace wrapper now classifies a tool's outcome from its result
  (`rejected` / `failed` / `unavailable`), so a refused operation is no longer logged as
  `ok`; the evaluation harness scores from the corrected outcomes.
- **Dependency bounds.** Pinned `mcp>=1.9,<2` (MCP v2 is a breaking rewrite) and
  `kubernetes<37`; added `cryptography` for Ed25519.

### Changed

- Tool surface: 34 tools (added `propose_rollback`). Proposals are written atomically
  (temp file + rename). `get_audit_trail` streams the tail instead of reading the whole
  file. `cluster_events` fetches a wider window before sorting so newer events are not
  missed on busy clusters. Unit tests: 57.

### Added (tooling, platform, and governance in this release)

- **Expanded the tool surface to 27 tools across nine toolsets** (inventory,
  observability, placement, work, addons, registration, policy, resources,
  audit), covering the Open Cluster Management read API end to end: cluster sets
  and bindings, cluster claims, per-cluster detail, Placements and
  PlacementDecisions, AddOnPlacementScores, ManifestWork status feedback,
  ManifestWorkReplicaSets, ClusterManagementAddOns and per-cluster add-on health,
  pending join CSRs, and governance Policy compliance.
- **Generic allow-listed reader** (`list_resources`, `get_resource`) over OCM API
  types. Secrets and core kinds are not on the allow-list and cannot be named, so
  the dangerous read does not exist rather than being merely restricted.
- **Gated OCM lifecycle actions** (`propose_cluster_action`,
  `apply_cluster_action`): cordon, uncordon, set_label, accept. Each routes
  through the same static-guardrail, hub dry-run, and approval-token gate as a
  ManifestWork; none is applied inline.
- **Four MCP prompts**: `diagnose_fleet`, `remediate_with_approval`,
  `incident_postmortem`, `why_not_scheduled`, encoding the safe workflow.
- **MCP tool annotations** (`readOnlyHint` / `destructiveHint`) on every tool, and
  an `OCM_MCP_READ_ONLY` backstop that disables both write toolsets for
  inspection-only deployments.
- **Homepage demo** (animated terminal GIF) plus a
  [Tools and Prompts reference](docs/tools.md) and a matching wiki page.
- **HyperShift HCP toolset**: `list_hosted_clusters`, `get_hosted_cluster`,
  `list_node_pools` (hypershift.openshift.io/v1beta1), for fleets running Hosted
  Control Planes. Feature-detects when HCPs are hosted on a separate management
  cluster.
- **ACM extended inventory**: `get_cluster_info` (ManagedClusterInfo: OpenShift
  version, nodes, console URL, vendor - read from the hub, no spoke access needed),
  `list_addons_for_cluster`, and `list_policy_violations` (NonCompliant / Pending
  rollup; `Pending` correctly counts as a violation).
- **Add-on lifecycle actions**: `enable_addon` / `disable_addon` (create/delete a
  ManagedClusterAddOn) as gated `propose_cluster_action` actions.
- **Six more prompts**: `onboard_cluster`, `addon_troubleshoot`,
  `hosted_cluster_health`, `policy_compliance_report`, `capacity_report`,
  `rollout_status` (ten prompts total).
- **`ocm-mcp doctor`**: a live read-path smoke test that calls every read tool
  against the hub and prints a PASS/EMPTY/SKIP/FAIL table, writing nothing.

### Security and hardening

- **Apply-time integrity re-check (TOCTOU)**: `apply_manifestwork` and
  `apply_cluster_action` now recompute the proposal's content hash and (for
  ManifestWorks) re-run the static guardrails at apply time, so a proposal file
  edited at rest is rejected even though the token still matches the stale hash.
- **RBAC now mirrors the real tool surface**: the hub ClusterRole covers placement,
  add-on, operator, policy, ManagedClusterInfo, HyperShift, and CSR APIs, plus
  `patch` on ManagedClusters and CSR approval - previously it only allowed
  ManagedCluster reads and ManifestWorks, so most tool calls would have 403'd. Still
  no Secret reads, no exec, no arbitrary delete.
- **Approval key rotation**: `ocm-mcp rotate-secret` regenerates the approval
  keypair, invalidating all outstanding tokens.
- **Bounded spoke reads**: health/event/log calls carry a read timeout
  (`OCM_MCP_SPOKE_TIMEOUT`) and a fetch cap (`OCM_MCP_HEALTH_LIMIT`) that reports
  truncation, so one large cluster cannot hang or flood a tool call.
- **API client TTL**: the cached Kubernetes client is rebuilt after
  `OCM_MCP_CLIENT_TTL` seconds so rotated/exec-refreshed credentials are picked up.
- **Full-UUID proposal IDs** (128-bit) instead of 8 hex characters.
- **Robust PodSpec extraction** in the static guardrails for CronJob and other
  workload kinds, so the security checks stay correct if `ALLOWED_KINDS` grows.

### Changed

- Approval proposals now carry a `kind` (manifestwork or action) and typed
  `params`; the content hash binds the whole proposal, so a token approves an
  exact ManifestWork bundle or an exact lifecycle action.
- Tool surface: 33 tools across ten toolsets (from the initial 10). ManifestWork
  status feedback now decodes the FieldValue `type` discriminator
  (Integer/String/Boolean/JsonRaw) rather than guessing.
- Unit tests: 46 (from 26), adding lifecycle-action approvals, the reader
  allow-list, and the HCP / ManagedClusterInfo / add-on shaping logic.

## [0.1.0] - 2026-07-25

First public release: the complete guardrailed-AgentOps pattern, end to end.

### Added

- **MCP server** with a deliberately small tool surface over an Open Cluster
  Management hub: 7 read tools (`list_clusters`, `get_cluster_health`,
  `query_events`, `get_pod_logs`, `list_manifestworks`,
  `list_pending_proposals`, `get_audit_trail`) and 3 gated write tools
  (`propose_manifestwork`, `apply_manifestwork`, `rollback_manifestwork`).
- **Four guardrail layers**: static checks (privileged/host access, protected
  namespaces, kind allowlist, pinned images) → Kyverno dry-run admission on
  the hub → human approval via HMAC tokens bound to proposal content hashes
  with TTL → least-privilege RBAC.
- **Kyverno ClusterPolicies** validating embedded manifests inside
  ManifestWorks (`foreach` over `spec.workload.manifests`), scoped by the
  `app.kubernetes.io/managed-by: ocm-mcp-server` label, with an offline CLI
  test suite (12 cases) following kyverno/policies conventions.
- **`ocm-mcp` CLI** for the human side: pending / show / approve / reject /
  audit.
- **Observability**: OpenTelemetry span per tool call (optional OTLP export)
  plus an always-on append-only audit log.
- **Fleet bootstrap** (`make bootstrap`): 1 hub + 3 managed kind clusters,
  OCM via clusteradm, Kyverno, policies, RBAC, demo app, optional Jaeger.
- **Chaos scenarios**: failing-rollout, crashloop, quota-exhaustion,
  oom-loop, broken-service, config-drift, scaled-to-zero, reversible via
  `make reset`.
- **Evaluation harness**: 22 scripted incident scenarios (15 remediate,
  3 diagnose-only, 4 adversarial) scored objectively from transcripts, live
  cluster state, and the audit log.
- **Client examples** for Claude Code, Codex CLI, Gemini CLI, and any other
  MCP-capable client, plus a production-shaped system prompt.
- **Documentation**: deployment guide, worked examples, architecture,
  guardrail rationale and threat model, demo script, upstream notes, and a
  project wiki covering the full journey from problem to roadmap.
- Unit tests (26), ruff lint, CI, and Dockerfile.

[0.1.0]: https://github.com/ocm-mcp-server/ocm-mcp-server/releases/tag/v0.1.0
