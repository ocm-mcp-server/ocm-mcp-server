# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""Edge-case coverage for config (env parsing, chmod fallback) and filelock."""

from pathlib import Path

from ocm_mcp_server import config, filelock


def test_spoke_contexts_parsed_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OCM_MCP_HOME", str(tmp_path))
    monkeypatch.setenv("OCM_MCP_SPOKE_CONTEXTS", "c1=kind-c1, c2 = kind-c2 ,malformed")
    settings = config.Settings()
    # Whitespace is stripped, and a pair without '=' is skipped rather than crashing.
    assert settings.spoke_contexts == {"c1": "kind-c1", "c2": "kind-c2"}


def test_tighten_swallows_chmod_failure(monkeypatch, tmp_path):
    p = tmp_path / "f"
    p.write_text("x")

    def boom(self, mode, **kwargs):
        raise OSError("chmod not supported on this filesystem")

    monkeypatch.setattr(Path, "chmod", boom)
    config._tighten(p, 0o600)  # best-effort: must not raise
    assert p.read_text() == "x"  # and must not touch the file's contents


def test_locked_is_noop_without_fcntl(monkeypatch, tmp_path):
    monkeypatch.setattr(filelock, "_HAVE_FCNTL", False)
    target = tmp_path / "state.json"
    with filelock.locked(target):
        target.write_text("{}")
    assert target.read_text() == "{}"  # the body still ran
    assert not (tmp_path / "state.json.lock").exists()  # and no lock file was created
