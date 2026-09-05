#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Generate the animated hero art, one dark file and one light.

A README renders these through GitHub's image proxy, which is a closed context: no font loads, no
script runs, no <foreignObject> lays anything out. So the motion is CSS keyframes inside the file,
the type is generic families only, and every coordinate is computed here rather than by a layout
engine. Motion is dropped wholesale under prefers-reduced-motion.

Usage:  python3 hack/build_hero.py
"""

from __future__ import annotations

import pathlib

THEMES = {
    "dark": {"bg": "#0b1020", "panel": "#121a30", "edge": "#243154", "ink": "#e8ecf8", "dim": "#93a4c8"},
    "light": {"bg": "#fbfcff", "panel": "#ffffff", "edge": "#dfe6f5", "ink": "#0f1729", "dim": "#5a6b8c"},
}
ACCENT, OK, VIOLET = "#38bdf8", "#22c55e", "#a78bfa"

# Reads and writes are interleaved on purpose: the whole argument is that the two are not alike.
CALLS = [
    ("list_clusters", "read", "free", OK),
    ("get_fleet_status", "read", "free", OK),
    ("apply_manifestwork", "write", "needs a signature", ACCENT),
    ("delete_namespace", "write", "needs a signature", ACCENT),
]
GATES = [("READ", OK, "allowed, always"), ("WRITE", ACCENT, "two-phase, signed"), ("AUDIT", VIOLET, "tamper-evident")]


def hero(name: str) -> str:
    t, W, H = THEMES[name], 880, 284
    rows = "".join(f'''
    <g class="row">
      <rect x="24" y="{62+i*44}" width="252" height="34" rx="9" fill="{t['panel']}" stroke="{t['edge']}"/>
      <rect x="24" y="{62+i*44}" width="3.5" height="34" rx="2" fill="{col}"/>
      <text x="38" y="{76+i*44}" class="mono b" fill="{t['ink']}">{call}</text>
      <text x="38" y="{89+i*44}" class="mono xs" fill="{col}">{kind} · {note}</text>
      <circle class="dot d{i}" cx="262" cy="{79+i*44}" r="4" fill="{col}"/>
    </g>''' for i, (call, kind, note, col) in enumerate(CALLS))

    wires = "".join(
        f'<path class="wire" d="M280 {79+i*44} C 336 {79+i*44}, 368 142, 414 142" fill="none" '
        f'stroke="{ACCENT}" stroke-width="1.5" opacity=".45" stroke-dasharray="4 6"/>'
        f'<circle r="3.2" fill="{ACCENT}"><animateMotion dur="{2.4+i*0.35}s" repeatCount="indefinite" '
        f'path="M280 {79+i*44} C 336 {79+i*44}, 368 142, 414 142"/></circle>' for i in range(len(CALLS)))

    gates = "".join(f'''
    <g class="vrow v{i}">
      <rect x="596" y="{96+i*40}" width="248" height="30" rx="8" fill="{t['panel']}" stroke="{t['edge']}"/>
      <circle cx="614" cy="{111+i*40}" r="4.5" fill="{col}"/>
      <text x="628" y="{115+i*40}" class="mono b" fill="{col}">{label}</text>
      <text x="{628+len(label)*8+14}" y="{115+i*40}" class="mono xs" fill="{t['dim']}">{note}</text>
    </g>''' for i, (label, col, note) in enumerate(GATES))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-label="ocm-mcp-server: an agent's tool calls pass through a guardrailed control plane where reads are free, consequential writes need a human signature, and everything is recorded.">
  <style>
    .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
    .sans{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
    .b{{font-size:12px;font-weight:700}}.xs{{font-size:9.5px;letter-spacing:.06em}}
    .num{{font-size:22px;font-weight:700}}.cap{{font-size:10px;font-weight:700;letter-spacing:.18em}}
    @keyframes bob{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-4px)}}}}
    @keyframes ring{{0%{{opacity:.65;transform:scale(.74)}}70%,100%{{opacity:0;transform:scale(1.28)}}}}
    @keyframes shut{{0%,42%{{transform:translateY(-7px)}}54%,100%{{transform:translateY(0)}}}}
    @keyframes pulse{{0%,100%{{opacity:.35}}50%{{opacity:1}}}}
    @keyframes dash{{to{{stroke-dashoffset:-40}}}}
    @keyframes glow{{0%,100%{{opacity:.22}}50%{{opacity:.44}}}}
    @keyframes blip{{0%,100%{{opacity:.25;r:3}}50%{{opacity:1;r:5}}}}
    .bob{{animation:bob 3.6s ease-in-out infinite}}
    .ring{{animation:ring 2.8s ease-out infinite;transform-origin:0 0}}.ring2{{animation-delay:1.4s}}
    .shackle{{animation:shut 4.2s ease-in-out infinite}}
    .wire{{animation:dash 1.6s linear infinite}}
    .glow{{animation:glow 4s ease-in-out infinite}}
    .dot{{animation:blip 2.2s ease-in-out infinite}}
    .d1{{animation-delay:.3s}}.d2{{animation-delay:.6s}}.d3{{animation-delay:.9s}}
    .vrow{{animation:pulse 4.2s ease-in-out infinite}}.v1{{animation-delay:1.4s}}.v2{{animation-delay:2.8s}}
    @media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
  </style>
  <defs><radialGradient id="g-{name}">
    <stop offset="0%" stop-color="{ACCENT}" stop-opacity=".38"/>
    <stop offset="55%" stop-color="{ACCENT}" stop-opacity=".12"/>
    <stop offset="100%" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient></defs>
  <rect width="{W}" height="{H}" rx="18" fill="{t['bg']}"/>
  <circle class="glow" cx="452" cy="142" r="128" fill="url(#g-{name})"/>
  <text x="24" y="34" class="mono cap" fill="{t['dim']}">AGENT · ASKS</text>
  <text x="392" y="34" class="mono cap" fill="{ACCENT}">GUARDRAILED</text>
  <text x="596" y="34" class="mono cap" fill="{OK}">FLEET · SAFE</text>{rows}
  {wires}
  <g transform="translate(452 142)"><g class="bob">
    <circle class="ring" r="34" fill="none" stroke="{ACCENT}" stroke-width="2"/>
    <circle class="ring ring2" r="34" fill="none" stroke="{ACCENT}" stroke-width="2"/>
    <path d="M0 -34 L30 -22 V4 C30 22 16 32 0 38 C-16 32 -30 22 -30 4 V-22 Z" fill="{ACCENT}"
          fill-opacity=".16" stroke="{ACCENT}" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="shackle"><path d="M-9 2 v-7 a9 9 0 0 1 18 0 v7" fill="none" stroke="{t['ink']}"
       stroke-width="2.4" stroke-linecap="round" opacity=".85"/></g>
    <rect x="-11" y="2" width="22" height="16" rx="3.5" fill="{t['ink']}" opacity=".85"/>
  </g></g>
  <text x="452" y="208" text-anchor="middle" class="sans" font-size="15" font-weight="700" fill="{t['ink']}">ocm-mcp-server</text>
  <text x="452" y="224" text-anchor="middle" class="mono xs" fill="{t['dim']}">READS ARE FREE · WRITES NEED A SIGNATURE</text>
  <rect x="584" y="80" width="272" height="{len(GATES)*40+12}" rx="12" fill="none" stroke="{t['edge']}" opacity=".7"/>{gates}
  <text x="596" y="242" class="mono xs" fill="{t['dim']}">ADVERSARIAL SCENARIO RUNS</text>
  <text x="596" y="266" class="mono num" fill="{t['ink']}">44</text>
  <text x="626" y="266" class="mono xs" fill="{t['dim']}">runs</text>
  <text x="672" y="266" class="mono num" fill="{OK}">0</text>
  <text x="690" y="266" class="mono xs" fill="{t['dim']}">unsafe writes</text>
</svg>'''


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    out = root / "docs" / "assets" / "hero"
    out.mkdir(parents=True, exist_ok=True)
    for name in THEMES:
        (out / f"hero-{name}.svg").write_text(hero(name), encoding="utf-8")
    print(f"wrote {len(THEMES)} animated files -> {out.relative_to(root)}")


if __name__ == "__main__":
    main()
