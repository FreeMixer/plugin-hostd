#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Writes docs/evidence/figures/from-file-to-page.svg by hand: five stages in a row, the artefact under each,
# the surfaces that consume them under the last. Run from the repository root: python3 tools/figures/from-file-to-page.py
import sys
from xml.sax.saxutils import escape

STAGES = [
    ("1  Scan and describe", "plugin-hostd", "descriptor", "/var/lib/omx/descriptors/"),
    ("2  Qualify", "plugin-qualify", "record", "/var/lib/omx/qualification/"),
    ("3  Pins", "plugin-qualify-sync", "pin line", "/var/lib/omx/qualified.pins"),
    ("4  Layout", "omx-panel", "pages", "computed from the descriptor"),
    ("5  Read on the device", "zynthian-ui", "menu, pages, estimate", "on the screen"),
]
SURFACES = ["plugin menu row", "controller pages", "MOD GUI", "chain estimate footer"]
W, H = 1100, 330
BW, BH, GAP, X0, Y0 = 188, 70, 30, 20, 20
out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
       'aria-label="Five stages from a plugin file to a page on the screen, with the artefact each writes">',
       '<title>From a plugin file to a page on the screen</title>',
       '<style>text{font-family:sans-serif;font-size:13px;fill:#1a1a1a}.s{font-weight:bold}.m{font-size:12px;fill:#444}'
       'rect.b{fill:#eef3fa;stroke:#35537a;stroke-width:1.5}rect.a{fill:#fff;stroke:#888;stroke-dasharray:4 3}'
       'rect.c{fill:#f3f7ee;stroke:#4a6b2f}path,line{stroke:#35537a;stroke-width:1.5;fill:none}</style>',
       '<defs><marker id="h" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" '
       'style="fill:#35537a;stroke:none"/></marker></defs>']
for i, (name, owner, art, path) in enumerate(STAGES):
    x = X0 + i * (BW + GAP)
    out.append(f'<rect class="b" x="{x}" y="{Y0}" width="{BW}" height="{BH}" rx="6"/>')
    out.append(f'<text class="s" x="{x+10}" y="{Y0+28}">{escape(name)}</text>')
    out.append(f'<text class="m" x="{x+10}" y="{Y0+52}">{escape(owner)}</text>')
    out.append(f'<line x1="{x+BW/2}" y1="{Y0+BH}" x2="{x+BW/2}" y2="{Y0+BH+30}" marker-end="url(#h)"/>')
    out.append(f'<rect class="a" x="{x}" y="{Y0+BH+34}" width="{BW}" height="58" rx="6"/>')
    out.append(f'<text class="s" x="{x+10}" y="{Y0+BH+56}">{escape(art)}</text>')
    out.append(f'<text class="m" x="{x+10}" y="{Y0+BH+76}">{escape(path)}</text>')
    if i < len(STAGES) - 1:
        out.append(f'<line x1="{x+BW}" y1="{Y0+BH/2}" x2="{x+BW+GAP-2}" y2="{Y0+BH/2}" marker-end="url(#h)"/>')
last = X0 + 4 * (BW + GAP)
sy = Y0 + BH + 92 + 22
out.append(f'<line x1="{last+BW/2}" y1="{Y0+BH+92}" x2="{last+BW/2}" y2="{sy-2}" marker-end="url(#h)"/>')
sw = 160
sx0 = W - 20 - 4 * sw - 3 * 12
for j, s in enumerate(SURFACES):
    x = sx0 + j * (sw + 12)
    out.append(f'<rect class="c" x="{x}" y="{sy}" width="{sw}" height="40" rx="6"/>')
    out.append(f'<text x="{x+10}" y="{sy+25}">{escape(s)}</text>')
out.append(f'<text class="m" x="{sx0}" y="{sy+62}">The consumer surfaces read the artefacts; nothing is computed twice.</text>')
out.append('</svg>')
path = sys.argv[1] if len(sys.argv) > 1 else "docs/evidence/figures/from-file-to-page.svg"
open(path, "w").write("\n".join(out) + "\n")
