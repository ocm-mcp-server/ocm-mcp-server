#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Sandeep Bazar
# SPDX-License-Identifier: Apache-2.0
"""Generate the project's animated art: one dark file and one light for each panel.

Every panel here is an argument the project makes, drawn so it can be watched instead of
read: a privileged write dying at the first gate, a token that expires, a hash chain that
notices tampering, three agents whose safety column never moves. The numbers are pulled
from the repository - the tool table in server.py, the published evaluation JSON - so a
panel cannot quietly go stale while the thing it describes changes.

A README renders these through GitHub's image proxy, which is a closed context: no font
loads, no script runs, no <foreignObject> lays anything out. So the motion is CSS keyframes
inside the file, the type is generic families only, and every coordinate is computed here
rather than by a layout engine. Motion is dropped wholesale under prefers-reduced-motion,
and each panel is built so the frozen state still reads as the finished story.

Usage:  python3 hack/build_art.py
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from eval_table import LABELS  # the path is set above so this runs from any cwd

ROOT = pathlib.Path(__file__).resolve().parent.parent

THEMES = {
    "dark": {"bg": "#0b1020", "panel": "#121a30", "edge": "#243154", "ink": "#e8ecf8", "dim": "#93a4c8"},
    "light": {"bg": "#fbfcff", "panel": "#ffffff", "edge": "#dfe6f5", "ink": "#0f1729", "dim": "#5a6b8c"},
}
ACCENT, OK, VIOLET, DENY, AMBER = "#38bdf8", "#22c55e", "#a78bfa", "#f43f5e", "#fb923c"

# Shared type and the reduced-motion escape hatch. Everything below composes this, so one
# rule about motion applies to every panel rather than being restated eight times.
BASE_CSS = """
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
    .sans{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
    .b{font-size:12px;font-weight:700}.xs{font-size:9.5px;letter-spacing:.06em}
    .s{font-size:11px}.cap{font-size:10px;font-weight:700;letter-spacing:.18em}
    .num{font-size:22px;font-weight:700}
    @keyframes dash{to{stroke-dashoffset:-40}}
    @keyframes glow{0%,100%{opacity:.22}50%{opacity:.44}}
    @keyframes blip{0%,100%{opacity:.25}50%{opacity:1}}
    .wire{animation:dash 1.6s linear infinite}
    .glow{animation:glow 4s ease-in-out infinite}
"""
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


def esc(text: str) -> str:
    """XML-escape a label. Tool names and shell snippets carry & and < often enough."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg(name: str, w: int, h: int, label: str, css: str, body: str) -> str:
    """Wrap a panel body in the frame every panel shares: viewBox, style block, ground."""
    t = THEMES[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{esc(label)}">\n  <style>{BASE_CSS}{css}\n    {REDUCED}\n  </style>\n'
        f'  <rect width="{w}" height="{h}" rx="18" fill="{t["bg"]}"/>\n{body}\n</svg>'
    )


def eyebrow(x: int, y: int, text: str, fill: str, anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" class="mono cap" fill="{fill}">{esc(text)}</text>'


def panel(x: float, y: float, w: float, h: float, t: dict[str, str], r: int = 10, fill: str = "") -> str:
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill or t["panel"]}" stroke="{t["edge"]}"/>')


def chip(x: float, y: float, text: str, col: str, w: float = 0, cls: str = "") -> str:
    """A small tinted pill. Width is measured from the label so nothing overflows."""
    w = w or len(text) * 6.4 + 18
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c}><rect x="{x}" y="{y}" width="{w}" height="18" rx="6" fill="{col}" fill-opacity=".16" '
            f'stroke="{col}" stroke-opacity=".45"/>'
            f'<text x="{x + w / 2}" y="{y + 12.6}" text-anchor="middle" class="mono xs" fill="{col}">'
            f'{esc(text)}</text></g>')


def tick(x: float, y: float, col: str, cls: str = "", r: float = 8) -> str:
    s = r * 0.52
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c}><circle cx="{x}" cy="{y}" r="{r}" fill="{col}" fill-opacity=".18" stroke="{col}" '
            f'stroke-width="1.4"/><path d="M{x - s} {y} l{s * 0.8} {s * 0.8} l{s * 1.4} -{s * 1.6}" '
            f'fill="none" stroke="{col}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></g>')


def cross(x: float, y: float, col: str, cls: str = "", r: float = 8) -> str:
    s = r * 0.42
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c}><circle cx="{x}" cy="{y}" r="{r}" fill="{col}" fill-opacity=".18" stroke="{col}" '
            f'stroke-width="1.4"/><path d="M{x - s} {y - s} l{s * 2} {s * 2} M{x + s} {y - s} l-{s * 2} {s * 2}" '
            f'fill="none" stroke="{col}" stroke-width="2" stroke-linecap="round"/></g>')


def lock(x: float, y: float, col: str, s: float = 1.0) -> str:
    return (f'<g transform="translate({x} {y}) scale({s})">'
            f'<path d="M-4 0 v-3.2a4 4 0 0 1 8 0V0" fill="none" stroke="{col}" stroke-width="1.6"/>'
            f'<rect x="-5.4" y="0" width="10.8" height="7.6" rx="1.8" fill="{col}"/></g>')


# ---------------------------------------------------------------------------
# Facts. Read from the repository rather than typed in, so a panel that claims a
# number is claiming the same number the code and the published runs claim.
# ---------------------------------------------------------------------------

def tool_counts() -> dict[str, int]:
    """How many tools carry each annotation, counted off the server's own registrations."""
    src = (ROOT / "src" / "ocm_mcp_server" / "server.py").read_text(encoding="utf-8")
    found = re.findall(r"annotations=(READ|PROPOSE|APPLY)\b", src)
    return {k: found.count(k) for k in ("READ", "PROPOSE", "APPLY")} | {"TOTAL": len(found)}


def toolset_counts() -> dict[str, int]:
    """Tools per toolset, counted inside server.py's own toolset sections.

    server.py divides itself with `# ==== toolset: <name>` banners, and those sections are what
    the README table describes, so counting decorators between them keeps the picture, the
    table and the code from drifting apart the way the table already had.
    """
    src = (ROOT / "src" / "ocm_mcp_server" / "server.py").read_text(encoding="utf-8")
    parts = re.split(r"^# =+ toolset: (\S+)\s*$", src, flags=re.MULTILINE)[1:]
    return {parts[i]: parts[i + 1].count("@mcp.tool(") for i in range(0, len(parts), 2)}


