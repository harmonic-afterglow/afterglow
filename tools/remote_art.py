"""Cut a remote's drawing out of a page of its user guide, as an SVG the editors draw.

Logitech's user guides draw each remote as line art - every key its own outline, the
printed labels as text - which is exactly the picture people know the remote by. This
turns one page (pdftocairo's SVG of it) into a file holding just the remote: whatever
reaches into the region is kept, at the page's own coordinates, so the key positions in
the remote's `art.json` are the page's points too.

Everything about one remote's drawing lives in its folder (library/remotes/<id>/): the
recipe in `art.json` under "source" - the guide, page and region, callout colours to
leave out, colours to repaint, a mock-up screen to empty, marks to print on the keys -
and the result, `art.svg`, written beside it.

    python3 tools/remote_art.py ../afterglow-site/_sources/manuals \
        src/afterglow/library/remotes/harmony-one src/afterglow/library/remotes/harmony-900

The first argument is the folder holding the user guides. Needs pdftocairo (poppler), but
not for a guide kept only as the SVG of its remote's page.
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


def _mark(root, marks) -> None:
    """Print on the keys what the guide's drawing leaves off: the 1100's is drawn
    blank, and the 900's colour keys are drawn black. Each mark is a label - {"text", "x", "y", "size"}, centred on x, y - or a
    symbol, {"d"} in the drawing's points, filled in black or its "fill" colour, and
    outlined with "stroke" - a width."""
    layer = ET.SubElement(root, NS + "g", {"id": "afterglow-marks", "fill": INK})
    for mark in marks:
        if "text" in mark:
            label = ET.SubElement(layer, NS + "text", {
                "x": str(mark["x"]), "y": str(mark["y"] + mark["size"] * 0.36),
                "font-family": "Helvetica, Arial, sans-serif", "font-weight": "bold",
                "font-size": str(mark["size"]), "text-anchor": "middle"})
            label.text = mark["text"]
        else:
            outlined = mark.get("stroke")
            fill = mark.get("fill") or ("none" if outlined else INK)
            ET.SubElement(layer, NS + "path", {
                "d": mark["d"], "fill": fill,
                **({"stroke": INK, "stroke-width": str(outlined),
                    "stroke-linecap": "round", "stroke-linejoin": "round"}
                   if outlined else {})})


INK = "#231f20"                      # the guides' own black


def cut(page_svg: Path, region, out: Path, drop=(), recolour=None, screen=None,
        marks=()) -> None:
    x, y, width, height = region
    tree = ET.parse(page_svg)
    root = tree.getroot()
    _keep_inside(root, (1, 0, 0, 1, 0, 0), (x, y, x + width, y + height))
    _restyle(root, drop, recolour)
    if screen:
        _blank(root, screen)
    if marks:
        _mark(root, marks)
    _drop_unused(root)
    root.set("viewBox", f"{x} {y} {width} {height}")
    root.set("width", f"{width}pt")
    root.set("height", f"{height}pt")
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
                source.get("screen"), source.get("marks", ()))
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
