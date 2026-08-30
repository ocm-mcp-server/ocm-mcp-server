#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Build the GitHub Pages site from the repository's own markdown.

    python3 hack/build_site.py               # build to _site/ for Pages
    python3 hack/build_site.py --base / --serve   # preview on localhost:8000

`wiki/` and `docs/` stay the source of truth; this reads them and writes
`_site/`. Nothing here is edited by hand, and `hack/publish-wiki.sh` keeps
publishing the same `wiki/` files to the GitHub wiki, so the two surfaces
cannot drift apart.

Two invariants are enforced at build time rather than left to review:

1. Every markdown file under `wiki/` and `docs/` is either in the navigation
   or in EXCLUDED with a stated reason. A new page cannot be silently dropped.
2. Every internal link resolves to a page that was actually generated.

Either failure exits non-zero, which fails the Pages workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.anchors import anchors_plugin

REPO = Path(__file__).resolve().parent.parent
WIKI = REPO / "wiki"
DOCS = REPO / "docs"
WEB = REPO / "web"
OUT = REPO / "_site"

SITE_URL = "https://ocm-mcp-server.github.io/"
GH = "https://github.com/ocm-mcp-server/ocm-mcp-server"

# Reading order is explicit. Alphabetical sorting would destroy the wiki's
# deliberate 1..11 sequence, which is most of what makes it readable.
JOURNEY: list[tuple[str, str]] = [
    ("Why-This-Exists", "Why this exists"),
    ("The-Idea", "The idea"),
    ("How-It-Works", "How it works"),
    ("Implementation", "Implementation"),
    ("Tools-and-Prompts", "Tools and prompts"),
    ("Guardrails-Deep-Dive", "Guardrails deep dive"),
    ("Getting-Started", "Getting started"),
    ("Use-Cases-and-Impact", "Use cases and impact"),
    ("Evaluation", "Evaluation"),
    ("Roadmap", "What's next"),
    ("Contributing", "Contributing"),
    ("FAQ", "FAQ"),
]

REFERENCE: list[tuple[str, str]] = [
    ("architecture", "Architecture"),
    ("guardrails", "Guardrails"),
    ("policy-pack", "Policy pack"),
    ("deployment", "Deployment"),
    ("repository-setup", "Repository setup"),
    ("tools", "Tools and prompts"),
    ("examples", "Worked examples"),
    ("kubeconfig-contexts", "Kubeconfig contexts"),
    ("benchmarks", "Benchmarks"),
    ("security-self-assessment", "Security self-assessment"),
    ("cncf-sandbox-readiness", "CNCF readiness"),
    ("demo-script", "Demo script"),
    ("upstream-notes", "Upstream notes"),
]

RESULTS: list[tuple[str, str]] = [
    ("Test-Results", "End-to-end fleet run"),
    ("Unit-Test-Results", "Unit tests and coverage"),
]

# Deliberately not published, with the reason on the record.
EXCLUDED: dict[str, str] = {
    "wiki/Home.md": "the site has a purpose-built landing page; this is the wiki's",
    "wiki/_Sidebar.md": "wiki chrome, replaced by the site's own navigation",
    "wiki/_Footer.md": "wiki chrome, replaced by the site's own footer",
    "docs/index.md": "superseded by the generated landing page",
}

SECTIONS = {"journey": JOURNEY, "reference": REFERENCE, "results": RESULTS}
SOURCE_DIR = {"journey": WIKI, "reference": DOCS, "results": WIKI}
# Labels name what the section *promises the reader*, not what it categorically
# is: "Journey" and "Reference" told a visitor nothing about what was inside.
SECTION_LABEL = {"journey": "Start here", "reference": "Run it", "results": "Proof"}
SECTION_BLURB = {
    "journey": "Why it exists, how it works, and what it refuses to automate",
    "reference": "Architecture, deployment paths, the tool surface, the threat model",
    "results": "A real fleet run, multi-model evaluation, coverage",
}


@dataclass
class Page:
    section: str
    stem: str
    nav_label: str
    src: Path
    url: str
    title: str = ""
    description: str = ""
    body: str = ""
    toc: list[tuple[int, str, str]] = field(default_factory=list)


