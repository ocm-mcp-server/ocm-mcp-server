#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# Publish the version-controlled wiki/ pages to the GitHub wiki.
#
# One-time prerequisite: the wiki must be initialized once via the GitHub UI
# (repo -> Wiki -> "Create the first page" -> Save any content). After that,
# run this script whenever wiki/ changes.
#
# Usage: ./hack/publish-wiki.sh
set -euo pipefail

REPO_SSH="git@github.com:sandeepbazar/ocm-mcp-server.wiki.git"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"

echo "Cloning wiki repo..."
if ! git clone "$REPO_SSH" "$TMP" 2>/dev/null; then
  echo "ERROR: could not clone the wiki repo."
  echo "Initialize it once in the browser (repo -> Wiki -> Create the first page),"
  echo "then re-run this script."
  exit 1
fi

echo "Syncing wiki/ pages..."
cp "$HERE"/wiki/*.md "$TMP"/
# Non-page assets served raw from the wiki repo (e.g. the Shields coverage badge).
cp "$HERE"/wiki/*.json "$TMP"/ 2>/dev/null || true

cd "$TMP"
git add -A
if git diff --cached --quiet; then
  echo "No changes to publish."
  exit 0
fi
git commit -s -m "docs: sync wiki from repo wiki/ pages"
git push origin HEAD
echo "Wiki published: https://github.com/sandeepbazar/ocm-mcp-server/wiki"
rm -rf "$TMP"
