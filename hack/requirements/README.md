<!--
SPDX-FileCopyrightText: 2026 Sandeep Bazar
SPDX-License-Identifier: Apache-2.0
-->

# Hash-pinned CI tool requirements

Each file here pins one build-time tool that a workflow installs, together with
its full transitive closure and a SHA-256 hash for every artifact. Workflows
install them with `--require-hashes`, so pip fails closed if PyPI ever serves
different bytes for a pinned version.

| File | Tool | Consumed by |
| --- | --- | --- |
| `parity.txt` | `pyyaml` | `.github/workflows/ci.yaml` — guardrail ↔ Kyverno parity contract |
| `build.txt` | `build` | `.github/workflows/release.yaml` — sdist and wheel build |
| `pip.txt` | `pip` | `.github/workflows/bench.yaml` — pip upgrade inside the bench venv |

These are deliberately separate from the top-level `requirements.lock`, which
locks the *server's own runtime* dependencies for the container image. Tools
used only to run CI have no business in that closure.

`--require-hashes` is all-or-nothing: pip refuses the whole install if a single
resolved dependency lacks a hash. That is why `build.txt` also pins
`packaging`, `pyproject-hooks`, and a Windows-only `colorama`, even though the
workflows only ever ask for `build`.

## Regenerating

Same toolchain as `requirements.lock`. Compile from a bare specifier so the
transitive set is resolved fresh:

```sh
echo "pyyaml==6.0.3" | uv pip compile - --generate-hashes --universal -o hack/requirements/parity.txt
echo "build==1.5.0"  | uv pip compile - --generate-hashes --universal -o hack/requirements/build.txt
echo "pip==26.2.1"   | uv pip compile - --generate-hashes --universal -o hack/requirements/pip.txt
```

`--universal` resolves across platforms rather than just the host, so the same
file is valid on any runner. Dependabot also proposes version bumps here and
rewrites the hashes itself; those PRs need no manual regeneration.
