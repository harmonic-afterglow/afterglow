"""Cut a remote's drawing out of a page of its user guide, as an SVG the editors draw.

Logitech's user guides draw each remote as line art - every key its own outline, the
printed labels as text - which is exactly the picture people know the remote by. This
turns one page (pdftocairo's SVG of it) into a file holding just the remote: whatever
reaches into the region is kept, at the page's own coordinates, so the key positions in
the remote's `art.json` are the page's points too.

Everything about one remote's drawing lives in its folder (library/remotes/<id>/): the
recipe in `art.json` under "source" - the guide, page and region, callout colours to
leave out, parts of the page to erase or move, colours to repaint, a flat colour for a
shaded case, a stretch for a guide that drew the remote squashed, a mock-up screen to
empty, marks to print on the keys - and the result, `art.svg`, written beside it.

    python3 tools/remote_art.py ../afterglow-site/_sources/manuals \
        src/afterglow/library/remotes/harmony-one src/afterglow/library/remotes/harmony-900

The first argument is the folder holding the user guides. Needs pdftocairo (poppler), but
not for a guide kept only as the SVG of its remote's page. A label printed as a mark is
its letters' outlines, kept in the recipe, so the drawing needs no font.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SVG = "http://www.w3.org/2000/svg"
NS = "{%s}" % SVG
XLINK = "{http://www.w3.org/1999/xlink}"
NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK[1:-1])


def _matrix(transform):
    if not transform:
        return (1, 0, 0, 1, 0, 0)
    values = [float(v) for v in NUM.findall(transform)]
    if transform.startswith("matrix"):
        return tuple(values)
    if transform.startswith("translate"):
        return (1, 0, 0, 1, values[0], values[1] if len(values) > 1 else 0)
    raise ValueError(f"unexpected transform {transform}")


def _then(a, b):
    """b applied inside a."""
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _points(element, m):
    if element.tag == NS + "path":
        values = [float(v) for v in NUM.findall(element.get("d", ""))]
        pairs = zip(values[0::2], values[1::2])
    elif element.tag == NS + "use":
        pairs = [(float(element.get("x", 0)), float(element.get("y", 0)))]
    else:
        return []
    return [(m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]) for x, y in pairs]


def _keep_inside(parent, m, box) -> bool:
    """Drop what lies outside the box; whether anything in `parent` is left."""
    x0, y0, x1, y1 = box
    kept = False
    for child in list(parent):
        if child.tag == NS + "defs":
            continue
        inner = _then(m, _matrix(child.get("transform")))
        points = _points(child, inner)
        if points:
            # Anything reaching into the region: the remote's outline runs past a
            # region that starts below its screen, and is cut by the view box.
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            inside = min(xs) <= x1 and max(xs) >= x0 and min(ys) <= y1 and max(ys) >= y0
        else:
            inside = _keep_inside(child, inner, box)
        if inside:
            kept = True
        else:
            parent.remove(child)
    return kept


def _drop_unused(root) -> None:
    """Keep only the definitions the drawing uses: the page's SVG defines every glyph
    and clip on the page, most of them for the text beside the remote."""
    def references(element):
        found = set()
        for node in element.iter():
            href = node.get(XLINK + "href") or node.get("href") or ""
            if href.startswith("#"):
                found.add(href[1:])
            for value in node.attrib.values():
                found.update(re.findall(r"url\(#([^)]+)\)", value))
        return found

    defs = [d for d in root.iter(NS + "defs")]
    body = [child for child in root if child.tag != NS + "defs"]
    wanted = set()
    for element in body:
        wanted |= references(element)
    # A clip or glyph may itself refer to another definition.
    by_id = {node.get("id"): node for d in defs for node in d.iter() if node.get("id")}
    pending = list(wanted)
    while pending:
        node = by_id.get(pending.pop())
        for more in references(node) - wanted if node is not None else ():
            wanted.add(more)
            pending.append(more)

    def prune(parent):
        for child in list(parent):
            ident = child.get("id")
            if ident is not None:
                if ident not in wanted:
                    parent.remove(child)
            else:
                prune(child)
                if len(child) == 0 and child.tag == NS + "g":
                    parent.remove(child)
    for d in defs:
        prune(d)


def _colour(value):
    """A colour as pdftocairo writes it - rgb(…%, …%, …%) - as #rrggbb; else as is."""
    match = re.fullmatch(r"rgb\(([\d.]+)%,\s*([\d.]+)%,\s*([\d.]+)%\)", value or "")
    if not match:
        return value
    return "#" + "".join(f"{round(float(v) * 2.55):02x}" for v in match.groups())


