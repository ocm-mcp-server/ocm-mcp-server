# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ocm_mcp_server.config import SETTINGS


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Point all server state (secret, proposals, audit) at a temp directory."""
    monkeypatch.setattr(SETTINGS, "home", tmp_path)
    return tmp_path
