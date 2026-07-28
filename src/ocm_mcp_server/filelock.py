# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

"""A small advisory file lock so concurrent processes serialize on shared state.

The proposal store and the spent-token store are plain files. Two apply calls (or a
CLI and the server) can race on them, so mutations take an exclusive lock on a sibling
`<path>.lock` first. POSIX `fcntl.flock` is used where available; on platforms without
it the context manager is a no-op (single-process use is still correct).

Platform support: this module imports `fcntl`, which does not exist on Windows, so
`_HAVE_FCNTL` is False there and `locked()` silently becomes a no-op - no exclusive
lock is actually taken, so two processes racing on the same proposal/token store on
Windows are not serialized. Windows is unsupported for this reason; run under WSL2
(a real Linux kernel, so `fcntl` is available) instead.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

try:
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-POSIX
    _HAVE_FCNTL = False


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on `<path>.lock` for the duration of the block."""
    if not _HAVE_FCNTL:
        yield
        return
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fd:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