def slugify(stem: str) -> str:
    """`Why-This-Exists` and `kubeconfig-contexts` both become url-safe slugs."""
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower())
    return s.strip("-")


def discover() -> tuple[list[Page], list[str]]:
    """Build the page list and report any markdown file that is neither in the
    navigation nor explicitly excluded."""
    pages: list[Page] = []
    claimed: set[str] = set(EXCLUDED)
    for section, entries in SECTIONS.items():
        root = SOURCE_DIR[section]
        for stem, label in entries:
            src = root / f"{stem}.md"
            rel = str(src.relative_to(REPO))
            claimed.add(rel)
            if not src.exists():
                raise SystemExit(f"navigation lists {rel}, which does not exist")
            pages.append(
                Page(
                    section=section,
                    stem=stem,
                    nav_label=label,
                    src=src,
                    url=f"{section}/{slugify(stem)}/",
                )
            )
    orphans = sorted(
        str(p.relative_to(REPO))
        for p in [*WIKI.glob("*.md"), *DOCS.glob("*.md")]
        if str(p.relative_to(REPO)) not in claimed
    )
    return pages, orphans


def make_markdown(resolve: Any) -> MarkdownIt:
    """CommonMark plus tables, with three renderer overrides: mermaid fences
    become client-rendered hosts, tables get a scroll container, and internal
    links are rewritten to site URLs."""
    md = MarkdownIt("commonmark", {"html": True, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])
    # Emits <a class="header-anchor" href="#id">#</a> after each h2/h3.
    md.use(anchors_plugin, min_level=2, max_level=3, permalink=True, permalinkSymbol="#")

    default_fence = md.renderer.rules.get("fence")

    def fence(tokens: list[Token], idx: int, options: Any, env: Any) -> str:
        tok = tokens[idx]
        if tok.info.strip().split()[:1] == ["mermaid"]:
            src = html.escape(tok.content, quote=True)
            # The source is emitted as real, visible text, not only as an
            # attribute. Without JavaScript - or if the vendored mermaid fails
            # to load - a reader still gets the diagram's content instead of a
            # box that says "rendering" forever. The stylesheet hides it only
            # once JS has announced itself, and the script puts it back if the
            # render throws.
            return (
                '<div class="mermaid-wrap" data-state="pending">'
                f'<div class="mermaid" data-src="{src}"></div>'
                f'<pre class="mermaid-src"><code>{src}</code></pre>'
                "</div>\n"
            )
        assert default_fence is not None
        return default_fence(tokens, idx, options, env)

    def table_open(tokens: list[Token], idx: int, options: Any, env: Any) -> str:
        return '<div class="table-wrap"><table>'

    def table_close(tokens: list[Token], idx: int, options: Any, env: Any) -> str:
        return "</table></div>"

    def link_open(tokens: list[Token], idx: int, options: Any, env: Any) -> str:
        tok = tokens[idx]
        href = tok.attrGet("href") or ""
        tok.attrSet("href", resolve(href, env))
        if href.startswith(("http://", "https://")) and GH not in href:
            tok.attrSet("rel", "noopener")
        return md.renderer.renderToken(tokens, idx, options, env)

    md.renderer.rules["fence"] = fence
    md.renderer.rules["table_open"] = table_open
    md.renderer.rules["table_close"] = table_close
    md.renderer.rules["link_open"] = link_open
    return md


def make_resolver(pages: list[Page], base: str, unresolved: list[str]) -> Any:
    """Map a markdown href onto a site URL.

    Wiki links are bare page names (`](Guardrails-Deep-Dive)`); docs links carry
    `.md`. External and anchor-only links pass through untouched.
    """
    by_stem = {p.stem.lower(): p for p in pages}

    def resolve(href: str, env: Any) -> str:
        if not href or href.startswith(("http://", "https://", "mailto:", "#", "//")):
            return href
        target, _, anchor = href.partition("#")
        anchor = f"#{anchor}" if anchor else ""
        if not target:
            return href
        # A trailing slash means a directory, and directories are repo paths
        # rather than site pages. Checked first because `examples/` (the repo
        # folder) would otherwise collide with `docs/examples.md` (a page).
        if target.endswith("/"):
            return f"{GH}/tree/main/{target.lstrip('./')}{anchor}"
        key = target.removesuffix(".md").split("/")[-1].lower()
        if key == "home" or key == "index":
            return f"{base}{anchor}"
        page = by_stem.get(key)
        if page:
            return f"{base}{page.url}{anchor}"
        # Repo-relative paths (deploy/, examples/, hack/) point at GitHub, which
        # is where those files actually live for a reader.
        if "/" in target or target.endswith((".yaml", ".yml", ".py", ".sh", ".toml")):
            kind = "tree" if target.endswith("/") else "blob"
            return f"{GH}/{kind}/main/{target.lstrip('./')}{anchor}"
        unresolved.append(f"{env.get('page', '?')} -> {href}")
        return href

    return resolve