def _restyle(root, drop=(), recolour=None) -> None:
    """Take out what is drawn in a `drop` colour - the guide's callout lines and their
    letters - and repaint the rest by `recolour`, {#rrggbb: #rrggbb}."""
    recolour = recolour or {}
    dropped = {c.lower() for c in drop}

    def walk(parent):
        for child in list(parent):
            if child.tag == NS + "defs":
                continue
            colours = {_colour(child.get(a)) for a in ("fill", "stroke") if child.get(a)}
            if colours & dropped:
                parent.remove(child)
                continue
            for attribute in ("fill", "stroke"):
                value = _colour(child.get(attribute))
                if value in recolour:
                    child.set(attribute, recolour[value])
            walk(child)
    walk(root)


def _bounds(element, m):
    points = [point for node in element.iter()
              for point in _points(node, m)] if element.tag != NS + "use" else \
        _points(element, m)
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _blank(root, screen) -> None:
    """Empty the drawn screen - the guide shows made-up Activities on it."""
    x, y, width, height = screen
    inner = (x + 1, y + 1, x + width - 1, y + height - 1)

    def walk(parent, m):
        for child in list(parent):
            if child.tag == NS + "defs":
                continue
            matrix = _then(m, _matrix(child.get("transform")))
            box = _bounds(child, matrix)
            if box and (inner[0] <= box[0] and box[2] <= inner[2]
                        and inner[1] <= box[1] and box[3] <= inner[3]):
                parent.remove(child)
            elif box:
                walk(child, matrix)
    walk(root, (1, 0, 0, 1, 0, 0))


def _erase(root, boxes) -> None:
    """Leave out what lies wholly inside any of ``boxes`` (x0, y0, x1, y1): a part of
    the page that reaches into the region but is no part of the remote - the 800's
    slide-out keyboard, drawn against its side."""
    def inside(box):
        return any(x0 <= box[0] and box[2] <= x1 and y0 <= box[1] and box[3] <= y1
                   for x0, y0, x1, y1 in boxes)

    def walk(parent, m):
        for child in list(parent):
            matrix = _then(m, _matrix(child.get("transform")))
            box = _bounds(child, matrix)
            if box and inside(box):
                parent.remove(child)
            elif box:
                walk(child, matrix)
    walk(root, (1, 0, 0, 1, 0, 0))


def _move(root, moves) -> None:
    """Move what lies wholly inside each move's "box" (x0, y0, x1, y1) "by" (dx, dy):
    the 555's guide prints the 525's Menu and Guide, which the 555 has the other way
    round. Everything to move is found first, so two words can swap places."""
    found = []

    def walk(parent, m, box, by):
        for child in list(parent):
            if child.tag == NS + "defs":
                continue
            matrix = _then(m, _matrix(child.get("transform")))
            bounds = _bounds(child, matrix)
            if bounds and (box[0] <= bounds[0] and bounds[2] <= box[2]
                           and box[1] <= bounds[1] and bounds[3] <= box[3]):
                found.append((child, m, by))
            elif bounds:
                walk(child, matrix, box, by)
    for move in moves:
        walk(root, (1, 0, 0, 1, 0, 0), move["box"], move["by"])
    for child, m, by in found:
        # the shift in the parent's own units, ahead of the child's transform
        a, b, c, d = m[:4]
        det = a * d - b * c
        tx, ty = (d * by[0] - c * by[1]) / det, (a * by[1] - b * by[0]) / det
        child.set("transform",
                  f"translate({tx:.4f} {ty:.4f}) {child.get('transform') or ''}".strip())


def _mark(root, marks, transform=None) -> None:
    """Print on the keys what the guide's drawing leaves off: the 1100's is drawn
    blank, and the 900's colour keys are drawn black. Each mark is a shape, {"d"} in the
    drawing's points, filled in black or its "fill" colour and outlined with "stroke" - a
    width; a label is its letters' outlines, named by "label"."""
    # a stretched drawing's marks carry the stretch themselves, outside it: the keys
    # view paints this layer again by its own bounds, which leave out a parent's
    # transform
    layer = ET.SubElement(root, NS + "g", {"id": "afterglow-marks", "fill": INK,
                                           **({"transform": transform} if transform else {})})
    for mark in marks:
        if "text" in mark:
            # a label is its letters' outlines (a "d" mark), never text: a PC without the
            # font would draw another, or none
            raise SystemExit(f"mark {mark['text']!r} is text; give its outline as a d mark")
        outlined = mark.get("stroke")
        fill = mark.get("fill") or ("none" if outlined else INK)
        # "colour" strokes an outline in a colour of its own: the Xbox 360's Y, X, A and
        # B rings, open inside so a lit key's tint shows through the layer painted over it
        ET.SubElement(layer, NS + "path", {
            "d": mark["d"], "fill": fill,
            **({"stroke": mark.get("colour", INK), "stroke-width": str(outlined),
                "stroke-linecap": "round", "stroke-linejoin": "round"}
               if outlined else {})})


