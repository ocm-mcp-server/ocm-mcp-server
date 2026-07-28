# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Tests for paged hub reads (paged_list): continue-following, bounds, truncation."""

from __future__ import annotations

from typing import Any

import pytest

from ocm_mcp_server import ocm
from ocm_mcp_server.ocm import paged_list


class FakeListFn:
    """A list function serving canned pages, recording how it was called."""

    def __init__(self, pages: list[dict[str, Any]]):
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.pages[len(self.calls) - 1]


def test_single_page_passes_limit_and_returns_items() -> None:
    fn = FakeListFn([{"items": [{"a": 1}, {"a": 2}], "metadata": {}}])
    res = paged_list(fn, "group", "v1", "things")
    assert res == {"items": [{"a": 1}, {"a": 2}]}
    assert fn.calls == [
        {"args": ("group", "v1", "things"), "kwargs": {"limit": ocm.LIST_PAGE_SIZE}}
    ]


def test_follows_continue_tokens_across_pages() -> None:
    fn = FakeListFn(
        [
            {"items": [{"a": 1}], "metadata": {"continue": "tok-1"}},
            {"items": [{"a": 2}], "metadata": {"continue": "tok-2"}},
            {"items": [{"a": 3}], "metadata": {}},
        ]
    )
    res = paged_list(fn)
    assert [i["a"] for i in res["items"]] == [1, 2, 3]
    assert "truncated" not in res
    assert "_continue" not in fn.calls[0]["kwargs"]
    assert fn.calls[1]["kwargs"]["_continue"] == "tok-1"
    assert fn.calls[2]["kwargs"]["_continue"] == "tok-2"


def test_stops_at_max_items_and_reports_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocm, "LIST_MAX_ITEMS", 2)
    fn = FakeListFn(
        [
            {"items": [{"a": 1}], "metadata": {"continue": "more"}},
            {"items": [{"a": 2}], "metadata": {"continue": "even-more"}},
            {"items": [{"a": 3}], "metadata": {"continue": "never-reached"}},
        ]
    )
    res = paged_list(fn)
    assert [i["a"] for i in res["items"]] == [1, 2]
    assert "truncated at 2 items" in res["truncated"]
    assert len(fn.calls) == 2  # the ceiling stopped the walk before page 3


def test_null_items_treated_as_empty() -> None:
    # The apiserver can legally return "items": null for an empty collection.
    fn = FakeListFn([{"items": None, "metadata": {"continue": ""}}])
    assert paged_list(fn) == {"items": []}
