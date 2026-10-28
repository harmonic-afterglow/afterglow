"""The pictures a build composes for itself: a device or activity type's icon on the frame
it is drawn over, an activity's icon on its starting screen, and a favourite's logo on its
button - each composed so it needs no transparency.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

from pathlib import Path

from .pages import MENU_FRAME_XY, MENU_ICON_XY


# A device row's icon sits over the row frame's left end: this patch of the frame.
ROW_ICON_SIZE = (51, 48)


def row_icon(directory, manifest: dict, pictures: dict, kind: str,
             name: str | None, frame: str = "row-frame") -> str | None:
    """Compose the row icon for a ``kind`` of type ``name`` into ``pictures``, once per
    icon and frame, and return its role (row_icons.py); None when the scaffold has no
    type icons. Activities' rows are drawn on their own frame (``activity/row-frame``),
    so their icons carry that frame's patch rather than a device row's."""
    role = row_icons_role(kind, name, directory, frame)
    if role is not None and role not in pictures:
        at = (MENU_ICON_XY[0][0] - MENU_FRAME_XY[0][0], MENU_ICON_XY[0][1] - MENU_FRAME_XY[0][1])
        pictures[role] = _composed(directory, manifest, frame, at, ROW_ICON_SIZE, kind, name)
    return role


def row_icons_role(kind, name, directory, frame="row-frame"):
    from . import row_icons

    role = row_icons.role(kind, name, directory)
    if role is None or frame == "row-frame":
        return role
    return f"{frame.rsplit('/', 1)[0]}/{role}"


# Where an activity's icon sits on the screen it starts on, and the box it is fitted to.
START_ICON_XY, START_ICON_SIZE = (57, 67), (62, 42)
SENDING_XY = (57, 33)


def start_icon(directory, manifest: dict, pictures: dict, name: str | None) -> str | None:
    """Compose the icon an activity of type ``name`` shows while it starts: its type
    icon on the patch of the backdrop it is drawn over, so it needs no transparency."""
    from . import row_icons

    path = row_icons.source(directory, "activities", name)
    if path is None or "backdrop" not in manifest["pictures"]:
        return None
    role = f"activity/start-icon/{path.stem}"
    if role not in pictures:
        pictures[role] = _composed(directory, manifest, "backdrop", START_ICON_XY,
                                   START_ICON_SIZE, "activities", name, box=START_ICON_SIZE)
    return role


# A favourite's logo sits inside its button's frame, clear of the bevel.
LOGO_BOX = (73, 42)


def logo_file(name) -> Path | None:
    """A favourite's logo: a path, or a name in the owner's logos folder (paths.py)."""
    from ... import paths

    if not name:
        return None
    for path in (Path(name), paths.logos_dir() / str(name)):
        if path.is_file():
            return path
    return None


def favourite_picture(directory, manifest, pictures, image, position, skipped,
                      where) -> str | None:
    """Compose a favourite's logo onto the frame of the button place it is drawn in, so
    it needs no transparency; None, and a note, when the logo cannot be found."""
    from ... import imaging
    from . import assets, bitmap, row_icons

    path = logo_file(image)
    if path is None:
        if image:
            skipped.append(f"{where}: no logo {image!r}; its name is drawn instead")
        return None
    frame = f"activity/button-frame/{position}"
    if frame not in manifest["pictures"]:
        frame = f"button-frame/{position}"
    role = f"favourite/{path.stem}/{position}"
    if role not in pictures:
        under = imaging.decode((Path(directory) / manifest["pictures"][frame]["file"])
                               .read_bytes())["rows"]
        logo = imaging.decode(path.read_bytes())["rows"]
        size = (len(under[0]), len(under))
        rows = row_icons.compose(under, (0, 0), size, logo, LOGO_BOX)
        image_ = {"width": size[0], "height": size[1], "rows": rows}
        pictures[role] = bitmap.encode(assets.to_rows(image_)[0], mode=assets.MODES["shorter"])
    return role


# A button's icon - one of the glyphs the editors offer (icons/buttons), the 900's own -
# fills its frame, clear of the bevel, and the label is drawn over it, as on Logitech's
# builds.
BUTTON_ICON_BOX = (73, 44)


def button_picture(directory, manifest, pictures, icon, position, skipped,
                   where) -> str | None:
    """An activity button's frame with its icon on it, for the place it is in - its label
    is drawn over it; None, and a note, when there is no such icon. Icons were never drawn on the One:
    the editors offered them and the remote showed the label alone."""
    from ... import imaging, paths
    from . import assets, bitmap, row_icons

    path = paths.icons("buttons", f"{icon}.png") if icon else None
    if path is None or not path.is_file():
        if icon:
            skipped.append(f"{where}: no icon {icon!r}; the label is drawn alone")
        return None
    frame = f"activity/button-frame/{position}"
    if frame not in manifest["pictures"]:
        frame = f"button-frame/{position}"
    role = f"button-icon/{icon}/{position}"
    if role not in pictures:
        under = imaging.decode((Path(directory) / manifest["pictures"][frame]["file"])
                               .read_bytes())["rows"]
        glyph = imaging.decode(path.read_bytes())["rows"]
        size = (len(under[0]), len(under))
        rows = row_icons.compose(under, (0, 0), size, glyph, BUTTON_ICON_BOX)
        image_ = {"width": size[0], "height": size[1], "rows": rows}
        pictures[role] = bitmap.encode(assets.to_rows(image_)[0], mode=assets.MODES["shorter"])
    return role


def _composed(directory, manifest, frame, at, size, kind, name, box=None) -> bytes:
    from ... import imaging
    from . import assets, bitmap, row_icons

    under = imaging.decode((Path(directory) / manifest["pictures"][frame]["file"])
                           .read_bytes())["rows"]
    icon = imaging.decode(row_icons.source(directory, kind, name).read_bytes())["rows"]
    rows = row_icons.compose(under, at, size, icon, box or row_icons.FIT)
    image = {"width": size[0], "height": size[1], "rows": rows}
    return bitmap.encode(assets.to_rows(image)[0], mode=assets.MODES["shorter"])