def _flatten(root, colour) -> None:
    """Paint what a gradient shades - the 5xx guides' case - in one ``colour``: the
    editors tint keys over the drawing, and a shaded case reads as tinted. The guide
    shades a rectangle clipped to the case, and the editors' renderer (Qt's) ignores
    clipping, which left the rectangle's corners white past the case's rounded ends: the
    shape takes its clip's own outline instead."""
    clips = {node.get("id"): node for node in root.iter(NS + "clipPath")}

    def outline_of(clip_ids):
        for ident in clip_ids:                       # the innermost clip first
            clip = clips.get(ident)
            path = (next((c for c in clip if c.tag == NS + "path"), None)
                    if clip is not None else None)
            if path is not None and "C" in path.get("d", "") and not path.get("transform"):
                return path.get("d")
        return None

    def walk(parent, clip_ids):
        for child in parent:
            if child.tag == NS + "defs":
                continue
            inner = clip_ids
            match = re.fullmatch(r"url\(#([^)]+)\)", child.get("clip-path") or "")
            if match:
                inner = [match.group(1)] + clip_ids
            for attribute in ("fill", "stroke"):
                if (child.get(attribute) or "").startswith("url("):
                    child.set(attribute, colour)
                    shape = outline_of(inner) if attribute == "fill" else None
                    if shape and child.tag == NS + "path" and not child.get("transform"):
                        child.set("d", shape)
            walk(child, inner)
    walk(root, [])


def _stretch(root, origin, factors) -> str:
    """Scale everything drawn by ``factors`` (x, y) from ``origin``: the 5xx guides drew
    their remote 10% narrower than it is, every round key an upright oval. Key places in
    `art.json` are in the stretched drawing's points."""
    (x, y), (sx, sy) = origin, factors
    matrix = f"matrix({sx} 0 0 {sy} {x - x * sx:.4f} {y - y * sy:.4f})"
    layer = ET.Element(NS + "g", {"transform": matrix})
    for child in [c for c in root if c.tag != NS + "defs"]:
        root.remove(child)
        layer.append(child)
    root.append(layer)
    return matrix


INK = "#231f20"                      # the guides' own black
def cut(page_svg: Path, region, out: Path, drop=(), recolour=None, screen=None,
        marks=(), erase=(), flat=None, stretch=None, move=()) -> None:
    x, y, width, height = region
    tree = ET.parse(page_svg)
    root = tree.getroot()
    _keep_inside(root, (1, 0, 0, 1, 0, 0), (x, y, x + width, y + height))
    if erase:
        _erase(root, erase)
    if move:
        _move(root, move)
    _restyle(root, drop, recolour)
    if flat:
        _flatten(root, flat)
    if screen:
        _blank(root, screen)
    _drop_unused(root)
    matrix = None
    if stretch:
        matrix = _stretch(root, (x, y), stretch)
        width, height = width * stretch[0], height * stretch[1]
    if marks:
        _mark(root, marks, matrix)
    root.set("viewBox", f"{x} {y} {width:g} {height:g}")
    root.set("width", f"{width:g}pt")
    root.set("height", f"{height:g}pt")
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="utf-8", xml_declaration=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("guides", type=Path, help="the folder holding the user guides")
    parser.add_argument("remotes", type=Path, nargs="+", help="remote folders to draw")
    args = parser.parse_args(argv)
    for folder in args.remotes:
        source = json.loads((folder / "art.json").read_text(encoding="utf-8"))["source"]
        with tempfile.TemporaryDirectory() as work:
            # a guide kept only as its page's SVG - pdftocairo's, the remote's page - is
            # that page already
            page = args.guides / source["guide"]
            if page.suffix.lower() != ".svg":
                page = Path(work) / "page.svg"
                subprocess.run(["pdftocairo", "-svg", "-f", str(source["page"]),
                                "-l", str(source["page"]), str(args.guides / source["guide"]),
                                str(page)], check=True)
            out = folder / "art.svg"
            cut(page, source["region"], out, source.get("drop", ()),
                {k.lower(): v for k, v in (source.get("recolour") or {}).items()},
                source.get("screen"), source.get("marks", ()), source.get("erase", ()),
                source.get("flat"), source.get("stretch"), source.get("move", ()))
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
