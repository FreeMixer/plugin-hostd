#!/usr/bin/env python3
"""Figures of docs/zynthian/upstream-series.md, drawn from the measurement files and nothing else.

    tools/zynthian/series-figures.py [--check]

Writes docs/zynthian/evidence/series/03-modhost-backend/verb-replies.svg from
docs/zynthian/evidence/path-a/diff.txt: for each verb MOD-UI sent in the path-a session, how many calls it made and
how many of plugin-hostd's replies differ from mod-host's. --check only says whether the committed figure is what the
data draws now (exit 1 when it is not). Plain SVG, no plotting library.
"""

import os
import sys
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIFF = os.path.join(ROOT, "docs/zynthian/evidence/path-a/diff.txt")
OUT = os.path.join(ROOT, "docs/zynthian/evidence/series/03-modhost-backend/verb-replies.svg")


def read_diff(path):
    """[(verb, calls, differing)] from the tab-separated table at the top of diff.txt."""
    rows = []
    with open(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        calls_at, diff_at = header.index("ref"), header.index("aligned replies differing")
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < len(header) or not cols[calls_at].isdigit():
                break
            rows.append((cols[0], int(cols[calls_at]), int(cols[diff_at])))
    return rows


def svg(rows):
    bar_h, gap, left, right, top = 18, 6, 150, 70, 54
    width = 640
    scale = (width - left - right) / max(c for _, c, _ in rows)
    height = top + len(rows) * (bar_h + gap) + 40
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           'font-family="sans-serif" font-size="12">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           '<text x="16" y="22" font-size="14" fill="#111111">MOD-UI session on mod-host and on plugin-hostd: '
           'replies per verb</text>',
           f'<text x="16" y="40" fill="#444444">{sum(c for _, c, _ in rows)} calls, '
           f'{sum(d for _, _, d in rows)} replies differ (dark)</text>']
    for i, (verb, calls, differing) in enumerate(rows):
        y = top + i * (bar_h + gap)
        same = calls - differing
        out.append(f'<text x="{left - 8}" y="{y + 13}" text-anchor="end" fill="#111111">{escape(verb)}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{same * scale:.1f}" height="{bar_h}" fill="#9db8d6"/>')
        if differing:
            out.append(f'<rect x="{left + same * scale:.1f}" y="{y}" width="{differing * scale:.1f}" height="{bar_h}" '
                       'fill="#1f3a5f"/>')
        label = f"{calls}" + (f" ({differing} differ)" if differing else "")
        out.append(f'<text x="{left + calls * scale + 6:.1f}" y="{y + 13}" fill="#111111">{label}</text>')
    out.append(f'<text x="16" y="{height - 12}" fill="#666666">Source: docs/zynthian/evidence/path-a/diff.txt</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    drawn = svg(read_diff(DIFF))
    if "--check" in sys.argv[1:]:
        try:
            with open(OUT) as f:
                same = f.read() == drawn
        except OSError:
            same = False
        print(f"{os.path.relpath(OUT, ROOT)}: {'matches the data' if same else 'differs from the data'}")
        return 0 if same else 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(drawn)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
