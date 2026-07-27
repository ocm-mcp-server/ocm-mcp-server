# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0

# Makes `tests` a regular package so cross-file imports like
# `from tests.test_csr import ...` resolve identically under `pytest`
# (the console script, used by CI) and `python -m pytest` (which happens
# to add the repo root to sys.path).