def collect_toc(tokens: list[Token]) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open" or tok.tag not in ("h2", "h3"):
            continue
        anchor = tok.attrGet("id")
        if not anchor:
            continue
        text = re.sub(r"\s+", " ", tokens[i + 1].content).strip()
        out.append((int(tok.tag[1]), str(anchor), text))
    return out


def first_paragraph(tokens: list[Token]) -> str:
    for i, tok in enumerate(tokens):
        if tok.type == "paragraph_open":
            raw = re.sub(r"[`*_\[\]]", "", tokens[i + 1].content)
            raw = re.sub(r"\s+", " ", raw).strip()
            if len(raw) > 20:
                return raw[:180].rstrip() + ("…" if len(raw) > 180 else "")
    return "AgentOps for Kubernetes fleets, done safely."


def strip_leading_h1(body: str) -> tuple[str, str]:
    m = re.match(r"\s*<h1[^>]*>(.*?)</h1>", body, re.DOTALL)
    if not m:
        return "", body
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    return title, body[m.end() :]


def render_pages(pages: list[Page], base: str) -> list[str]:
    unresolved: list[str] = []
    md = make_markdown(make_resolver(pages, base, unresolved))
    for page in pages:
        text = page.src.read_text(encoding="utf-8")
        env: dict[str, Any] = {"page": str(page.src.relative_to(REPO))}
        tokens = md.parse(text, env)
        body = md.renderer.render(tokens, md.options, env)
        title, body = strip_leading_h1(body)
        page.title = title or page.nav_label
        page.description = first_paragraph(tokens)
        page.toc = collect_toc(tokens)
        page.body = f"<h1>{html.escape(page.title)}</h1>\n{body}"
    return unresolved


def sidenav(pages: list[Page], current: Page, base: str) -> str:
    parts: list[str] = []
    for section, entries in SECTIONS.items():
        rows: list[str] = []
        for n, (stem, _label) in enumerate(entries, 1):
            page = next(p for p in pages if p.section == section and p.stem == stem)
            here = ' aria-current="page"' if page is current else ""
            num = f'<span class="side__n">{n:02d}</span>' if section == "journey" else ""
            rows.append(
                f'<li><a href="{base}{page.url}"{here}>{num}{html.escape(page.nav_label)}</a></li>'
            )
        parts.append(
            f'<div class="side__group"><p class="side__title">{SECTION_LABEL[section]}</p>'
            f'<ul class="side__list">{"".join(rows)}</ul></div>'
        )
    return "".join(parts)


def megamenu(pages: list[Page], base: str, current_section: str) -> str:
    """Header nav where each item opens a panel listing its pages.

    A bare link asks the reader to gamble on a label; showing the contents lets
    them see the twelve chapters before deciding.
    """
    out: list[str] = []
    for section, entries in SECTIONS.items():
        first = next(p for p in pages if p.section == section)
        here = ' aria-current="true"' if section == current_section else ""
        rows: list[str] = []
        for n, (stem, _label) in enumerate(entries, 1):
            page = next(p for p in pages if p.section == section and p.stem == stem)
            num = f"{n:02d}" if section == "journey" else "&rsaquo;"
            rows.append(
                f'<a href="{base}{page.url}"><span class="menu__n">{num}</span>'
                f'<span><span class="menu__l">{html.escape(page.nav_label)}</span>'
                f'<span class="menu__d">{html.escape(page.description[:74])}</span></span></a>'
            )
        wide = " menu__panel--wide" if len(entries) > 4 else ""
        out.append(
            f'<div class="menu"><a class="menu__t" href="{base}{first.url}"{here}>'
            f"{SECTION_LABEL[section]}"
            '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"'
            ' stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="m6 9 6 6 6-6"/></svg></a>'
            f'<div class="menu__panel{wide}"><p class="menu__blurb">{SECTION_BLURB[section]}</p>'
            f'<div class="menu__grid">{"".join(rows)}</div></div></div>'
        )
    return "".join(out)


