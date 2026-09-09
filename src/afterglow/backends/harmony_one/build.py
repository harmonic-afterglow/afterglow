"""Turn a portable Harmony One project into native operations on its own baseline.

Every other module here changes one native structure. This one decides which of those
changes a project is actually asking for, applies them in an order that keeps each
step's evidence valid, and accounts for every byte that moved. It never invents a base
image: an authored Harmony One is the user's own image with a bounded set of edits, so
what it cannot express is reported rather than dropped.

Format reference: docs/harmony_one/gspm.md
"""

from __future__ import annotations

import hashlib

from . import (
    authoring,
    command_index,
    font_index,
    glyph_codec,
    gspm,
    inventory,
    relocation,
    screen_program,
    ui_index,
)


def page_layout(sizes: list[int], commands: int) -> list[int] | None:
    """Split a command count into page sizes the image has slot shapes for.

    The donors offer 6, 4 and 2 button slots in one image and 6, 5, 3 and 2 in the
    other, so how many buttons a page holds is a property of the image rather than a
    constant. Prefer the fewest pages, then the fullest first page.
    """
    if commands < 1:
        raise ValueError("a device needs at least one command to lay out")
    usable = sorted({size for size in sizes if size > 0}, reverse=True)
    if not usable:
        return None
    best: dict[int, list[int]] = {0: []}
    for total in range(1, commands + 1):
        for size in usable:
            if size <= total and total - size in best:
                candidate = [size] + best[total - size]
                if total not in best or len(candidate) < len(best[total]):
                    best[total] = candidate
    return best.get(commands)


def _native_devices(payload: bytes) -> dict[str, int]:
    menus = inventory.inspect(payload)["ui"]["device_menus"]
    return {
        item["label"]: item["device_index"]
        for item in menus["devices"] if item.get("label")
    }


def label_fonts(payload: bytes) -> dict:
    """Return the font attribute each kind of authored text would be drawn in."""
    out = {}
    sources = authoring.command_screen_sources(payload)
    numbered = [
        source for source in sources
        if screen_program.page_indicator(
            payload, source["program_offset"], screen_program.PAGE_NUMBER_XY) is not None
    ]
    if numbered:
        source = max(numbered, key=lambda item: len(item["command_key_codes"]))
        out["button"] = screen_program.buttons(
            payload, source["program_offset"])[0]["attribute"]
        prologue = ui_index.drawing_program(
            payload, source["program_offset"])["instructions"][0]
        if prologue["opcode"] == "call":
            counter = screen_program.page_indicator(
                payload, prologue["target"], screen_program.PAGE_TOTAL_XY)
            title = screen_program.screen_title(payload, prologue["target"])
            if title is not None and counter is not None:
                out["title"] = _title_attribute(payload, prologue["target"])
    menus = ui_index.device_menus(payload)
    if menus["menus"]:
        screens = ui_index.screen_slots(payload)
        slot = screens[menus["menus"][0]["screen"]]["slots"][-1]
        rows = screen_program.menu_rows(payload, slot["program_offset"])
        if rows:
            out["menu"] = screen_program._row_attribute(
                payload, slot["program_offset"], rows[0])
    return out


def _title_attribute(payload: bytes, prologue_offset: int) -> int:
    program = ui_index.drawing_program(payload, prologue_offset)
    attribute = None
    for item in program["instructions"]:
        if item["opcode"] == "attribute":
            attribute = item["value"]
        elif (item["opcode"] in ("text", "inline_text")
                and (item["x"], item["y"]) == screen_program.TITLE_XY):
            return attribute
    raise ValueError("this prologue draws no title")


def undrawable(payload: bytes, attribute: int, text: str, report: dict) -> str:
    """Return the characters of ``text`` this font attribute cannot draw."""
    widths = screen_program.glyph_widths(payload, attribute)
    codes = report["character_to_code"]
    return "".join(sorted({
        character for character in set(text)
        if character not in codes or codes[character] not in widths
    }))


