<!--
SPDX-FileCopyrightText: 2026 Sandeep Bazar
SPDX-License-Identifier: Apache-2.0
-->

# Vendored third-party site assets

Committed rather than loaded from a CDN, on purpose.

This project's whole thesis is that you verify before you trust: every GitHub
Action is pinned by commit SHA, every Python dependency by hash, every release
artifact signed with provenance. Pulling an unpinned script from a CDN into the
project's own homepage would contradict all of it, and a CDN compromise would
execute attacker code in every visitor's browser.

| File | Upstream | Version | SHA-256 |
| --- | --- | --- | --- |
| `mermaid.min.js` | https://cdn.jsdelivr.net/npm/mermaid | 11.12.0 | `07e37dfa97b337ccc85365d57eddf99b9706f09db3b59b260d0333b23b343c4b` |

## Updating

```sh
MV=<new-version>
curl -fsSL "https://cdn.jsdelivr.net/npm/mermaid@${MV}/dist/mermaid.min.js" \
  -o web/vendor/mermaid.min.js
shasum -a 256 web/vendor/mermaid.min.js
```

Update the version and hash in the table above in the same commit. The file is
~2.7 MB, so `web/static/site.js` loads it lazily — only on pages that actually
contain a diagram, and only once one is about to scroll into view.
