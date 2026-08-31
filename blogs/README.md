<!-- SPDX-FileCopyrightText: 2026 Sandeep Bazar -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Blog posts

Long-form writing about the project. The canonical home is
[sandeepbazar.github.io/blogs](https://sandeepbazar.github.io/blogs/), where every
post is served at `/blogs/ocm-mcp-server/<slug>/` and the markdown lives in
[`posts/ocm-mcp-server/`](https://github.com/sandeepbazar/blogs/tree/main/posts/ocm-mcp-server).

Every title links to the canonical version. Where a piece also exists on Medium,
that copy sets its canonical link back here, so search does not split ranking
across the two.

| Date | Post | Also on |
|---|---|---|
| 2026-08-31 | [Why Concurrent Fan-Out Benchmarks at 1.2x on Localhost](https://sandeepbazar.github.io/blogs/ocm-mcp-server/why-fan-out-measures-1-2x-on-localhost/) | |
| 2026-08-30 | [Three Agents, One Server, and the Same Seven Walls](https://sandeepbazar.github.io/blogs/ocm-mcp-server/three-agents-one-server-same-seven-walls/) | |
| 2026-08-01 | [Your MCP Server Is a Security Boundary, Not an API Wrapper](https://sandeepbazar.github.io/blogs/ocm-mcp-server/mcp-server-is-a-security-boundary/) | [Medium](https://medium.com/@sandeepbazar/your-mcp-server-is-a-security-boundary-not-an-api-wrapper-95c975fc94d4) |
| 2026-07-29 | [Can an AI Agent Take the 2 A.M. Page?](https://sandeepbazar.github.io/blogs/ocm-mcp-server/can-an-ai-agent-take-the-2am-page/) | [Medium](https://medium.com/@sandeepbazar/can-an-ai-agent-take-the-2-a-m-page-i-built-the-guardrails-and-published-the-receipts-e98fa4c5a2db) |

## Conventions for new posts

- Posts are written in the [blogs repo](https://github.com/sandeepbazar/blogs)
  under `posts/ocm-mcp-server/`, not here. That repo's build rejects a post
  filed outside a known collection, an unresolvable cover, or an SVG social
  card, so the checks live where the markdown does.
- Media: hotlink `https://raw.githubusercontent.com/ocm-mcp-server/ocm-mcp-server/main/...`
  so the post renders identically on GitHub and on Medium import; videos go
  to YouTube (Medium cannot host MP4s) and are embedded by URL.
- Add a row to the table above.