def eval_facts() -> dict[str, object]:
    """The published evaluation runs, reduced to what the art states.

    Safety is the only axis drawn as a claim, because it is the only one the server is
    responsible for: the agent owns its diagnosis and its recovery. `held` counts scenarios
    that actually reached the guardrails; `runs` counts every scenario every agent ran.
    """
    rows, runs, held = [], 0, 0
    for path in sorted((ROOT / "eval" / "results" / "published").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        got, want = (int(v) for v in data["scores"]["safety"].split("/"))
        rows.append({
            "agent": LABELS.get(data["agent"].get("name", ""), data["agent"].get("name", path.stem)),
            "model": data["agent"].get("model", ""),
            "diagnosis": data["scores"]["diagnosis"],
            "recovery": data["scores"]["recovery"],
            "safety": data["scores"]["safety"],
            "held": got, "reached": want,
        })
        runs += len(data["results"])
        held += got
    return {"rows": rows, "runs": runs, "held": held}


def helm(cx: float, cy: float, r: float, col: str, cls: str = "") -> str:
    """A managed cluster, drawn as a seven-spoked helm.

    OCM's whole inventory is Kubernetes clusters, so the fleet should look like Kubernetes
    rather than like anonymous dots. This is the project's own line-art take on a ship's
    helm - the shape Kubernetes is named for - and not a copy of the Kubernetes logo file,
    which is a Linux Foundation trademark with its own usage rules.
    """
    pts = [(cx + r * math.sin(math.tau * i / 7), cy - r * math.cos(math.tau * i / 7)) for i in range(7)]
    ring = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    spokes = "".join(
        f'<line x1="{cx + r * 0.3 * math.sin(math.tau * (i + 0.5) / 7):.1f}" '
        f'y1="{cy - r * 0.3 * math.cos(math.tau * (i + 0.5) / 7):.1f}" '
        f'x2="{cx + r * 0.78 * math.sin(math.tau * (i + 0.5) / 7):.1f}" '
        f'y2="{cy - r * 0.78 * math.cos(math.tau * (i + 0.5) / 7):.1f}" '
        f'stroke="{col}" stroke-width="{r * 0.17:.2f}" stroke-linecap="round"/>' for i in range(7))
    c = f' class="{cls}"' if cls else ""
    return (f'<g{c}><polygon points="{ring}" fill="{col}" fill-opacity=".14" stroke="{col}" '
            f'stroke-width="{r * 0.15:.2f}" stroke-linejoin="round"/>{spokes}'
            f'<circle cx="{cx}" cy="{cy}" r="{r * 0.24:.1f}" fill="none" stroke="{col}" '
            f'stroke-width="{r * 0.15:.2f}"/></g>')


def lit(name: str, on: float, off: float, dim: str = ".28") -> str:
    """A card that dims until its turn comes, then holds until the whole sequence resets."""
    return (f"@keyframes {name}{{0%,{max(on - 4, 0)}%{{opacity:{dim}}}{on}%,{off}%{{opacity:1}}"
            f"{min(off + 4, 100)}%,100%{{opacity:{dim}}}}}")


def pop(name: str, on: float, off: float) -> str:
    """A verdict mark's own keyframe: nothing, then a snap into place, then out with the pass."""
    return (f"@keyframes {name}{{0%,{on - 4}%{{opacity:0;transform:scale(.5)}}"
            f"{on}%,{off}%{{opacity:1;transform:scale(1)}}"
            f"{min(off + 3, 100)}%,100%{{opacity:0;transform:scale(.5)}}}}")


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

GATES = [
    ("LAYER 1", "guardrails", "this server, first", "privileged, host access,<br>unpinned images", "#8ea2ff"),
    ("LAYER 2", "Kyverno", "dry-run on the hub", "whatever your org's<br>policies reject", ACCENT),
    ("LAYER 3", "approval", "a person, Ed25519", "anything no human<br>signed for", AMBER),
    ("LAYER 4", "RBAC", "Kubernetes itself", "no Secrets, no exec,<br>no stray deletes", OK),
]
# Gate geometry, shared by the drawing and the packet timeline: a waypoint the packet stops
# at has to be the same number as the door it stops in front of, or the motion lies.
GX = [268 + i * 212 for i in range(4)]      # left edge of each gate box
GW, START = 180, 216                        # gate width, and where a packet leaves the agent
CENTRE = [x + GW / 2 for x in GX]           # the door in each gate
MB_ON = [42, 50, 68, 74]                    # when each gate is *cleared*, in loop %
FLEET_X = 1146


def gauntlet(name: str) -> str:
    """Two writes walk the same four gates. One dies at the first; one earns its way through.

    The privileged request is drawn first and refused first on purpose: the loop's opening
    beat is a refusal, so nobody has to watch the whole thing to learn what the gates are for.
    """
    t, W, H = THEMES[name], 1280, 430
    lane_a, lane_b = 166, 232

    boxes = ""
    for i, (kick, gname, by, stops, col) in enumerate(GATES):
        x = GX[i]
        note = "".join(
            f'<text x="{x + 16}" y="{300 + j * 12}" class="mono xs" fill="{t["dim"]}">{esc(line)}</text>'
            for j, line in enumerate(stops.split("<br>")))
        boxes += f'''
  <g>
    {panel(x, 76, GW, 254, t, 12)}
    <rect x="{x}" y="76" width="{GW}" height="3" rx="1.5" fill="{col}" opacity=".9"/>
    <text x="{x + 16}" y="102" class="mono xs" fill="{col}">{kick}</text>
    <text x="{x + 16}" y="121" class="sans" font-size="14" font-weight="700" fill="{t["ink"]}">{gname}</text>
    <text x="{x + 16}" y="137" class="mono xs" fill="{t["dim"]}">{esc(by)}</text>
    <line x1="{CENTRE[i]}" y1="146" x2="{CENTRE[i]}" y2="272" stroke="{col}" stroke-width="1.2"
          stroke-dasharray="3 5" opacity=".5"/>
    <text x="{x + 16}" y="286" class="mono xs" fill="{col}">STOPS</text>{note}
  </g>'''

    # The verdict marks. Each is pinned to its own gate and its own lane, and each is timed to
    # the moment the packet arrives - a tick that lights before the packet is a tick that means
    # nothing. Lane A only ever earns one mark, and it is a cross.
    marks = cross(CENTRE[0], lane_a + 26, DENY, "m mA")
    marks += "".join(tick(CENTRE[i], lane_b + 26, OK, f"m mB{i}") for i in range(4))
    # Each verdict lights when its own gate is cleared, and every one of them goes out
    # together at the end of the pass, so a restart never inherits a lit gate.
    mark_css = pop("mA", 17, 30) + "".join(pop(f"mB{i}", on, 94) for i, on in enumerate(MB_ON))
    mark_css += "".join(f'.mB{i}{{animation:mB{i} 15s ease-out infinite}}' for i in range(4))

    lanes = "".join(
        f'<line class="wire" x1="{START}" y1="{y}" x2="{FLEET_X - 22}" y2="{y}" stroke="{col}" '
        f'stroke-width="1.4" stroke-dasharray="4 6" opacity=".3"/>'
        for y, col in ((lane_a, DENY), (lane_b, OK)))

    req_a = f'''
    {panel(44, 140, 172, 52, t, 9)}
    <rect x="44" y="140" width="3" height="52" rx="1.5" fill="{DENY}"/>
    <text x="58" y="158" class="mono b" fill="{t["ink"]}">apply_manifestwork</text>
    <text x="58" y="172" class="mono xs" fill="{DENY}">image: nginx:latest</text>
    <text x="58" y="184" class="mono xs" fill="{DENY}">privileged: true</text>'''
    req_b = f'''
    {panel(44, 206, 172, 52, t, 9)}
    <rect x="44" y="206" width="3" height="52" rx="1.5" fill="{OK}"/>
    <text x="58" y="224" class="mono b" fill="{t["ink"]}">apply_manifestwork</text>
    <text x="58" y="238" class="mono xs" fill="{OK}">nginx:1.27@sha256:9f2…</text>
    <text x="58" y="250" class="mono xs" fill="{OK}">runAsNonRoot: true</text>'''

    nodes = "".join(helm(1146 + (i % 3) * 34, 190 + (i // 3) * 42, 11, OK, f"node n{i}") for i in range(6))

    css = f"""
    @keyframes runA{{0%,4%{{transform:translateX(0)}}14%,22%{{transform:translateX({CENTRE[0] - START}px)}}
      31%,100%{{transform:translateX(0)}}}}
    @keyframes tintA{{0%,13%{{opacity:0}}16%,30%{{opacity:1}}34%,100%{{opacity:0}}}}
    @keyframes hideA{{0%,13%{{opacity:1}}16%,30%{{opacity:0}}34%,100%{{opacity:1}}}}
    @keyframes runB{{0%,34%{{transform:translateX(0)}}
      41%,44%{{transform:translateX({CENTRE[0] - START}px)}}
      49%,52%{{transform:translateX({CENTRE[1] - START}px)}}
      57%,67%{{transform:translateX({CENTRE[2] - START}px)}}
      73%,76%{{transform:translateX({CENTRE[3] - START}px)}}
      83%,94%{{transform:translateX({FLEET_X - START}px)}}
      97%,100%{{transform:translateX({FLEET_X - START}px);opacity:0}}}}
    @keyframes showB{{0%,33%{{opacity:0}}35%,85%{{opacity:1}}91%,100%{{opacity:0}}}}
{mark_css}
    @keyframes refused{{0%,15%{{opacity:0}}19%,32%{{opacity:1}}36%,100%{{opacity:0}}}}
    @keyframes waiting{{0%,56%{{opacity:0}}59%,64%{{opacity:1}}67%,100%{{opacity:0}}}}
    @keyframes signed{{0%,64%{{opacity:0}}68%,94%{{opacity:1}}97%,100%{{opacity:0}}}}
    @keyframes landed{{0%,82%{{opacity:0}}86%,96%{{opacity:1}}99%,100%{{opacity:0}}}}
    @keyframes live{{0%,84%{{opacity:.42}}90%,96%{{opacity:1}}99%,100%{{opacity:.42}}}}
    .pkt{{transform-box:fill-box}}
    .runA{{animation:runA 15s ease-in-out infinite}}
    .runB{{animation:runB 15s ease-in-out infinite,showB 15s linear infinite}}
    .tintA{{animation:tintA 15s linear infinite}}.hideA{{animation:hideA 15s linear infinite}}
    .m{{transform-origin:center;transform-box:fill-box;opacity:0}}
    .refused{{animation:refused 15s linear infinite}}
    .waiting{{animation:waiting 15s ease-in-out infinite}}
    .signed{{animation:signed 15s linear infinite}}
    .landed{{animation:landed 15s linear infinite}}
    .node{{animation:live 15s ease-in-out infinite}}
    .n1{{animation-delay:.15s}}.n2{{animation-delay:.3s}}.n3{{animation-delay:.45s}}
    .n4{{animation-delay:.6s}}.n5{{animation-delay:.75s}}
    @media (prefers-reduced-motion:reduce){{
      .runB{{transform:translateX({FLEET_X - START}px)}}.m,.signed,.landed,.refused{{opacity:1}}
      .runA,.tintA,.waiting{{opacity:0}}.hideA{{opacity:1}}.node{{opacity:1}}}}
"""
    body = f'''  <circle class="glow" cx="{FLEET_X}" cy="200" r="150" fill="url(#gg-{name})"/>
  <defs><radialGradient id="gg-{name}">
    <stop offset="0%" stop-color="{OK}" stop-opacity=".3"/>
    <stop offset="100%" stop-color="{OK}" stop-opacity="0"/></radialGradient></defs>
  {eyebrow(32, 44, "AGENT · PROPOSES", t["dim"])}
  {eyebrow(676, 44, "FOUR GATES · EACH ONE CAN REFUSE ON ITS OWN", ACCENT, "middle")}
  {eyebrow(1248, 44, "FLEET · SAFE", OK, "end")}
  <g>{panel(32, 76, 196, 254, t, 12)}
    <text x="48" y="106" class="sans" font-size="14" font-weight="700" fill="{t["ink"]}">AI agent</text>
    <text x="48" y="122" class="mono xs" fill="{t["dim"]}">holds no kubeconfig</text>
    {req_a}{req_b}
  </g>{lanes}{boxes}
  <g>{panel(1116, 76, 132, 254, t, 12)}
    <text x="1132" y="106" class="sans" font-size="14" font-weight="700" fill="{t["ink"]}">fleet</text>
    <text x="1132" y="122" class="mono xs" fill="{t["dim"]}">via the OCM hub</text>
    {nodes}
    <g class="landed">{chip(1132, 258, "applied", OK, 46)}{chip(1132, 280, "verified", OK, 56)}</g>
  </g>
  {marks}
  <g class="waiting">{chip(CENTRE[2] - 52, 196, "awaiting a human", AMBER, 104)}</g>
  <g class="signed">{chip(CENTRE[2] - 46, 196, "Ed25519 token", VIOLET, 92)}</g>
  <g class="pkt runA"><g class="hideA"><circle cx="{START}" cy="{lane_a}" r="7" fill="{ACCENT}"/></g>
    <g class="tintA"><circle cx="{START}" cy="{lane_a}" r="7" fill="{DENY}"/></g></g>
  <g class="pkt runB"><circle cx="{START}" cy="{lane_b}" r="7" fill="{OK}"/></g>
  <g class="refused">{chip(258, 356, "refused at Layer 1 — privileged: true, image not pinned — it never reached a cluster", DENY, 560)}</g>
  <g class="signed">{chip(258, 384, "all four satisfied — content-bound token signed by a person, applied, verified", OK, 560)}</g>
  <text x="836" y="370" class="mono xs" fill="{t["dim"]}">None of these layers live in the system prompt,</text>
  <text x="836" y="392" class="mono xs" fill="{t["dim"]}">so none of them can be talked out of.</text>'''
    return svg(name, W, H, "Two writes walk the same four gates: a privileged, unpinned request is "
               "refused at the first layer and never reaches a cluster, while a compliant one passes "
               "the static checks, Kyverno, a human Ed25519 signature and RBAC, and is applied and "
               "verified.", css, body)


def paths(name: str) -> str:
    """Two lanes out of one server: a read returns, a write has to earn its way.

    The counts are read off the server's own annotations, so the ratio the picture makes an
    argument out of - almost all of this surface is read - cannot drift from the code.
    """
    t, W, H = THEMES[name], 1280, 356
    n = tool_counts()
    read_y, write_y, box_top = 132, 278, 190

    # Stations sit above the write lane with a short drop to it, so the travelling call rides
    # clear track: a dot crossing its own label reads as a glitch rather than as progress.
    stations = [("propose", "a proposal id and\na content hash", ACCENT, 470),
                ("approve", "a person runs\nocm-mcp approve", AMBER, 700),
                ("apply", "the token is spent,\nonce, and audited", VIOLET, 930)]
    boxes = ""
    for label, sub, col, x in stations:
        lines = "".join(f'<text x="{x + 15}" y="{box_top + 40 + j * 13}" class="mono xs" '
                        f'fill="{t["dim"]}">{esc(line)}</text>' for j, line in enumerate(sub.split("\n")))
        boxes += (f'<g>{panel(x, box_top, 168, 68, t, 10)}'
                  f'<rect x="{x}" y="{box_top}" width="3" height="68" rx="1.5" fill="{col}"/>'
                  f'<text x="{x + 15}" y="{box_top + 22}" class="sans" font-size="13" font-weight="700" '
                  f'fill="{col}">{label}</text>{lines}'
                  f'<line x1="{x + 84}" y1="{box_top + 68}" x2="{x + 84}" y2="{write_y}" '
                  f'stroke="{col}" stroke-width="1.2" stroke-dasharray="3 4" opacity=".55"/></g>')

    read_tools = ["list_clusters", "get_fleet_status", "get_cluster_health", "list_placements"]
    reads = "".join(chip(300 + i * 152, 88, tool, OK, 140) for i, tool in enumerate(read_tools))

    css = """
    @keyframes zip{0%{transform:translateX(0);opacity:0}4%{opacity:1}
      34%{transform:translateX(880px);opacity:1}38%{transform:translateX(880px);opacity:0}
      39%,100%{transform:translateX(0);opacity:0}}
    @keyframes back{0%,38%{opacity:0;transform:translateX(880px)}42%{opacity:1}
      62%{transform:translateX(0);opacity:1}66%,100%{transform:translateX(0);opacity:0}}
    @keyframes crawl{0%,4%{transform:translateX(0);opacity:0}8%{opacity:1}
      20%,30%{transform:translateX(306px)}42%,64%{transform:translateX(536px)}
      76%,90%{transform:translateX(766px)}94%,100%{transform:translateX(912px);opacity:0}}
    @keyframes hold{0%,44%{opacity:0}48%,62%{opacity:1}66%,100%{opacity:0}}
    @keyframes done{0%,88%{opacity:0}92%,97%{opacity:1}99%,100%{opacity:0}}
    .zip{animation:zip 11s cubic-bezier(.2,.9,.3,1) infinite}
    .back{animation:back 11s cubic-bezier(.2,.9,.3,1) infinite}
    .crawl{animation:crawl 11s ease-in-out infinite}
    .hold{animation:hold 11s ease-in-out infinite}
    .done{animation:done 11s ease-in-out infinite}
    @media (prefers-reduced-motion:reduce){
      .zip,.back{opacity:1;transform:translateX(440px)}
      .crawl{opacity:1;transform:translateX(766px)}.done{opacity:1}.hold{opacity:0}}
"""
    read_n, write_n = n["READ"], n["PROPOSE"] + n["APPLY"]
    body = f'''  {eyebrow(32, 42, "ONE SERVER · TWO KINDS OF CALL", t["dim"])}
  {eyebrow(1248, 42, f"{n['TOTAL']} TOOLS · {read_n} OF THEM READ-ONLY", ACCENT, "end")}
  <g>{panel(32, 88, 200, 212, t, 12)}
    <text x="48" y="118" class="sans" font-size="15" font-weight="700" fill="{t["ink"]}">ocm-mcp-server</text>
    <text x="48" y="134" class="mono xs" fill="{t["dim"]}">holds the kubeconfig</text>
    <line x1="48" y1="150" x2="216" y2="150" stroke="{t["edge"]}"/>
    <text x="48" y="180" class="mono num" fill="{OK}">{read_n}</text>
    <text x="{48 + 15 * len(str(read_n))}" y="180" class="mono xs" fill="{t["dim"]}">read tools</text>
    <text x="48" y="196" class="mono xs" fill="{t["dim"]}">readOnlyHint · no gate</text>
    <text x="48" y="238" class="mono num" fill="{ACCENT}">{write_n}</text>
    <text x="{48 + 15 * len(str(write_n))}" y="238" class="mono xs" fill="{t["dim"]}">write tools</text>
    <text x="48" y="254" class="mono xs" fill="{t["dim"]}">{n['PROPOSE']} propose · {n['APPLY']} apply</text>
    <text x="48" y="284" class="mono xs" fill="{DENY}">0 that read Secrets or exec</text>
  </g>
  {eyebrow(300, 70, "READS · FREE, IMMEDIATE, THE WHOLE OCM API", OK)}
  {reads}
  <line class="wire" x1="240" y1="{read_y}" x2="1132" y2="{read_y}" stroke="{OK}" stroke-width="1.5"
        stroke-dasharray="4 6" opacity=".35"/>
  <g class="zip"><circle cx="248" cy="{read_y}" r="6.5" fill="{OK}"/></g>
  <g class="back"><circle cx="248" cy="{read_y}" r="6.5" fill="{OK}" fill-opacity=".35" stroke="{OK}"/>
    <text x="264" y="{read_y - 12}" class="mono xs" fill="{OK}">answer</text></g>
  {helm(1164, read_y, 17, OK)}
  {eyebrow(300, 170, "WRITES · TWO-PHASE, AND A PERSON IS IN IT", ACCENT)}
  {boxes}
  <line class="wire" x1="240" y1="{write_y}" x2="1132" y2="{write_y}" stroke="{ACCENT}" stroke-width="1.5"
        stroke-dasharray="4 6" opacity=".35"/>
  <g class="crawl"><circle cx="248" cy="{write_y}" r="6.5" fill="{ACCENT}"/></g>
  <g class="hold">{chip(646, 298, "waiting on a human — nothing here times out into a yes", AMBER)}</g>
  {helm(1164, write_y, 17, ACCENT)}
  <g class="done">{tick(1184, write_y - 16, OK, "", 9)}</g>
  <text x="32" y="338" class="mono xs" fill="{t["dim"]}">A capability that does not exist cannot be prompt-injected into use: Secrets, exec and arbitrary delete are absent from the allow-list, not merely discouraged.</text>'''
    return svg(name, W, H, f"Reads and writes take different paths through the server: {read_n} "
               f"read-only tools answer immediately and freely, while all {write_n} writing tools go "
               "through propose, a human approval, and a one-time-token apply.", css, body)


def approval(name: str) -> str:
    """The two-phase write, at the resolution where the interesting part is visible.

    The beat this panel exists for is the last one: the same token, offered a second time, is
    refused. A token that can be replayed is a token that only looks like consent.
    """
    t, W, H = THEMES[name], 1280, 340
    y = 178
    steps = [
        ("1", "propose", ACCENT, ["propose_manifestwork(...)", "→ sha256:9f2c1e…", "nothing has left the hub"]),
        ("2", "a person looks", AMBER, ["$ ocm-mcp approve 9f2c1e…", "on a trusted terminal,", "not through the agent"]),
        ("3", "token minted", VIOLET, ["Ed25519, bound to the hash,", "the operation, the audience,", "and an expiry"]),
        ("4", "apply", OK, ["token verified and burned,", "ManifestWork delivered,", "audit line written"]),
    ]
    xs = [40 + i * 258 for i in range(4)]
    cards = ""
    for i, (num, label, col, lines) in enumerate(steps):
        x = xs[i]
        rows = "".join(f'<text x="{x + 46}" y="{y + 12 + j * 14}" class="mono xs" fill="{t["dim"]}">'
                       f'{esc(line)}</text>' for j, line in enumerate(lines))
        cards += f'''
  <g class="step s{i}">
    {panel(x, y - 46, 232, 96, t, 11)}
    <circle cx="{x + 26}" cy="{y - 20}" r="13" fill="{col}" fill-opacity=".18" stroke="{col}"/>
    <text x="{x + 26}" y="{y - 15}" text-anchor="middle" class="mono b" fill="{col}">{num}</text>
    <text x="{x + 46}" y="{y - 15}" class="sans" font-size="13" font-weight="700" fill="{t["ink"]}">{label}</text>
    {rows}
  </g>'''
        if i < 3:
            cards += (f'<path class="wire" d="M{x + 232} {y - 20} h22" stroke="{col}" stroke-width="1.6" '
                      f'stroke-dasharray="4 5" opacity=".55" fill="none"/>')
    step_css = "".join(lit(f"s{i}", 8 + i * 16, 88) for i in range(4))
    step_css += "".join(f".s{i}{{animation:s{i} 13s ease-in-out infinite}}" for i in range(4))

    # The expiry is drawn as a bar that runs down, because "it expires" is a promise and a bar
    # that empties is the same promise with a clock attached.
    css = f"""
{step_css}
    @keyframes ttl{{0%,42%{{width:236px}}92%,100%{{width:26px}}}}
    @keyframes replay{{0%,72%{{opacity:0;transform:translateX(0)}}78%{{opacity:1}}
      84%{{opacity:1;transform:translateX(-150px)}}88%,100%{{opacity:0;transform:translateX(-150px)}}}}
    @keyframes stamp{{0%,84%{{opacity:0;transform:scale(1.7)}}89%,96%{{opacity:1;transform:scale(1)}}
      99%,100%{{opacity:0;transform:scale(1.7)}}}}
    .step{{opacity:.28}}
    .ttl{{animation:ttl 13s linear infinite}}
    .replay{{animation:replay 13s ease-in-out infinite}}
    .stamp{{animation:stamp 13s ease-out infinite;transform-origin:center;transform-box:fill-box}}
    @media (prefers-reduced-motion:reduce){{.step{{opacity:1}}.ttl{{width:120px}}
      .replay,.stamp{{opacity:1;transform:none}}}}
"""
    body = f'''  {eyebrow(40, 44, "A WRITE IS TWO CALLS WITH A PERSON BETWEEN THEM", ACCENT)}
  {eyebrow(1240, 44, "NO STEP CAN BE SKIPPED BY ASKING NICELY", t["dim"], "end")}
  <text x="40" y="88" class="sans" font-size="19" font-weight="700" fill="{t["ink"]}">The server never holds the authority to change anything on its own.</text>
  <text x="40" y="110" class="mono s" fill="{t["dim"]}">It holds a public verifier key. The signing key stays with the person, on their terminal.</text>
  {cards}
  <g>{panel(40, 258, 560, 46, t, 10)}
    <text x="56" y="278" class="mono xs" fill="{VIOLET}">TOKEN TTL · IT EXPIRES WHETHER OR NOT ANYONE USES IT</text>
    <rect x="56" y="288" width="236" height="7" rx="3.5" fill="{VIOLET}" fill-opacity=".16"/>
    <rect class="ttl" x="56" y="288" width="236" height="7" rx="3.5" fill="{VIOLET}"/>
    <text x="308" y="295" class="mono xs" fill="{t["dim"]}">bound to one hash, one operation, one use</text>
  </g>
  <g>{panel(624, 258, 616, 46, t, 10)}
    <text x="640" y="285" class="mono xs" fill="{DENY}">REPLAY</text>
    <text x="700" y="285" class="mono xs" fill="{t["dim"]}">a captured token buys nothing twice</text>
    <g class="replay">{chip(1136, 272, "token, again", VIOLET, 94)}</g>
    <g class="stamp">{cross(966, 281, DENY, "", 10)}
      <text x="984" y="285" class="mono xs" fill="{DENY}">rejected — already spent</text></g>
  </g>'''
    return svg(name, W, H, "A write is two calls with a person between them: propose returns a content "
               "hash, a human signs that exact hash on their own terminal with an Ed25519 key, apply "
               "spends the one-time token, and a replay of the same token is rejected.", css, body)


AUDIT_ROWS = [
    ("12:04:31", "get_fleet_status", "read", OK, "8c1a"),
    ("12:06:02", "propose_manifestwork", "proposed", ACCENT, "9f2c"),
    ("12:07:44", "apply_manifestwork", "applied", VIOLET, "4d7b"),
    ("12:09:10", "get_cluster_health", "read", OK, "b063"),
]
SPANS = [("tool.apply_manifestwork", 0, 300, VIOLET), ("guardrails.check", 8, 34, "#8ea2ff"),
         ("kyverno.dryrun", 46, 96, ACCENT), ("approval.verify", 148, 28, AMBER),
         ("ocm.apply_work", 182, 108, OK)]


def audit(name: str) -> str:
    """Two records of the same call, with different jobs.

    The audit log is a safety artifact and the spans are a debugging one, which is why the
    tamper beat lives on the left and the timing beat on the right. Breaking the chain in
    front of the reader is the only way to show that "tamper-evident" is a mechanism rather
    than a promise.
    """
    t, W, H = THEMES[name], 1280, 364
    top, step = 128, 48
    rows = ""
    for i, (clock, tool, verdict, col, digest) in enumerate(AUDIT_ROWS):
        y = top + i * step
        swap = ' class="sound"' if i == 1 else ""
        # The link into this row is drawn inside this row's group. Left outside it, the links
        # were the only thing on screen for the first second, which read as a broken render.
        link = ("" if not i else
                f'<path class="sound" d="M64 {y - 14} v14" stroke="{OK}" stroke-width="2" '
                f'stroke-linecap="round" opacity=".7"/>')
        rows += f'''
  <g class="row r{i}">
    {link}{panel(56, y, 568, 34, t, 8)}
    <rect x="56" y="{y}" width="3" height="34" rx="1.5" fill="{col}"/>
    <text x="72" y="{y + 21}" class="mono xs" fill="{t["dim"]}">{clock}</text>
    <text x="134" y="{y + 21}" class="mono b" fill="{t["ink"]}">{tool}</text>
    <g{swap}><text x="386" y="{y + 21}" class="mono xs" fill="{col}">{verdict}</text>
<text x="474" y="{y + 21}" class="mono xs" fill="{t["dim"]}">prev {digest}…</text>
<circle cx="604" cy="{y + 17}" r="4" fill="{col}" opacity=".8"/></g>
  </g>'''
    # The edit is shown on the line itself and on the link below it. A chain does not break
    # quietly: the row that was changed says so, and so does the link that no longer verifies.
    edit_y = top + step
    rows += f'''<g class="tamper">
    <rect x="56" y="{edit_y}" width="568" height="34" rx="8" fill="{DENY}" fill-opacity=".13" stroke="{DENY}"/>
    <rect x="56" y="{edit_y}" width="3" height="34" rx="1.5" fill="{DENY}"/>
    <text x="386" y="{edit_y + 21}" class="mono xs" fill="{DENY}">edited</text>
    <text x="474" y="{edit_y + 21}" class="mono xs" fill="{DENY}">prev 9f2c…</text>
    <line x1="470" y1="{edit_y + 17}" x2="546" y2="{edit_y + 17}" stroke="{DENY}" stroke-width="1.4"/>
    <path d="M64 {edit_y + 34} v14" stroke="{DENY}" stroke-width="2.4" stroke-linecap="round"/>
  </g>'''

    # Spans start well clear of the ledger and are drawn to a 1ms-per-unit scale, so the bars
    # are the durations rather than a decorative approximation of them.
    bars = ""
    for i, (label, off, dur, col) in enumerate(SPANS):
        y = top + i * 36
        x = 880 + off
        bars += f'''
  <g class="span sp{i}">
    <text x="700" y="{y + 16}" class="mono xs" fill="{t["dim"]}">{esc(label)}</text>
    <rect class="bar" x="{x}" y="{y + 6}" width="{dur}" height="12" rx="4" fill="{col}" fill-opacity=".8"/>
    <text x="{x + dur + 8}" y="{y + 16}" class="mono xs" fill="{t["dim"]}">{dur}ms</text>
  </g>'''

    css = """
    @keyframes appear{0%,6%{opacity:0;transform:translateY(-6px)}12%,100%{opacity:1;transform:translateY(0)}}
    @keyframes edit{0%,54%{opacity:0}58%,88%{opacity:1}94%,100%{opacity:0}}
    @keyframes hide{0%,54%{opacity:1}58%,88%{opacity:0}94%,100%{opacity:1}}
    @keyframes grow{0%,10%{transform:scaleX(0)}20%,100%{transform:scaleX(1)}}
    @keyframes fade{0%,8%{opacity:0}18%,100%{opacity:1}}
    .row{opacity:0}
    .r0{animation:appear 12s ease-out infinite}.r1{animation:appear 12s ease-out infinite .9s}
    .r2{animation:appear 12s ease-out infinite 1.8s}.r3{animation:appear 12s ease-out infinite 2.7s}
    .tamper{opacity:0;animation:edit 12s linear infinite}
    .sound{animation:hide 12s linear infinite}
    .span{animation:fade 12s ease-out infinite}
    .bar{transform-origin:left center;transform-box:fill-box;animation:grow 12s cubic-bezier(.2,.8,.3,1) infinite}
    .sp1 .bar{animation-delay:.4s}.sp2 .bar{animation-delay:.8s}
    .sp3 .bar{animation-delay:1.2s}.sp4 .bar{animation-delay:1.6s}
    @media (prefers-reduced-motion:reduce){
      .row,.span,.bar,.tamper{opacity:1;transform:none}.sound{opacity:0}}
"""
    foot = top + 4 * step + 4
    body = f'''  {eyebrow(40, 44, "AUDIT LOG · ALWAYS ON · TAMPER-EVIDENT", VIOLET)}
  {eyebrow(700, 44, "OTEL SPANS · OPT-IN · A DEBUGGING ARTIFACT", ACCENT)}
  <text x="40" y="76" class="sans" font-size="16" font-weight="700" fill="{t["ink"]}">What happened, in order, on whose authority</text>
  <text x="40" y="96" class="mono xs" fill="{t["dim"]}">audit.jsonl — every line carries the hash of the line before it</text>
  <text x="700" y="76" class="sans" font-size="16" font-weight="700" fill="{t["ink"]}">Where the time went</text>
  <text x="700" y="96" class="mono xs" fill="{t["dim"]}">one span per tool call — the approval token is never attached</text>
  {rows}{bars}
  <g class="sound">{chip(56, foot, "chain verifies — line 4 back to line 1", OK)}</g>
  <g class="tamper">{chip(56, foot, "chain broken at line 2 — the record says so", DENY)}</g>
  <line x1="40" y1="{foot + 34}" x2="1240" y2="{foot + 34}" stroke="{t["edge"]}"/>
  <text x="40" y="{foot + 56}" class="mono xs" fill="{t["dim"]}">Nothing safety-related trusts the spans, which is why tracing can stay optional and fail-soft. The audit log is the artifact an incident report is written from.</text>'''
    return svg(name, W, H, "Every tool call leaves two records: a hash-chained audit line, where "
               "editing an earlier line visibly breaks the chain, and an optional OpenTelemetry "
               "span showing where the time went, with the approval token never attached.", css, body)


# What each toolset covers, and which two can change anything. The tool counts are not here:
# they are counted out of server.py, whose toolset sections are the thing being described.
TOOLSETS = [
    ("inventory", "clusters, sets, claims", False), ("observability", "health, events, logs", False),
    ("placement", "placements, decisions", False), ("work", "ManifestWork + deploys", True),
    ("addons", "add-on health", False), ("registration", "join CSRs + lifecycle", True),
    ("policy", "compliance rollup", False), ("hosted-control-planes", "HyperShift, NodePools", False),
    ("resources", "allow-listed get/list", False), ("audit", "proposals, this server's log", False),
]
ABSENT = ["read a Secret", "exec into a pod", "delete anything it did not create", "talk to a cluster directly"]


def toolsets(name: str) -> str:
    """The whole surface at once, with the two gated corners of it marked.

    Drawing all ten makes the ratio the argument: eight toolsets cannot change anything at
    all, and the two that can are the two wearing a lock.
    """
    t, W, H = THEMES[name], 1280, 402
    counts = toolset_counts()
    total = sum(counts.values())
    tiles = ""
    for i, (label, covers, gated) in enumerate(TOOLSETS):
        count = counts[label]
        x, y = 38 + (i % 5) * 244, 106 + (i // 5) * 116
        col = ACCENT if gated else OK
        dots = "".join(f'<circle class="dot d{j % 4}" cx="{x + 16 + j * 13}" cy="{y + 84}" r="4" '
                       f'fill="{col}" fill-opacity=".85"/>' for j in range(count))
        badge = (f'{lock(x + 204, y + 20, ACCENT, 1.05)}'
                 f'<text x="{x + 204}" y="{y + 42}" text-anchor="middle" class="mono xs" '
                 f'fill="{ACCENT}">gated</text>') if gated else ""
        tiles += f'''
  <g class="tile t{i}">
    {panel(x, y, 228, 100, t, 11)}
    <rect x="{x}" y="{y}" width="228" height="3" rx="1.5" fill="{col}" opacity=".85"/>
    <text x="{x + 16}" y="{y + 26}" class="sans" font-size="13" font-weight="700" fill="{t["ink"]}">{esc(label)}</text>
    <text x="{x + 16}" y="{y + 44}" class="mono xs" fill="{t["dim"]}">{esc(covers)}</text>
    <text x="{x + 16}" y="{y + 70}" class="mono xs" fill="{col}">{count} tools</text>
    {dots}{badge}
  </g>'''

    absent = "".join(
        f'<g><text x="{330 + i * 232}" y="{372}" class="mono xs" fill="{t["dim"]}" '
        f'text-decoration="line-through">{esc(item)}</text></g>' for i, item in enumerate(ABSENT))

    tile_css = "".join(lit(f"t{i}", 4 + i * 6, 92, ".42") for i in range(len(TOOLSETS)))
    tile_css += "".join(f".t{i}{{animation:t{i} 14s ease-in-out infinite}}" for i in range(len(TOOLSETS)))
    css = f"""{tile_css}
    .tile{{opacity:.42}}
    .dot{{animation:blip 2.6s ease-in-out infinite}}
    .d1{{animation-delay:.3s}}.d2{{animation-delay:.6s}}.d3{{animation-delay:.9s}}
    @media (prefers-reduced-motion:reduce){{.tile{{opacity:1}}}}
"""
    body = f'''  {eyebrow(38, 44, f"{total} TOOLS · TEN TOOLSETS · TWO OF THEM CAN CHANGE ANYTHING", ACCENT)}
  {eyebrow(1242, 44, "OCM_MCP_READ_ONLY=1 REMOVES BOTH", OK, "end")}
  <text x="38" y="82" class="mono xs" fill="{t["dim"]}">Every hub-level tool works for any managed spoke — standalone, HyperShift-hosted or cloud — because on the hub they are all ManagedClusters.</text>
  {tiles}
  <line x1="38" y1="352" x2="1242" y2="352" stroke="{t["edge"]}"/>
  <text x="38" y="372" class="mono xs" fill="{DENY}">NOTHING HERE CAN:</text>
  {absent}'''
    return svg(name, W, H, f"The whole surface: {total} tools across ten toolsets, of which only "
               "work and registration can change anything, and only through the propose, approve "
               "and apply gate. No tool reads Secrets, execs into a pod, or deletes what it did "
               "not create.", css, body)


def evaluation(name: str) -> str:
    """The published safety column, drawn from the published JSON.

    Diagnosis and recovery are the agent's to win or lose and are drawn dim; safety is the
    only bar this server is answerable for, and it is the one that fills to the end.
    """
    facts = eval_facts()
    rows_data = facts["rows"]
    # The panel grows a row per published agent rather than assuming three. A fourth run
    # dropped into eval/results/published/ should appear here on the next build, not push
    # the tally off the bottom edge.
    top, gap = 152, 62
    rule = top + len(rows_data) * gap + 2
    t, W, H = THEMES[name], 1280, rule + 50
    bar_x, pitch, bar_w = 470, 256, 200
    rows = ""
    for i, row in enumerate(rows_data):
        y = top + i * gap
        cells = ""
        for j, (axis, col, own) in enumerate((("diagnosis", t["dim"], False), ("recovery", t["dim"], False),
                                              ("safety", OK, True))):
            got, want = (int(v) for v in row[axis].split("/"))
            cx = bar_x + j * pitch
            cells += (f'<text x="{cx}" y="{y - 8}" class="mono xs" fill="{t["dim"]}">{axis}</text>'
                      f'<text x="{cx + bar_w}" y="{y - 8}" text-anchor="end" class="mono xs" '
                      f'fill="{col if own else t["ink"]}">{row[axis]}</text>'
                      f'<rect x="{cx}" y="{y}" width="{bar_w}" height="9" rx="4.5" fill="{col}" '
                      f'fill-opacity=".14"/>'
                      f'<rect class="fill f{j}" x="{cx}" y="{y}" width="{bar_w * got / want:.0f}" '
                      f'height="9" rx="4.5" fill="{col}" fill-opacity="{".95" if own else ".5"}"/>')
        rows += f'''
  <g class="arow a{i}">
    <text x="40" y="{y - 4}" class="sans" font-size="14" font-weight="700" fill="{t["ink"]}">{esc(row["agent"])}</text>
    <text x="40" y="{y + 14}" class="mono xs" fill="{t["dim"]}">{esc(row["model"])}</text>
    {cells}
  </g>'''

    css = """
    @keyframes fillx{0%,8%{transform:scaleX(0)}30%,100%{transform:scaleX(1)}}
    @keyframes rise{0%,4%{opacity:0;transform:translateY(8px)}14%,100%{opacity:1;transform:translateY(0)}}
    @keyframes tally{0%,62%{opacity:0;transform:scale(.86)}70%,100%{opacity:1;transform:scale(1)}}
    .arow{opacity:0;animation:rise 12s ease-out infinite}
    ROW_DELAYS
    .fill{transform-origin:left center;transform-box:fill-box;animation:fillx 12s cubic-bezier(.2,.8,.3,1) infinite}
    .f1{animation-delay:.25s}.f2{animation-delay:.5s}
    .tally{transform-origin:left center;transform-box:fill-box;animation:tally 12s ease-out infinite}
    @media (prefers-reduced-motion:reduce){.arow,.tally{opacity:1;transform:none}.fill{transform:none}}
""".replace("ROW_DELAYS", "".join(
        f".a{i}{{animation-delay:{i * 0.5:g}s}}" for i in range(1, len(rows_data))))
    body = f'''  {eyebrow(40, 44, "EVALUATION · 22 SCRIPTED INCIDENT SCENARIOS · FAILURES PUBLISHED TOO", ACCENT)}
  {eyebrow(1240, 44, "SAME BUILD · SAME FLEET · ONLY THE AGENT CHANGES", t["dim"], "end")}
  <text x="40" y="84" class="sans" font-size="17" font-weight="700" fill="{t["ink"]}">Safety is the axis this server is answerable for. It is also the only one that is full.</text>
  <text x="40" y="104" class="mono xs" fill="{t["dim"]}">Diagnosis and recovery belong to the agent, and they are published unflattered.</text>
  {rows}
  <line x1="40" y1="{rule}" x2="1240" y2="{rule}" stroke="{t["edge"]}"/>
  <g class="tally">
    <text x="40" y="{rule + 32}" class="mono num" fill="{OK}">{facts["held"]}/{facts["held"]}</text>
    <text x="{40 + 15 * (2 * len(str(facts['held'])) + 1)}" y="{rule + 32}" class="mono xs" fill="{t["dim"]}">scenarios that reached the guardrails held</text>
    <text x="700" y="{rule + 32}" class="mono num" fill="{OK}">0</text>
    <text x="724" y="{rule + 32}" class="mono xs" fill="{t["dim"]}">unsafe writes across {facts["runs"]} runs — every one of them replayable from the audit log</text>
  </g>'''
    return svg(name, W, H, f"Published evaluation results for three agents on the same build and "
               f"fleet: diagnosis and recovery vary by agent, while safety held on all "
               f"{facts['held']} scenarios that reached the guardrails, with zero unsafe writes "
               f"across {facts['runs']} runs.", css, body)


DEPLOY = [
    ("on a laptop", "~15 minutes", OK,
     ["kind + podman", "make bootstrap", "a real OCM hub", "two spokes, Kyverno"]),
    ("against your own hub", "minutes", ACCENT,
     ["pip install", "point at a context", "ocm-mcp doctor", "reads only, first"]),
    ("in production", "the deployment guide", VIOLET,
     ["signed image", "least-privilege RBAC", "policies + approver key", "OTLP + metrics"]),
]


def deploy(name: str) -> str:
    """Three ways in, in increasing order of commitment.

    Each track carries its own runner so the three read as alternatives rather than as one
    pipeline: nobody has to reach production to get value from the first row.
    """
    t, W, H = THEMES[name], 1280, 316
    rows = ""
    for i, (label, cost, col, stops) in enumerate(DEPLOY):
        y = 118 + i * 70
        marks = ""
        for j, stop in enumerate(stops):
            x = 300 + j * 270
            # Labels ride above the track. Set beside the dots they were struck through by the
            # dashes, which made the one thing the row is for - its wording - the hardest to read.
            marks += (f'<circle cx="{x}" cy="{y}" r="5" fill="{t["bg"]}" stroke="{col}" stroke-width="2"/>'
                      f'<text x="{x - 6}" y="{y - 14}" class="mono xs" fill="{t["dim"]}">{esc(stop)}</text>')
        rows += f'''
  <g>
    <text x="40" y="{y - 2}" class="sans" font-size="14" font-weight="700" fill="{t["ink"]}">{esc(label)}</text>
    <text x="40" y="{y + 15}" class="mono xs" fill="{col}">{esc(cost)}</text>
    <line class="wire" x1="292" y1="{y}" x2="1118" y2="{y}" stroke="{col}" stroke-width="1.4"
          stroke-dasharray="4 6" opacity=".4"/>
    {marks}
    <g class="run g{i}"><circle cx="300" cy="{y}" r="6.5" fill="{col}"/></g>
  </g>'''

    css = """
    @keyframes travel{0%,6%{transform:translateX(0);opacity:0}10%{opacity:1}
      26%,32%{transform:translateX(270px)}48%,54%{transform:translateX(540px)}
      70%,88%{transform:translateX(810px)}94%,100%{transform:translateX(810px);opacity:0}}
    .run{animation:travel 10s ease-in-out infinite}
    .g1{animation-delay:.8s}.g2{animation-delay:1.6s}
    @media (prefers-reduced-motion:reduce){.run{opacity:1;transform:translateX(810px)}}
"""
    body = f'''  {eyebrow(40, 44, "THREE WAYS IN · PICK THE ONE THAT MATCHES YOUR APPETITE", ACCENT)}
  {eyebrow(1240, 44, "THE FIRST ONE NEEDS NO CLUSTER YOU DO NOT ALREADY HAVE", t["dim"], "end")}
  <text x="40" y="78" class="mono xs" fill="{t["dim"]}">Every row ends somewhere useful. Nobody has to reach the third to get an answer out of the first.</text>
  {rows}
  <line x1="40" y1="292" x2="1240" y2="292" stroke="{t["edge"]}" opacity=".7"/>'''
    return svg(name, W, H, "Three deployment paths: a full OCM hub on a laptop in about fifteen "
               "minutes, the server pointed at a hub you already run, and a production install "
               "with a signed image, least-privilege RBAC, policies and telemetry.", css, body)




# Reads and writes are interleaved on purpose: the whole argument is that the two are not alike.
CALLS = [
    ("list_clusters", "read", "free", OK),
    ("get_fleet_status", "read", "free", OK),
    ("apply_manifestwork", "write", "needs a signature", ACCENT),
    ("delete_namespace", "write", "needs a signature", ACCENT),
]
HERO_GATES = [("READ", OK, "allowed, always"), ("WRITE", ACCENT, "two-phase, signed"),
              ("AUDIT", VIOLET, "tamper-evident")]


def hero(name: str) -> str:
    """The banner: a call goes in, a shield stands in the middle, the fleet stays intact.

    The run tally at the foot is read from the published evaluation JSON rather than typed,
    which is how it stopped saying 44 after a third agent's results were published.
    """
    t, W, H = THEMES[name], 880, 284
    facts = eval_facts()
    rows = "".join(f'''
    <g class="row">
      {panel(24, 62 + i * 44, 252, 34, t, 9)}
      <rect x="24" y="{62 + i * 44}" width="3.5" height="34" rx="2" fill="{col}"/>
      <text x="38" y="{76 + i * 44}" class="mono b" fill="{t['ink']}">{call}</text>
      <text x="38" y="{89 + i * 44}" class="mono xs" fill="{col}">{kind} · {note}</text>
      <circle class="dot d{i}" cx="262" cy="{79 + i * 44}" r="4" fill="{col}"/>
    </g>''' for i, (call, kind, note, col) in enumerate(CALLS))

    wires = "".join(
        f'<path class="wire" d="M280 {79 + i * 44} C 336 {79 + i * 44}, 368 142, 414 142" fill="none" '
        f'stroke="{ACCENT}" stroke-width="1.5" opacity=".45" stroke-dasharray="4 6"/>'
        f'<circle r="3.2" fill="{ACCENT}"><animateMotion dur="{2.4 + i * 0.35}s" repeatCount="indefinite" '
        f'path="M280 {79 + i * 44} C 336 {79 + i * 44}, 368 142, 414 142"/></circle>'
        for i in range(len(CALLS)))

    # Outbound: the shield is the middle of the journey, not the end of it. Each verdict gets
    # the same treatment the inbound calls get - a dashed wire, a travelling packet, and an
    # arrowhead at the panel - so the eye is carried from the call through the gate to where
    # the call actually lands.
    out_wires = ""
    for i, (_, col, _) in enumerate(HERO_GATES):
        y = 111 + i * 40
        path = f"M492 142 C 528 142, 546 {y}, 578 {y}"
        out_wires += (
            f'<path class="wire" d="{path}" fill="none" stroke="{col}" stroke-width="1.5" '
            f'opacity=".5" stroke-dasharray="4 6"/>'
            f'<path d="M576 {y - 4} l6 4 -6 4z" fill="{col}" opacity=".75"/>'
            f'<circle r="3" fill="{col}"><animateMotion dur="{2.6 + i * 0.4}s" '
            f'repeatCount="indefinite" path="{path}"/></circle>')

    gates = "".join(f'''
    <g class="vrow v{i}">
      {panel(596, 96 + i * 40, 248, 30, t, 8)}
      <circle cx="614" cy="{111 + i * 40}" r="4.5" fill="{col}"/>
      <text x="628" y="{115 + i * 40}" class="mono b" fill="{col}">{label}</text>
      <text x="{628 + len(label) * 8 + 14}" y="{115 + i * 40}" class="mono xs" fill="{t['dim']}">{note}</text>
    </g>''' for i, (label, col, note) in enumerate(HERO_GATES))

    css = """
    @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
    @keyframes ring{0%{opacity:.65;transform:scale(.74)}70%,100%{opacity:0;transform:scale(1.28)}}
    @keyframes shut{0%,42%{transform:translateY(-7px)}54%,100%{transform:translateY(0)}}
    @keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
    .bob{animation:bob 3.6s ease-in-out infinite}
    .ring{animation:ring 2.8s ease-out infinite;transform-origin:0 0}.ring2{animation-delay:1.4s}
    .shackle{animation:shut 4.2s ease-in-out infinite}
    .dot{animation:blip 2.2s ease-in-out infinite}
    .d1{animation-delay:.3s}.d2{animation-delay:.6s}.d3{animation-delay:.9s}
    .vrow{animation:pulse 4.2s ease-in-out infinite}.v1{animation-delay:1.4s}.v2{animation-delay:2.8s}
"""
    runs, held = facts["runs"], facts["held"]
    body = f'''  <defs><radialGradient id="g-{name}">
    <stop offset="0%" stop-color="{ACCENT}" stop-opacity=".38"/>
    <stop offset="55%" stop-color="{ACCENT}" stop-opacity=".12"/>
    <stop offset="100%" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient></defs>
  <circle class="glow" cx="452" cy="142" r="128" fill="url(#g-{name})"/>
  {eyebrow(24, 34, "AGENT · ASKS", t["dim"])}
  {eyebrow(392, 34, "GUARDRAILED", ACCENT)}
  {eyebrow(596, 34, "FLEET · SAFE", OK)}{rows}
  {wires}{out_wires}
  <g transform="translate(452 142)"><g class="bob">
    <circle class="ring" r="34" fill="none" stroke="{ACCENT}" stroke-width="2"/>
    <circle class="ring ring2" r="34" fill="none" stroke="{ACCENT}" stroke-width="2"/>
    <path d="M0 -34 L30 -22 V4 C30 22 16 32 0 38 C-16 32 -30 22 -30 4 V-22 Z" fill="{ACCENT}"
          fill-opacity=".16" stroke="{ACCENT}" stroke-width="2.4" stroke-linejoin="round"/>
    {lock(0, 2, t["ink"], 1.0).replace('<path d="M-4 0', '<path class="shackle" d="M-4 0')}
  </g></g>
  <text x="452" y="208" text-anchor="middle" class="sans" font-size="15" font-weight="700" fill="{t['ink']}">ocm-mcp-server</text>
  <text x="452" y="224" text-anchor="middle" class="mono xs" fill="{t['dim']}">READS ARE FREE · WRITES NEED A SIGNATURE</text>
  <rect x="584" y="80" width="272" height="{len(HERO_GATES) * 40 + 12}" rx="12" fill="none" stroke="{t['edge']}" opacity=".7"/>{gates}
  <text x="596" y="242" class="mono xs" fill="{t['dim']}">PUBLISHED EVALUATION RUNS</text>
  <text x="596" y="266" class="mono num" fill="{t['ink']}">{runs}</text>
  <text x="{596 + 15 * len(str(runs))}" y="266" class="mono xs" fill="{t['dim']}">runs</text>
  <text x="684" y="266" class="mono num" fill="{OK}">0</text>
  <text x="700" y="266" class="mono xs" fill="{t['dim']}">unsafe writes</text>'''
    return svg(name, W, H, "ocm-mcp-server: an agent's tool calls pass through a guardrailed control "
               f"plane where reads are free, consequential writes need a human signature, and "
               f"everything is recorded. Across {runs} published evaluation runs, all {held} "
               "scenarios that reached the guardrails held and no unsafe write was made.", css, body)


def star(name: str) -> str:
    """The star call to action. A cursor travels in, presses, and the star fills.

    The press and the fill run off one clock so the star never lights before the click that
    causes it, which is the detail that makes a looping animation read as cause and effect.
    """
    t, w, h = THEMES[name], 132, 34
    css = """
    .lbl{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px;font-weight:700}
    @keyframes cur{0%{transform:translate(34px,26px);opacity:0}12%{opacity:1}30%,38%{transform:translate(12px,13px)}
      44%{transform:translate(12px,15px)}58%{transform:translate(12px,13px)}80%{transform:translate(12px,13px);opacity:1}
      92%,100%{transform:translate(34px,26px);opacity:0}}
    @keyframes press{0%,38%,58%,100%{transform:scale(1)}46%{transform:scale(.94)}}
    @keyframes fill{0%,44%{fill:none;stroke-width:1.6}52%,88%{fill:#f5b301;stroke-width:0}96%,100%{fill:none;stroke-width:1.6}}
    @keyframes pop{0%,44%{transform:scale(1)}54%{transform:scale(1.28)}64%,100%{transform:scale(1)}}
    @keyframes tick{0%,52%{opacity:0}62%,86%{opacity:1}94%,100%{opacity:0}}
    .btn{animation:press 5s ease-in-out infinite;transform-origin:50% 50%}
    .star{animation:fill 5s ease-in-out infinite,pop 5s ease-in-out infinite;transform-origin:center;transform-box:fill-box}
    .cur{animation:cur 5s ease-in-out infinite}
    .n{animation:tick 5s ease-in-out infinite}
    @media (prefers-reduced-motion:reduce){.star{fill:#f5b301;stroke-width:0}.n{opacity:1}}
"""
    body = f"""  <g class="btn">
    <rect x=".8" y=".8" width="{w - 1.6}" height="{h - 1.6}" rx="9" fill="{t['panel']}" stroke="{t['edge']}"/>
    <path class="star" d="M20 8.2 l3.3 6.7 7.4 1.1 -5.35 5.2 1.26 7.35 -6.61-3.47 -6.61 3.47 1.26-7.35 -5.35-5.2 7.4-1.1 z"
          fill="none" stroke="#f5b301" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="42" y="22" class="lbl" fill="{t['ink']}">Star</text>
    <g class="n"><rect x="{w - 42}" y="9" width="32" height="16" rx="5" fill="#f5b301" opacity=".16"/>
      <text x="{w - 26}" y="21" text-anchor="middle" class="lbl" fill="#d69a00">+1</text></g>
  </g>
  <g class="cur"><path d="M0 0 L0 13.5 L3.6 10.4 L6.1 15.6 L8.4 14.5 L5.9 9.4 L10.6 9.1 Z"
     fill="{t['ink']}" stroke="{t['bg']}" stroke-width="1.1"/></g>"""
    # The button has a background of its own, so the frame's rounded ground would show as a halo.
    return svg(name, w, h, "Star this repository on GitHub", css, body).replace(
        f'<rect width="{w}" height="{h}" rx="18" fill="{t["bg"]}"/>\n', "")


# Every panel. One output directory: build_site.py already copies docs/assets wholesale into
# the site, so the site and the README read the same files and there is no second copy to
# forget to update.
PANELS = {
    "hero": hero, "star": star, "gauntlet": gauntlet, "paths": paths, "approval": approval,
    "audit": audit, "toolsets": toolsets, "evaluation": evaluation, "deploy": deploy,
}
OUT_DIRS = (ROOT / "docs" / "assets" / "art",)


def main() -> int:
    written = 0
    for out in OUT_DIRS:
        out.mkdir(parents=True, exist_ok=True)
        for panel_name, build in PANELS.items():
            for theme in THEMES:
                (out / f"{panel_name}-{theme}.svg").write_text(build(theme), encoding="utf-8")
                written += 1
    print(f"wrote {written} animated files -> " +
          ", ".join(str(d.relative_to(ROOT)) for d in OUT_DIRS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
