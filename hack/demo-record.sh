#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
#
# Record the operator demo for one agent, and render the GIF and MP4 the README
# embeds.
#
#   ./hack/demo-record.sh claude
#   ./hack/demo-record.sh codex
#   ./hack/demo-record.sh both        # one fleet, both agents, back to back
#
# Produces demo/connect-<agent>.{cast,gif,mp4}. Assumes a fleet is already up
# (SPOKES=3 ./hack/bootstrap.sh); it does not create or delete clusters, so the
# same fleet can serve both recordings.
#
# Each chapter is a real model call against the real MCP server, so this costs
# quota and the wording differs run to run. hack/demo-connect.sh is the script
# being recorded; DRY_RUN=1 on that prints the chapters without calling anything.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

for t in asciinema agg ffmpeg; do
  command -v "$t" >/dev/null || { echo "missing: $t" >&2; exit 1; }
done

record_one() {
  local agent="$1"
  local cast="demo/connect-${agent}.cast"
  local gif="demo/connect-${agent}.gif"
  local mp4="demo/connect-${agent}.mp4"

  command -v "$agent" >/dev/null || { echo "== skipping ${agent}: not installed"; return 0; }

  echo "== recording ${agent} -> ${cast}"
  # --title is carried in the cast header and shown by the asciinema player; the
  # original recording had one, and a re-record without it loses that.
  AGENT="$agent" asciinema rec "$cast" --overwrite --idle-time-limit 4 \
    --title "ocm-mcp-server - a fleet operator's day with ${agent}" \
    --command "AGENT=${agent} ./hack/demo-connect.sh" </dev/null
  echo "   cast: $(wc -c <"$cast" | tr -d ' ') bytes"

  echo "== rendering ${gif}"
  agg --idle-time-limit 4 "$cast" "$gif" >/dev/null 2>&1
  echo "   gif: $(wc -c <"$gif" | tr -d ' ') bytes"

  echo "== rendering ${mp4}"
  # yuv420p and even dimensions, or QuickTime and GitHub's player refuse it.
  ffmpeg -y -i "$gif" -movflags faststart -pix_fmt yuv420p \
    -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" "$mp4" >/dev/null 2>&1
  echo "   mp4: $(wc -c <"$mp4" | tr -d ' ') bytes"
}

case "${1:-claude}" in
  claude) record_one claude ;;
  codex)  record_one codex ;;
  both)   record_one claude; record_one codex ;;
  *) echo "usage: $0 [claude|codex|both]" >&2; exit 2 ;;
esac
echo "== done"