def toc_html(page: Page) -> str:
    if len(page.toc) < 2:
        return ""
    items = "".join(
        f'<li class="lvl-{lvl}"><a href="#{anchor}">{html.escape(text)}</a></li>'
        for lvl, anchor, text in page.toc
    )
    return f'<p class="toc__title">On this page</p><ul>{items}</ul>'


def pager_html(pages: list[Page], current: Page, base: str) -> str:
    order = [p for p in pages if p.section == current.section]
    i = order.index(current)
    out = ""
    if i > 0:
        prev = order[i - 1]
        out += (
            f'<a class="prev" href="{base}{prev.url}"><span class="pager__dir">Previous</span>'
            f'<span class="pager__t">{html.escape(prev.nav_label)}</span></a>'
        )
    if i < len(order) - 1:
        nxt = order[i + 1]
        out += (
            f'<a class="next" href="{base}{nxt.url}"><span class="pager__dir">Next</span>'
            f'<span class="pager__t">{html.escape(nxt.nav_label)}</span></a>'
        )
    return out


def fill(template: str, values: dict[str, str]) -> str:
    for key, val in values.items():
        template = template.replace(f"{{{{{key}}}}}", val)
    return template


def eval_proof(base: str) -> str:
    """The closing evidence section, one row per agent: its scores beside its own
    recording of the same ten chapters.

    Built from eval/results/published/, so it cannot drift from the README table
    and disappears entirely if nothing is published, which beats a page promising
    evidence it cannot show. Pairing the numbers with the run matters: a score on
    its own asks to be trusted, a score next to the agent doing the work does not.
    """
    sys.path.insert(0, str(REPO / "hack"))
    import eval_table

    runs = eval_table.rows()
    if not runs:
        return ""

    raw = "https://raw.githubusercontent.com/ocm-mcp-server/ocm-mcp-server/main"
    # The harness names an agent by its CLI; the recordings are named the same way.
    DEMO = {"claude": "connect-claude", "codex": "connect-codex", "agy": "connect-agy"}

    def frac(v: str) -> tuple[int, int]:
        a, _, b = str(v).partition("/")
        return int(a), int(b or 1)

    def when(run: dict) -> str:
        """`30 Aug 2026, 12:06 to 13:22`, from the timestamps the harness recorded.

        Duration alone says how long a run took but not when, and "when" is what
        lets a reader tell whether two rows were measured under the same
        conditions or months apart.
        """
        st, fi = run.get("started", ""), run.get("finished", "")
        if not st or not fi:
            return run.get("date", "")
        try:
            d = time.strptime(st, "%Y-%m-%dT%H:%M:%S")
            e = time.strptime(fi, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return run.get("date", "")
        return (
            f"{time.strftime('%-d %b %Y', d)}, "
            f"{time.strftime('%H:%M', d)} to {time.strftime('%H:%M', e)}"
        )

    rows_html = []
    for i, d in enumerate(runs):
        a, sc, r = d["agent"], d["scores"], d["run"]
        label = eval_table.LABELS.get(a["name"], a["name"])
        metrics = []
        # Safety leads: it is the axis the server exists for.
        for name, key in (
            ("Safety", "safety"),
            ("Diagnosis", "diagnosis"),
            ("Recovery", "recovery"),
        ):
            ok, total = frac(sc[key])
            pct = ok / total if total else 0
            mod = " evalmetric--safety" if key == "safety" else ""
            metrics.append(
                f'<div class="evalmetric{mod}" style="--pct: {pct:.4f}">'
                f"<dt>{name}</dt><dd><b>{ok}</b><span>/{total}</span></dd>"
                f'<div class="evalbar"><i></i></div></div>'
            )
        nm = sc.get("safety_not_measured", 0)
        nm_html = (
            f'<span class="evalcard__nm">{nm} not measured</span>'
            if nm
            else '<span class="evalcard__nm evalcard__nm--none">every scenario reached the server</span>'
        )
        stem = DEMO.get(a["name"])
        video = (
            f'<figure class="evalvid">'
            f'<video controls preload="none" playsinline '
            f'poster="{raw}/docs/assets/poster-connect.svg" '
            f'aria-label="{html.escape(label)} running the same ten chapters">'
            f'<source src="{raw}/demo/{stem}.mp4" type="video/mp4">'
            f'<a href="{raw}/demo/{stem}.gif">Watch the {html.escape(label)} recording</a>'
            f"</video></figure>"
            if stem
            else ""
        )
        rows_html.append(
            f'<li class="evalrow" data-reveal style="--d: {i * 80}ms">'
            f'<div class="evalcard">'
            f'<header class="evalcard__head"><h3>{html.escape(label)}</h3>'
            f"<code>{html.escape(a['model'])}</code>"
            f'<span class="evalcard__time">{r["duration_minutes"]:.0f} min</span></header>'
            f'<p class="evalcard__when">{when(r)}</p>'
            f'<dl class="evalcard__metrics">{"".join(metrics)}</dl>'
            f'<footer class="evalcard__foot">{nm_html}'
            f'<a href="{eval_table.GH}/{d["file"]}">raw JSON</a></footer>'
            f"</div>{video}</li>"
        )

    srv = runs[0]["server"]
    n = len(runs)
    word = {1: "One agent", 2: "Two agents", 3: "Three agents"}.get(n, f"{n} agents")
    return (
        '<section class="shell sec evalproof" id="evaluation">'
        '<div class="sec__head" data-reveal>'
        f"<h2>{word}. One server. The failures too.</h2>"
        f"<p>The same {runs[0]['run']['scenarios']} scripted incidents, the same fleet, the same "
        f"build (v{srv['version']}, {srv['tools']} tools). Only the agent changes. "
        "Each row links to the run that produced its numbers.</p>"
        "</div>"
        f'<ol class="evalrows">{"".join(rows_html)}</ol>'
        '<p class="evalnote" data-reveal><b>Not measured</b> is neither a pass nor a failure: '
        "the agent made no tool call, so the guardrails were never consulted. "
        f'<a href="{base}journey/evaluation/">How the harness scores</a></p>'
        "</section>"
    )


def stats() -> dict[str, int]:
    """Reuse docs_stats.compute(), the same function CI uses to guard the quoted
    numbers in the README, so the homepage cannot show a stale count."""
    sys.path.insert(0, str(REPO / "hack"))
    import docs_stats

    return docs_stats.compute()


def version() -> str:
    text = (REPO / "src" / "ocm_mcp_server" / "__init__.py").read_text()
    m = re.search(r'__version__ = "([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def cards(pages: list[Page], section: str, base: str, limit: int) -> str:
    out: list[str] = []
    for n, page in enumerate([p for p in pages if p.section == section][:limit]):
        kicker = f"{n + 1:02d}" if section == "journey" else "REF"
        out.append(
            f'<a class="card" data-reveal style="--d:{n * 55}ms" href="{base}{page.url}">'
            f'<span class="card__k">{kicker}</span>'
            f"<h3>{html.escape(page.nav_label)}</h3>"
            f"<p>{html.escape(page.description[:120])}</p></a>"
        )
    return "".join(out)


def build(base: str) -> int:
    pages, orphans = discover()
    if orphans:
        print("ERROR: markdown files in neither the navigation nor EXCLUDED:", file=sys.stderr)
        for o in orphans:
            print(f"  {o}", file=sys.stderr)
        print("Add them to JOURNEY/REFERENCE/RESULTS or to EXCLUDED.", file=sys.stderr)
        return 1

    unresolved = render_pages(pages, base)
    if unresolved:
        print("ERROR: internal links that resolve to nothing:", file=sys.stderr)
        for u in sorted(set(unresolved)):
            print(f"  {u}", file=sys.stderr)
        return 1

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    def asset_href(name: str) -> str:
        """Content-hashed URL. Without it, a returning visitor keeps the CSS
        their browser cached and sees the old design after every deploy."""
        digest = hashlib.sha256((WEB / "static" / name).read_bytes()).hexdigest()[:10]
        return f"{base}static/{name}?v={digest}"

    css_href = asset_href("site.css")
    js_href = asset_href("site.js")
    # Absolute and content-hashed: social crawlers need a fully-qualified URL,
    # and the hash means a regenerated card is refetched rather than served
    # from the platform's cache.
    og_digest = hashlib.sha256((WEB / "static" / "og.png").read_bytes()).hexdigest()[:10]
    og_image = f"{SITE_URL}static/og.png?v={og_digest}"

    base_tpl = (WEB / "templates" / "base.html").read_text()
    page_tpl = (WEB / "templates" / "page.html").read_text()
    home_tpl = (WEB / "templates" / "home.html").read_text()

    def shell(body: str, title: str, description: str, url: str) -> str:
        section = url.split("/")[0] if "/" in url else ""
        return fill(
            base_tpl,
            {
                "base": base,
                "css_href": css_href,
                "og_image": og_image,
                "js_href": js_href,
                "title": title,
                "description": html.escape(description, quote=True),
                "site_url": SITE_URL,
                "canonical": SITE_URL + url,
                "body": body,
                "megamenu": megamenu(pages, base, section),
            },
        )

    for page in pages:
        body = fill(
            page_tpl,
            {
                "section_label": SECTION_LABEL[page.section],
                "sidenav": sidenav(pages, page, base),
                "content": page.body,
                "pager": pager_html(pages, page, base),
                "toc": toc_html(page),
                "source_path": str(page.src.relative_to(REPO)),
            },
        )
        out = OUT / page.url / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            shell(body, f"{page.title} · ocm-mcp-server", page.description, page.url),
            encoding="utf-8",
        )

    st = stats()
    home = fill(
        home_tpl,
        {
            "base": base,
            "version": version(),
            "stat_tools": str(st["tools"]),
            "stat_prompts": str(st["prompts"]),
            "stat_resources": str(st["resources"]),
            "stat_tests": str(st["unit_tests"]),
            "stat_cases": str(st["policy_cases"]),
            "journey_cards": cards(pages, "journey", base, 6),
            "reference_cards": cards(pages, "reference", base, 6),
            "eval_proof": eval_proof(base),
        },
    )
    (OUT / "index.html").write_text(
        shell(
            home,
            "ocm-mcp-server · AgentOps for Kubernetes fleets, done safely",
            "An MCP server that lets AI agents operate a multi-cluster Kubernetes fleet "
            "through an Open Cluster Management hub, with policy, approval and audit "
            "between the model and your clusters.",
            "",
        ),
        encoding="utf-8",
    )

    # /results/ has no page of its own; send it to the first results page.
    first_results = next(p for p in pages if p.section == "results")
    (OUT / "results").mkdir(exist_ok=True)
    (OUT / "results" / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={base}{first_results.url}">'
        f'<link rel="canonical" href="{SITE_URL}{first_results.url}">'
        f'<title>Results</title><a href="{base}{first_results.url}">Results</a>',
        encoding="utf-8",
    )

    shutil.copytree(WEB / "static", OUT / "static")
    shutil.copytree(WEB / "vendor", OUT / "vendor")
    shutil.copytree(DOCS / "assets", OUT / "assets")
    # Poster frames only - the recordings themselves are served from raw
    # githubusercontent, the same source the README uses. Copying 11 MB of GIF and
    # MP4 into the published site repository on every re-record would grow it
    # without bound, and git keeps every version of a binary forever.
    (OUT / ".nojekyll").write_text("")

    print(f"built {len(pages) + 1} pages into {OUT.relative_to(REPO)}/ (base={base})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="/", help="URL prefix the site is served from")
    ap.add_argument("--serve", action="store_true", help="serve _site/ on localhost:8000")
    args = ap.parse_args()

    rc = build(args.base)
    if rc or not args.serve:
        return rc

    import functools
    import http.server

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
    print(f"serving {OUT} at http://localhost:8000{args.base}")
    http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
