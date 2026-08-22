# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""The site builder's two invariants, plus the link rewriting they rest on.

The builder itself lives in hack/ and is not part of the shipped package, so it
is outside the coverage gate. These tests exist because the two failure modes
are silent: a page dropped from the navigation still builds, and a broken
internal link still renders. Both would only be noticed by a reader.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "hack"))

build_site = pytest.importorskip("build_site", reason="needs the [site] extra")


def test_every_markdown_page_is_either_published_or_excluded():
    """A new page in wiki/ or docs/ must be navigated to or explicitly skipped.

    Without this, adding a page silently publishes nothing and nobody notices.
    """
    _pages, orphans = build_site.discover()
    assert orphans == [], (
        f"these markdown files are in neither the navigation nor EXCLUDED: {orphans}. "
        "Add them to JOURNEY/REFERENCE/RESULTS, or to EXCLUDED with a reason."
    )


def test_excluded_entries_all_exist():
    """EXCLUDED must not accumulate stale paths that hide a real omission."""
    missing = [rel for rel in build_site.EXCLUDED if not (REPO / rel).exists()]
    assert missing == [], f"EXCLUDED lists files that no longer exist: {missing}"


def test_navigation_has_no_duplicate_urls():
    pages, _ = build_site.discover()
    urls = [p.url for p in pages]
    assert len(urls) == len(set(urls))


def test_every_internal_link_resolves():
    """The whole-site link check, which is also what fails the Pages build."""
    pages, _ = build_site.discover()
    unresolved = build_site.render_pages(pages, "/")
    assert unresolved == [], f"internal links pointing at nothing: {sorted(set(unresolved))}"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        # Wiki links are bare page names, with no .md suffix.
        ("Guardrails-Deep-Dive", "/journey/guardrails-deep-dive/"),
        # Docs links carry .md.
        ("architecture.md", "/reference/architecture/"),
        # Anchors survive the rewrite.
        ("Evaluation#results", "/journey/evaluation/#results"),
        # Both wikis' "Home" and docs' "index" mean the site root.
        ("Home", "/"),
        # External links are never touched.
        ("https://example.com/x", "https://example.com/x"),
        ("#section", "#section"),
        ("mailto:a@b.c", "mailto:a@b.c"),
    ],
)
def test_link_resolution(href, expected):
    pages, _ = build_site.discover()
    unresolved: list[str] = []
    resolve = build_site.make_resolver(pages, "/", unresolved)
    assert resolve(href, {"page": "test"}) == expected
    assert unresolved == []


def test_repo_relative_paths_point_at_github():
    """deploy/ and examples/ are not site pages; they live on GitHub."""
    pages, _ = build_site.discover()
    resolve = build_site.make_resolver(pages, "/", [])
    assert resolve("deploy/rbac.yaml", {}) == f"{build_site.GH}/blob/main/deploy/rbac.yaml"
    assert resolve("examples/", {}) == f"{build_site.GH}/tree/main/examples/"


def test_unknown_page_is_reported_not_silently_kept():
    pages, _ = build_site.discover()
    unresolved: list[str] = []
    resolve = build_site.make_resolver(pages, "/", unresolved)
    resolve("No-Such-Page", {"page": "wiki/Fake.md"})
    assert unresolved == ["wiki/Fake.md -> No-Such-Page"]


def test_slugify():
    assert build_site.slugify("Why-This-Exists") == "why-this-exists"
    assert build_site.slugify("kubeconfig-contexts") == "kubeconfig-contexts"
    assert build_site.slugify("FAQ") == "faq"


def test_mermaid_fences_become_client_rendered_hosts():
    """Mermaid must not reach the page as an ordinary code block: Pages renders
    no mermaid at all, so the fence becomes a host div the browser fills in."""
    md = build_site.make_markdown(lambda href, env: href)
    out = md.render("```mermaid\nflowchart LR\n  a-->b\n```")
    assert 'class="mermaid-wrap"' in out
    assert "data-src=" in out
    # Not left as a syntax-highlighted fence, which is what Pages would show.
    assert 'class="language-mermaid"' not in out


def test_mermaid_keeps_a_readable_source_fallback():
    """The diagram source must exist as real text, not only as an attribute.

    Without JavaScript - or when the vendored mermaid fails to load - the
    source block is the only thing a reader gets. If it lives solely in
    data-src, the page shows a permanent "rendering diagram..." placeholder.
    """
    md = build_site.make_markdown(lambda href, env: href)
    out = md.render("```mermaid\nflowchart LR\n  a-->b\n```")
    assert 'class="mermaid-src"' in out
    # The actual diagram text, readable without executing anything.
    assert "flowchart LR" in out.split('class="mermaid-src"')[1]


def test_tables_get_a_scroll_container():
    md = build_site.make_markdown(lambda href, env: href)
    out = md.render("| a | b |\n| --- | --- |\n| 1 | 2 |")
    assert '<div class="table-wrap"><table>' in out
    assert "</table></div>" in out
