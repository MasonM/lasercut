#!/usr/bin/env python3
"""
Repack the pieces in an OpenSCAD-exported SVG so they sit closer together.

Assumes the SVG contains a single <path> using only absolute M/L commands and
"z" closes (which is what OpenSCAD produces for polygon exports). Subpaths are
grouped into pieces by bounding-box containment (holes belong to the outline
that contains them), then the pieces are laid out with a simple shelf
(row-based) packing. Not optimal, but simple and good enough to save material.

Usage: pack_svg.py [--spacing MM] input.svg [output.svg]
If no output is given, the input file is rewritten in place.
"""

import argparse
import math
import re
import sys

NUM_RE = re.compile(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?')


def parse_subpaths(d: str):
    """Return a list of subpaths, each a list of (x, y) points."""
    subpaths = []
    for chunk in d.split('M')[1:]:
        nums = [float(n) for n in NUM_RE.findall(chunk)]
        if len(nums) < 4 or len(nums) % 2 != 0:
            raise ValueError(
                "Unexpected path data; expected pairs of coordinates")
        subpaths.append(list(zip(nums[0::2], nums[1::2])))
    return subpaths


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def group_pieces(subpaths):
    """Group subpaths into pieces: each hole joins the smallest outline whose
    bbox contains it. Returns a list of (piece_bbox, [subpath indices])."""
    boxes = [bbox(sp) for sp in subpaths]
    parent = list(range(len(subpaths)))
    for i, bi in enumerate(boxes):
        best = None
        for j, bj in enumerate(boxes):
            if i == j or not contains(bj, bi) or bbox_area(bj) <= bbox_area(bi):
                continue
            if best is None or bbox_area(bj) < bbox_area(boxes[best]):
                best = j
        if best is not None:
            parent[i] = best

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    groups = {}
    for i in range(len(subpaths)):
        groups.setdefault(root(i), []).append(i)
    return [(boxes[r], members) for r, members in groups.items()]


def pack(pieces, spacing):
    """Shelf-pack piece bboxes. Returns a list of (dx, dy) per piece (same
    order as input) placing bbox min-corners in a fresh coordinate space."""
    sizes = [(b[2] - b[0], b[3] - b[1]) for b, _ in pieces]
    order = sorted(range(len(pieces)), key=lambda i: -sizes[i][1])

    total_area = sum((w + spacing) * (h + spacing) for w, h in sizes)
    target_width = max(max(w for w, _ in sizes), math.sqrt(total_area) * 1.1)

    offsets = [None] * len(pieces)
    x = y = shelf_h = 0.0
    for i in order:
        w, h = sizes[i]
        if x > 0 and x + w > target_width:
            y += shelf_h + spacing
            x = shelf_h = 0.0
        offsets[i] = (x, y)
        x += w + spacing
        shelf_h = max(shelf_h, h)
    return offsets


def fmt(v):
    return f"{v:.4f}".rstrip('0').rstrip('.')


def pack_svg_text(svg: str, spacing: float = 2.0) -> str:
    """Repack the pieces of an OpenSCAD-exported SVG string; return new SVG."""
    m = re.search(r'<path d="(.*?)"', svg, re.S)
    if not m or svg.count('<path') != 1:
        raise ValueError("Expected exactly one <path> element in the SVG")
    subpaths = parse_subpaths(m.group(1))
    pieces = group_pieces(subpaths)
    offsets = pack(pieces, spacing)

    # Translate each piece so its bbox min-corner lands at the packed offset
    placed = [None] * len(subpaths)
    for (b, members), (ox, oy) in zip(pieces, offsets):
        dx, dy = ox - b[0], oy - b[1]
        for i in members:
            placed[i] = [(x + dx, y + dy) for x, y in subpaths[i]]

    all_boxes = [bbox(sp) for sp in placed]
    margin = spacing / 2
    min_x = min(b[0] for b in all_boxes) - margin
    min_y = min(b[1] for b in all_boxes) - margin
    width = max(b[2] for b in all_boxes) + margin - min_x
    height = max(b[3] for b in all_boxes) + margin - min_y

    d = "\n".join(
        "M " + " L ".join(f"{fmt(x)},{fmt(y)}" for x, y in sp) + " z"
        for sp in placed)

    return (
        '<?xml version="1.0" standalone="no"?>\n'
        '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
        f'<svg width="{fmt(width)}mm" height="{fmt(height)}mm" '
        f'viewBox="{fmt(min_x)} {fmt(min_y)} {fmt(width)} {fmt(height)}" '
        'xmlns="http://www.w3.org/2000/svg" version="1.1">\n'
        '<title>OpenSCAD Model</title>\n'
        f'<path d="\n{d}\n" stroke="black" fill="none" stroke-width="0.35"/>\n'
        '</svg>\n'
    )


def pack_svg_file(input_path: str, output_path: str = None,
                  spacing: float = 2.0) -> None:
    """Repack an SVG file, writing to output_path (or in place if None)."""
    with open(input_path) as f:
        svg = f.read()
    packed = pack_svg_text(svg, spacing)
    with open(output_path or input_path, 'w') as f:
        f.write(packed)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input')
    ap.add_argument('output', nargs='?')
    ap.add_argument('--spacing', type=float, default=2.0,
                    help='Gap between pieces in mm (default: 2)')
    args = ap.parse_args()

    try:
        pack_svg_file(args.input, args.output, args.spacing)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == '__main__':
    main()