def plan(project: dict, payload: bytes) -> dict:
    """Describe what a project asks of its baseline, including what cannot be done.

    Drawability is judged against the fonts the build will have, not the ones the image
    starts with, because completing fonts is the build's own first step.
    """
    gspm.validate(payload)
    existing = _native_devices(payload)
    completed, _report = font_index.complete(payload)
    fonts = label_fonts(completed)
    glyphs = glyph_codec.inspect(completed)
    sources = authoring.command_screen_sources(completed)
    sizes = sorted({
        len(source["command_key_codes"]) for source in sources
        if screen_program.page_indicator(
            completed, source["program_offset"],
            screen_program.PAGE_NUMBER_XY) is not None
    })
    capacity = authoring.menu_capacity(completed)
    can_grow = (
        capacity["every_page_numbered"] and capacity["replicas_agree_on_pages"]
        and bool(capacity["replicas"]))

    add = []
    keep = []
    refused = []
    for device in project.get("devices") or []:
        name = device.get("label") or ""
        signals = device.get("signals") or {}
        if name and name in existing:
            keep.append(name)
            continue
        if not name:
            refused.append({"device": None, "reason": "a device needs a name"})
            continue
        if not signals:
            refused.append({"device": name, "reason": "a device needs at least one command"})
            continue
        if not can_grow and not capacity["free_rows"]:
            refused.append({
                "device": name,
                "reason": "the Devices menu is full and does not number its pages, so "
                          "it cannot grow one",
            })
            continue
        pages = page_layout(sizes, len(signals))
        if pages is None:
            refused.append({
                "device": name,
                "reason": f"{len(signals)} commands do not divide into this image's "
                          f"page sizes {sizes}",
            })
            continue
        blocked = {}
        for kind, text in (("menu", name), ("title", name)):
            attribute = fonts.get(kind)
            if attribute is None:
                blocked[kind] = "no font"
                continue
            missing = undrawable(completed, attribute, text, glyphs)
            if missing:
                blocked[kind] = missing
        for command in signals:
            attribute = fonts.get("button")
            missing = "" if attribute is None else undrawable(
                completed, attribute, command, glyphs)
            if missing:
                blocked.setdefault("button", "")
                blocked["button"] += missing
        if blocked:
            refused.append({
                "device": name,
                "reason": "this image cannot draw " + ", ".join(
                    f"{kind}: {value!r}" for kind, value in sorted(blocked.items())),
            })
            continue
        add.append({"name": name, "commands": sorted(signals), "pages": pages})
    return {
        "baseline_devices": existing,
        "page_sizes": sizes,
        "fonts": fonts,
        "add_devices": add,
        "unchanged_devices": keep,
        "menu": {
            "replicas": len(capacity["replicas"]),
            "free_rows": capacity["free_rows"],
            "can_grow": can_grow,
        },
        "refused": refused,
        "rejected": {"devices": len(refused)},
    }


def apply(payload: bytes, project: dict, steps: dict, *, library=None) -> tuple[bytes, dict]:
    """Apply a plan to its baseline and account for every changed byte.

    Fonts are completed first so later labels are not limited to the characters the
    image happened to draw. Each device is then given its commands, a titled screen of
    its own pages, and a menu row that opens it, in that order: a screen cannot be
    built before the objects it binds exist, and a menu row cannot open a screen that
    has not been added.
    """
    original = payload
    applied = []
    result, font_report = font_index.complete(payload)
    applied.append({"step": "complete-fonts", "report": font_report})

    signals_by_name = {
        device.get("label"): device.get("signals") or {}
        for device in project.get("devices") or []
    }
    for request in steps["add_devices"]:
        signals = signals_by_name[request["name"]]
        ordered = [signals[name] for name in request["commands"]]
        result, device_report = authoring.add_command_device(
            result, ordered, library=library)
        applied.append({"step": "add-command-device", "report": device_report})

        sources = {
            len(source["command_key_codes"]): source
            for source in authoring.command_screen_sources(result)
            if screen_program.page_indicator(
                result, source["program_offset"],
                screen_program.PAGE_NUMBER_XY) is not None
        }
        missing = sorted({size for size in request["pages"] if size not in sources})
        if missing:
            raise ValueError(
                f"{request['name']} needs numbered {missing} button pages and this "
                "image has none")
        wrappers = list(device_report["wrapper_object_ids"])
        pages, page_sources, labels = [], [], []
        at = 0
        for size in request["pages"]:
            source = sources[size]
            keys = source["command_key_codes"]
            pages.append(list(zip(keys, wrappers[at:at + size])))
            order = screen_program.key_button_order(result, source["template"], sorted(keys))
            labels.append(dict(zip(order, request["commands"][at:at + size])))
            page_sources.append(source)
            at += size
        result, screen_report = authoring.add_command_screen(
            result, pages, sources=page_sources, labels=labels, title=request["name"])
        applied.append({"step": "add-command-screen", "report": screen_report})

        result, menu_report = authoring.add_menu_row(
            result, screen_report["screen"], request["name"])
        applied.append({"step": "add-menu-row", "report": menu_report})

    return result, confinement(original, result, applied)


def confinement(before: bytes, after: bytes, applied: list[dict]) -> dict:
    """Report what the build changed, beside what it was asked to change."""
    ranges = relocation.changed_ranges(before, after)
    ownership_before = command_index.inspect(before)
    ownership_after = command_index.inspect(after)
    menus_before = ui_index.device_menus(before, ownership_before)
    menus_after = ui_index.device_menus(after, ownership_after)
    return {
        "steps": [item["step"] for item in applied],
        "reports": applied,
        "validation": gspm.validate(after),
        "baseline_sha256": hashlib.sha256(before).hexdigest(),
        "artifact_sha256": hashlib.sha256(after).hexdigest(),
        "size": {"before": len(before), "after": len(after)},
        "changed_ranges": len(ranges),
        "changed_bytes": sum(end - start for start, end in ranges),
        "appended_bytes": max(0, len(after) - len(before)),
        "devices": {
            "before": ownership_before["counts"]["devices"],
            "after": ownership_after["counts"]["devices"],
        },
        "menu_rows": {
            "before": menus_before["counts"]["replica_rows"],
            "after": menus_after["counts"]["replica_rows"],
        },
        "menu_replicas": {
            "before": menus_before["counts"]["replica_menus"],
            "after": menus_after["counts"]["replica_menus"],
        },
        "rejected": {
            "before": dict(menus_before["rejected"]),
            "after": dict(menus_after["rejected"]),
        },
    }
