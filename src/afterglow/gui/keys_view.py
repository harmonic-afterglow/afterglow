"""The remote's keys as a picture of the remote: what each key does, at a glance.

The device editor's Commands and the activity editor's Physical buttons both say what
the remote's own keys do, and both were tables - forty rows of key names to read
through to find the one under your thumb. Here the remote is drawn as its user guide
draws it (its folder's `art.svg` and `art.json`), each key tinted by what it does, its
action on hover, and a click on it to change it. A remote nobody has drawn yet gets its keys as
the grid of its `hard_key_layout` - or, failing that, of its key names - so every
remote has the view.

Both pages keep their table as well: some people read a list faster than a picture,
and the choice between them is remembered (`KeysViewChoice`).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..qt.QtCore import QPointF, QRect, QRectF, QSettings, QSize, Qt, pyqtSignal
from ..qt.QtGui import (QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QRegion,
                        QTransform)
from ..qt.QtSvg import QSvgRenderer
from ..qt.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QSizePolicy,
                             QToolButton, QToolTip, QWidget)

# What a key can be, and its colour. Assigned: it sends something of this device's.
# Changed: the activity gives it something of its own. Default: the activity leaves it
# to its devices. Free: nothing. A key the remote keeps for itself is greyed.
ASSIGNED, CHANGED, DEFAULT, FREE = "assigned", "changed", "default", "free"
TINTS = {ASSIGNED: QColor(150, 190, 250), CHANGED: QColor(250, 196, 90),
         DEFAULT: QColor(205, 205, 205), FREE: None}
DARK = QColor(150, 150, 156)  # multiplied: the key greyed, its label still read
MARKS = "afterglow-marks"       # the layer tools/remote_art.py prints on the keys
CELL = 24.0           # a grid key's height, in the grid's own units


class RemoteKeys(QWidget):
    key_clicked = pyqtSignal(str)
    # one of the remote's own keys that can be chosen rather than assigned - a 650's
    # Watch TV, which starts the activity given it (set_choices)
    fixed_clicked = pyqtSignal(str)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._profile = profile
        self._states: dict[str, tuple[str, str]] = {}
        self._hover = None
        self._selected = None
        self._svg = None
        self._fixed: dict[str, QPainterPath] = {}
        # the drawing's parts shown, each (its rectangle in the drawing, where it goes):
        # the whole view, or the parts above and below a cut band
        self._parts: list[tuple[QRectF, QTransform]] = []
        self._choosable: dict[str, str] = {}
        self._chosen = None
        art = getattr(profile, "hard_key_art", None)
        if art and art["svg"].is_file():
            renderer = QSvgRenderer(str(art["svg"]))
            if renderer.isValid():
                self._svg = renderer
                self._view = QRectF(*art["view"]) if art["view"] else renderer.viewBoxF()
                self._body, self._keys, self._fixed = _shapes(renderer, art, self._view)
                self._labels = {}
                self._fold(art.get("cut"))
        if self._svg is None:
            boxes, self._labels, self._view = _grid(profile)
            self._keys = {}
            for key, box in boxes.items():
                shape = QPainterPath()
                radius = min(box.width(), box.height()) / 3
                shape.addRoundedRect(box, radius, radius)
                self._keys[key] = shape

    def _fold(self, cut) -> None:
        """Leave out the band ``cut`` - (top, bottom), or (top, bottom, widen) - and close
        the drawing up over it: what is below moves up, a key inside it (the 650's screen
        keys) goes, and what is above is widened by ``widen`` about the middle, so a case
        that is narrower above the band than below it meets itself at the join."""
        view = self._view
        if not cut:
            self._parts = [(QRectF(view), QTransform())]
            return
        top, bottom, *rest = cut
        widen = rest[0] if rest else 1.0
        gap = bottom - top
        middle = view.center().x()
        above = QTransform().translate(middle, 0).scale(widen, 1).translate(-middle, 0)
        below = QTransform().translate(0, -gap)
        self._parts = [(QRectF(view.x(), view.y(), view.width(), top - view.y()), above),
                       (QRectF(view.x(), bottom, view.width(), view.bottom() - bottom), below)]

        def moved(shape):
            box = shape.boundingRect()
            if box.top() >= bottom:
                return below.map(shape)
            if box.bottom() <= top:
                return above.map(shape)
            if box.top() >= top and box.bottom() <= bottom:
                return None                     # inside the band
            # across it (the case): the parts above and below, closed up
            upper, lower = QPainterPath(), QPainterPath()
            upper.addRect(QRectF(box.x() - 1, box.y() - 1, box.width() + 2, top - box.y() + 1))
            lower.addRect(QRectF(box.x() - 1, bottom, box.width() + 2, box.bottom() - bottom + 1))
            return above.map(shape.intersected(upper)).united(
                below.map(shape.intersected(lower)))
        self._keys = {key: shaped for key, shape in self._keys.items()
                      if (shaped := moved(shape)) is not None}
        self._fixed = {name: shaped for name, shape in self._fixed.items()
                       if (shaped := moved(shape)) is not None}
        self._body = moved(self._body) or QPainterPath()
        self._view = QRectF(view.x(), view.y(), view.width(), view.height() - gap)

    # what each key does
    def set_states(self, states: dict[str, tuple[str, str]]):
        """{key: (ASSIGNED / CHANGED / DEFAULT / FREE, what to say on hover)}."""
        self._states = dict(states)
        self.update()

    def set_choices(self, choosable: dict[str, str], chosen: str | None):
        """Which of the remote's own keys can be clicked, {name: what hovering says},
        and the one chosen, drawn lit where the others stay dark."""
        self._choosable = {name: text for name, text in choosable.items()
                           if name in self._fixed}
        self._chosen = chosen
        self.update()

    def select(self, key):
        self._selected = key
        self.update()

    def keys(self) -> list[str]:
        """Top to bottom, left to right, as they sit on the remote."""
        return sorted(self._keys, key=lambda k: (round(self._keys[k].boundingRect().y()),
                                                 self._keys[k].boundingRect().x()))

    def has_picture(self) -> bool:
        return self._svg is not None

    # geometry: the drawing fitted into the widget, keeping its shape
    def _transform(self) -> QTransform:
        view = self._view
        if view.width() <= 0 or view.height() <= 0:
            return QTransform()
        scale = min(self.width() / view.width(), self.height() / view.height())
        dx = (self.width() - view.width() * scale) / 2 - view.x() * scale
        dy = (self.height() - view.height() * scale) / 2 - view.y() * scale
        return QTransform(scale, 0, 0, scale, dx, dy)

    def key_at(self, point) -> str | None:
        inverted, ok = self._transform().inverted()
        if not ok:
            return None
        where = inverted.map(QPointF(point))
        for key, shape in self._keys.items():
            if shape.contains(where):
                return key
        return None

    def fixed_at(self, point) -> str | None:
        inverted, _ok = self._transform().inverted()
        where = inverted.map(QPointF(point))
        return next((name for name, shape in self._fixed.items()
                     if shape.contains(where)), None)

    # Small, and growing with the window: the editor's section scrolls rather than
    # cut the drawing off, so asking for its full height cost the bottom of the remote.
    def sizeHint(self):
        """As the drawing is shaped: a tall remote 420 high, a wide one 520 across."""
        if self._svg is None:
            return QSize(320, 300)
        aspect = self._view.width() / max(self._view.height(), 1)
        if aspect < 1:
            return QSize(round(420 * aspect), 420)
        return QSize(520, round(520 / aspect))

    def minimumSizeHint(self):
        return QSize(120, 240) if self._svg is not None else QSize(240, 160)

    # drawing
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        transform = self._transform()
        if self._svg is not None:
            painter.save()
            painter.setClipRect(transform.mapRect(self._view))
            painter.save()
            painter.setTransform(transform)
            painter.fillPath(self._body, QColor("white"))
            painter.restore()
            for part, placed in self._parts:
                painter.save()
                painter.setTransform(placed * transform)
                painter.setClipRect(part)
                self._svg.setViewBox(part)
                self._svg.render(painter, part)
                painter.restore()
            painter.restore()
        painter.setTransform(transform)
        pen_width = 2 / max(transform.m11(), 0.01)
        for key, shape in self._keys.items():
            state = self._states.get(key, (FREE, ""))[0]
            tint = TINTS.get(state)
            if self._svg is None:                     # a grid key is drawn whole
                painter.fillPath(shape, self.palette().button())
                if tint is not None:
                    painter.fillPath(shape, tint)
                painter.setPen(QPen(self.palette().mid().color(), pen_width / 2))
                painter.drawPath(shape)
                painter.setPen(self.palette().buttonText().color())
                painter.drawText(shape.boundingRect(), Qt.AlignmentFlag.AlignCenter,
                                 self._labels.get(key, key))
            elif tint is not None:
                # Under the drawing's own lines and print: multiplied onto the white
                # of the key, the black of its outline and label stays black.
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                painter.fillPath(shape, tint)
                painter.restore()
            if key in (self._selected, self._hover):
                # In the selection colour, wider when chosen than when pointed at: the
                # drawing's own outlines are black, so a dark ring would not show.
                colour = QColor(self.palette().highlight().color())
                painter.setPen(QPen(colour, pen_width * (1.5 if key == self._selected
                                                         else 1)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(shape)
        for name, shape in self._fixed.items():
            if name == self._chosen:
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                painter.fillPath(shape, TINTS[ASSIGNED])
                painter.restore()
            else:
                painter.save()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                painter.fillPath(shape, DARK)
                painter.restore()
            if name in self._choosable and name == self._hover:
                painter.setPen(QPen(QColor(self.palette().highlight().color()), pen_width))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(shape)
        # What tools/remote_art.py printed on the keys - the 900's colour bars, the
        # 1100's symbols - again on top, so a lit key keeps its red or its arrow.
        if self._svg is not None and self._svg.elementExists(MARKS):
            bounds = self._svg.boundsOnElement(MARKS)
            for part, placed in self._parts:
                painter.save()
                painter.setTransform(placed * transform)
                painter.setClipRect(part)
                self._svg.render(painter, MARKS, bounds)
                painter.restore()
        painter.end()

    # hover and click
    def mouseMoveEvent(self, event):
        key = self.key_at(event.position())
        fixed = None if key else self.fixed_at(event.position())
        hover = key or (fixed if fixed in self._choosable else None)
        if hover != self._hover:
            self._hover = hover
            self.update()
        if key:
            text = self._states.get(key, (FREE, ""))[1] or self.label(key)
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        elif fixed in self._choosable:
            QToolTip.showText(event.globalPosition().toPoint(),
                              self._choosable[fixed], self)
        elif fixed:
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{fixed}: the remote's own key, not assignable", self)
        else:
            QToolTip.hideText()
        self.setCursor(Qt.CursorShape.PointingHandCursor if hover
                       else Qt.CursorShape.ArrowCursor)

    def label(self, key) -> str:
        return key_label(self._profile, key)

    def leaveEvent(self, _event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        key = self.key_at(event.position())
        if key:
            self.key_clicked.emit(key)
            return
        fixed = self.fixed_at(event.position())
        if fixed in self._choosable:
            self.fixed_clicked.emit(fixed)


def key_label(profile, key) -> str:
    """The profile's name for a key, or the key's own without a profile."""
    labeller = getattr(profile, "key_label", None)
    return labeller(key) if labeller else key


# The drawing's outlines, read once: every path that is drawn with a line, as a shape in
# the drawing's coordinates. A key is lit by the smallest of them that surrounds it, cut
# to the key - so one half of the volume rocker lights alone.
_NS = "{http://www.w3.org/2000/svg}"
_NUMBER = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")
_TOKENS = re.compile(r"[MLCZ]|-?\d*\.?\d+(?:e-?\d+)?")


def _outlines(svg) -> list[QPainterPath]:
    found = []

    def walk(element, transform):
        for child in element:
            # The printing added on the keys (tools/remote_art.py) outlines nothing.
            if child.tag == _NS + "defs" or child.get("id") == MARKS:
                continue
            inner = _transform_of(child.get("transform")) * transform
            if child.tag == _NS + "path" and child.get("stroke") not in (None, "none"):
                path = _path(child.get("d", ""))
                if not path.isEmpty():
                    found.append(inner.map(path))
            walk(child, inner)
    walk(ET.parse(svg).getroot(), QTransform())
    return found


def _transform_of(text) -> QTransform:
    if not text:
        return QTransform()
    values = [float(v) for v in _NUMBER.findall(text)]
    if text.startswith("matrix"):
        return QTransform(*values)
    if text.startswith("translate"):
        return QTransform.fromTranslate(values[0], values[1] if len(values) > 1 else 0)
    return QTransform()


def _path(d) -> QPainterPath:
    """A path as pdftocairo writes one: absolute moves, lines, curves and closes."""
    path = QPainterPath()
    tokens = _TOKENS.findall(d)
    command, i = None, 0
    while i < len(tokens):
        token = tokens[i]
        if token in "MLCZ":
            command = token
            i += 1
            if token == "Z":
                path.closeSubpath()
            continue
        if command == "C":
            x1, y1, x2, y2, x, y = (float(v) for v in tokens[i:i + 6])
            path.cubicTo(x1, y1, x2, y2, x, y)
            i += 6
        else:
            x, y = float(tokens[i]), float(tokens[i + 1])
            (path.moveTo if command == "M" else path.lineTo)(x, y)
            command = "L" if command == "M" else command
            i += 2
    return path


def _clip(box) -> QPainterPath:
    """A key's box as art.json gives it: x, y, width, height, or a wedge's corners."""
    clip = QPainterPath()
    if len(box) == 4:
        clip.addRect(QRectF(*box))
    else:
        clip.addPolygon(QPolygonF([QPointF(box[i], box[i + 1])
                                   for i in range(0, len(box), 2)]))
        clip.closeSubpath()
    return clip


def _key_shape(outlines, box) -> QPainterPath:
    """The key's own part of the smallest outline around it; its box when none is.

    `box` is x, y, width, height - or, for a key that is a slice of a ring, the corners
    of the wedge that cuts it out, x1, y1, x2, y2, ... ."""
    clip = _clip(box)
    around = clip.boundingRect().adjusted(0.8, 0.8, -0.8, -0.8)
    surrounding = [o for o in outlines if o.boundingRect().contains(around)]
    if not surrounding:
        return clip
    outline = min(surrounding, key=lambda o: o.boundingRect().width()
                  * o.boundingRect().height())
    filled = QPainterPath(outline)
    filled.setFillRule(Qt.FillRule.WindingFill)
    return filled.intersected(clip)


class _Faces:
    """Each key's face as the drawing paints it: the white inside its outline.

    A key is lit by filling its shape, and the shape `_key_shape` finds is the key's
    outline clipped to its box - or the box itself where the drawing has no closed
    outline around it, as the 800's guide, which draws each outline as many short
    strokes. A box is square-cornered and the key is not, so the tint spilled past its
    rounded corners. So the drawing is rendered once, and a key's shape becomes the
    largest white area inside it - the key's face, cut off by the outline's own ink -
    grown by a pixel, under the outline, which a multiplied tint leaves black."""

    SCALE = 6.0            # pixels to a drawing point
    LIGHT = 200            # a pixel this bright or brighter is the key's paper

    def __init__(self, renderer, view: QRectF):
        self._view = view
        width = max(1, round(view.width() * self.SCALE))
        height = max(1, round(view.height() * self.SCALE))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("white"))
        painter = QPainter(image)
        renderer.setViewBox(view)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
        grey = image.convertToFormat(QImage.Format.Format_Grayscale8)
        stride = grey.bytesPerLine()
        bits = grey.constBits()
        if hasattr(bits, "setsize"):
            bits.setsize(stride * height)
        raw = bytes(bits)
        self._light = [raw[y * stride:y * stride + width] for y in range(height)]
        self._size = (width, height)
        self._to_view = (QTransform().translate(view.x(), view.y())
                         .scale(1 / self.SCALE, 1 / self.SCALE))

    def case(self) -> QPainterPath:
        """The remote's case: on each row of the drawing, from its first ink to its last.
        A guide may draw the case as many short strokes (the 800's), with no one outline
        to fill, and the window would show through."""
        width, height = self._size
        left, right = [], []
        for y in range(0, height, 2):
            row = self._light[y]
            dark = [x for x in range(width) if row[x] < self.LIGHT]
            if dark:
                left.append(QPointF(dark[0], y))
                right.append(QPointF(dark[-1] + 1, y))
        shape = QPainterPath()
        if left:
            shape.addPolygon(QPolygonF(left + right[::-1]))
            shape.closeSubpath()
        return self._to_view.map(shape)

    def _pixel_box(self, shape: QPainterPath):
        width, height = self._size
        box = shape.boundingRect()
        x0 = max(0, int((box.left() - self._view.x()) * self.SCALE))
        y0 = max(0, int((box.top() - self._view.y()) * self.SCALE))
        x1 = min(width, int((box.right() - self._view.x()) * self.SCALE) + 1)
        y1 = min(height, int((box.bottom() - self._view.y()) * self.SCALE) + 1)
        return x0, y0, x1, y1

    def _largest(self, shape: QPainterPath) -> list | None:
        """The largest white area inside ``shape``, a key's box, as pixels; None where
        it holds none - the drawing leaves the key blank, or it is too small to tell."""
        x0, y0, x1, y1 = self._pixel_box(shape)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        inside = self._to_view.inverted()[0].map(shape)
        light, seen, best = self._light, set(), []
        for y in range(y0, y1):
            for x in range(x0, x1):
                if (x, y) in seen or light[y][x] < self.LIGHT \
                        or not inside.contains(QPointF(x + 0.5, y + 0.5)):
                    continue
                area, todo = [], [(x, y)]
                seen.add((x, y))
                while todo:
                    cx, cy = todo.pop()
                    area.append((cx, cy))
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if x0 <= nx < x1 and y0 <= ny < y1 and (nx, ny) not in seen \
                                and light[ny][nx] >= self.LIGHT:
                            seen.add((nx, ny))
                            todo.append((nx, ny))
                if len(area) > len(best):
                    best = area
        return best if len(best) >= 4 else None

    def _whole(self, start, limit: int) -> set | None:
        """The white area ``start`` is in, as far as it goes; None when it goes past
        ``limit`` pixels - out of an outline that is not closed, into the case."""
        width, height = self._size
        light = self._light
        area, todo = {start}, [start]
        while todo:
            cx, cy = todo.pop()
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in area \
                        and light[ny][nx] >= self.LIGHT:
                    area.add((nx, ny))
                    todo.append((nx, ny))
                    if len(area) > limit:
                        return None
        return area

    def _path(self, pixels, clip: QPainterPath | None = None) -> QPainterPath:
        """Pixels as a path in the drawing's units, each grown by one under the ink."""
        rows: dict[int, list[int]] = {}
        for x, y in pixels:
            rows.setdefault(y, []).append(x)
        region = QRegion()
        for y, xs in rows.items():
            xs.sort()
            start = previous = xs[0]
            for x in xs[1:] + [None]:
                if x is not None and x == previous + 1:
                    previous = x
                    continue
                region = region.united(QRegion(QRect(start - 1, y - 1, previous - start + 3, 3)))
                if x is not None:
                    start = previous = x
        face = QPainterPath()
        face.addRegion(region)
        face = self._to_view.map(face).simplified()
        return face.intersected(clip) if clip is not None else face

    def of(self, shape: QPainterPath) -> QPainterPath | None:
        """The face inside ``shape``, a key's box, and what it encloses; None where the
        box holds no white."""
        best = self._largest(shape)
        if best is None:
            return None
        return self._path(_filled_area(best, self._pixel_box(shape)), shape)

    def all(self, boxes: dict) -> dict:
        """Each key's face, by the keys' names: the whole white inside the outline its
        box is in, where several keys share one outline - a d-pad's arrows, a rocker's
        two ends, Play and Pause - shared out between them, each part to the key whose
        box is nearest, so a lit key fills its part of the shape and not only its box.
        A key whose white runs out of its outline into the case keeps its box's part."""
        clips = {name: _clip(box) for name, box in boxes.items()}
        rects = {name: self._pixel_box(clip) for name, clip in clips.items()}
        owner: dict = {}                    # a pixel's outline, by its index
        outlines: list[dict] = []
        out = {}
        for name, clip in clips.items():
            best = self._largest(clip)
            if best is None:
                continue
            x0, y0, x1, y1 = rects[name]
            start = best[0]
            if start in owner:
                outlines[owner[start]]["keys"].append(name)
                continue
            # an outline is at most a few keys big; more is the case showing through
            area = self._whole(start, limit=max(4000, 12 * (x1 - x0) * (y1 - y0)))
            if area is None:
                out[name] = self._path(_filled_area(best, rects[name]), clip)
                continue
            index = len(outlines)
            outlines.append({"area": area, "keys": [name]})
            for pixel in area:
                owner[pixel] = index
        for outline in outlines:
            area, names = outline["area"], outline["keys"]
            xs = [x for x, _y in area]
            ys = [y for _x, y in area]
            bounds = (min(xs) - 1, min(ys) - 1, max(xs) + 2, max(ys) + 2)
            filled = _filled_area(list(area), bounds)
            if len(names) == 1:
                out[names[0]] = self._path(filled)
                continue
            inside = {name: self._to_view.inverted()[0].map(clips[name]) for name in names}
            parts: dict = {name: [] for name in names}
            for x, y in filled:
                point = QPointF(x + 0.5, y + 0.5)
                within = [name for name in names if inside[name].contains(point)]
                if len(within) == 1:
                    parts[within[0]].append((x, y))
                    continue
                parts[min(within or names, key=lambda name: _distance(rects[name], x, y))
                      ].append((x, y))
            for name, pixels in parts.items():
                if pixels:
                    out[name] = self._path(pixels)
        return out


def _distance(rect, x, y) -> float:
    """How far pixel x, y is from the rectangle (x0, y0, x1, y1); 0 inside it."""
    x0, y0, x1, y1 = rect
    dx = max(x0 - x, 0, x - x1 + 1)
    dy = max(y0 - y, 0, y - y1 + 1)
    return (dx * dx + dy * dy) ** 0.5


def _filled_area(face: list, bounds) -> list:
    """``face`` and whatever it encloses - the inside of a letter's o, of a key's icon -
    so a tint covers them: every pixel of ``bounds`` that cannot reach its edge without
    crossing the face."""
    x0, y0, x1, y1 = bounds
    taken = set(face)
    outside = set()
    todo = [(x, y) for x in range(x0, x1) for y in (y0, y1 - 1)] + \
           [(x, y) for y in range(y0, y1) for x in (x0, x1 - 1)]
    todo = [point for point in todo if point not in taken]
    outside.update(todo)
    while todo:
        cx, cy = todo.pop()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if x0 <= nx < x1 and y0 <= ny < y1 and (nx, ny) not in taken \
                    and (nx, ny) not in outside:
                outside.add((nx, ny))
                todo.append((nx, ny))
    return [(x, y) for y in range(y0, y1) for x in range(x0, x1) if (x, y) not in outside]


_SHAPES: dict = {}       # a drawing's case and key shapes, worked out once a session


def _shapes(renderer, art: dict, view: QRectF):
    """(the case, {key: shape}, {remote's own key: shape}) for ``art``, the drawing's
    units; worked out from the rendered drawing once, then kept."""
    svg = art["svg"]
    known = (str(svg), svg.stat().st_mtime, view.getRect(),
             repr(sorted(art["keys"].items())), repr(sorted(art["unassignable"].items())))
    if known in _SHAPES:
        body, keys, fixed = _SHAPES[known]
        return QPainterPath(body), dict(keys), dict(fixed)
    outlines = _outlines(svg)
    faces = _Faces(renderer, view)
    # the case, filled white under the drawing - a guide may draw it as a line only,
    # and the window would show through
    body = faces.case()
    # every key at once: keys that share an outline - a d-pad, a rocker - share out
    # its face between them
    boxes = {**{("key", key): box for key, box in art["keys"].items()},
             **{("fixed", name): box for name, box in art["unassignable"].items()}}
    found = faces.all(boxes)

    def shape(which, box):
        return found.get(which) or _key_shape(outlines, box)
    keys = _without_inner({key: shape(("key", key), box) for key, box in art["keys"].items()})
    fixed = {name: shape(("fixed", name), box) for name, box in art["unassignable"].items()}
    _SHAPES[known] = (body, keys, fixed)
    return QPainterPath(body), dict(keys), dict(fixed)


def _without_inner(shapes: dict) -> dict:
    """Each key less any key inside it: a d-pad's ring is drawn around its OK."""
    def size(path):
        box = path.boundingRect()
        return box.width() * box.height()

    out = {}
    for key, shape in shapes.items():
        for other, inner in shapes.items():
            if other != key and size(inner) < size(shape) and shape.intersects(inner):
                shape = shape.subtracted(inner)
        out[key] = shape
    return out


def _grid(profile):
    """Keys as cells of the profile's grid layout, or of its key names four a row."""
    layout = list(getattr(profile, "hard_key_layout", None) or [])
    if not layout:
        layout = [{"row": i // 4, "column": i % 4, "rows": 1, "columns": 1, "key": key,
                   "label": key}
                  for i, key in enumerate(getattr(profile, "hard_keys", None) or [])]
    keys, labels = {}, {}
    width = CELL * 3.2
    for cell in layout:
        if not cell.get("key"):
            continue
        keys[cell["key"]] = QRectF(cell["column"] * width + 2, cell["row"] * CELL + 2,
                                   cell["columns"] * width - 4, cell["rows"] * CELL - 4)
        labels[cell["key"]] = cell.get("label") or cell["key"]
    right = max((box.right() for box in keys.values()), default=width)
    bottom = max((box.bottom() for box in keys.values()), default=CELL)
    return keys, labels, QRectF(0, 0, right + 2, bottom + 2)


def legend(entries) -> QWidget:
    """A row of tinted swatches naming the states a view uses."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for state, text in entries:
        swatch = QLabel()
        swatch.setFixedSize(14, 14)
        tint = TINTS.get(state)
        swatch.setStyleSheet(
            "border: 1px solid palette(mid); border-radius: 3px; background: "
            + (f"rgb({tint.red()},{tint.green()},{tint.blue()})" if tint
               else "transparent") + ";")
        layout.addWidget(swatch)
        layout.addWidget(QLabel(text))
        layout.addSpacing(8)
    layout.addStretch()
    return row


class KeysViewChoice(QWidget):
    """Picture or List, remembered for everyone's next visit to either page."""
    changed = pyqtSignal(bool)                 # True for the picture

    KEY = "keys_view/picture"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.picture = QToolButton()
        self.picture.setText("Picture")
        self.listed = QToolButton()
        self.listed.setText("List")
        group = QButtonGroup(self)
        for button in (self.picture, self.listed):
            button.setCheckable(True)
            group.addButton(button)
            layout.addWidget(button)
        picture = QSettings().value(self.KEY, True, type=bool)
        (self.picture if picture else self.listed).setChecked(True)
        # Clicked, not toggled: only a person's choice is remembered.
        group.buttonClicked.connect(lambda button: self._chosen(button is self.picture))

    def _chosen(self, picture):
        QSettings().setValue(self.KEY, picture)
        self.changed.emit(picture)

    def show_picture(self, picture: bool):
        (self.picture if picture else self.listed).setChecked(True)
        self.changed.emit(picture)

    def is_picture(self) -> bool:
        return self.picture.isChecked()
