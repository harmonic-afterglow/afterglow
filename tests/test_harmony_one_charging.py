"""A generated Harmony One while it charges: the battery and the photos, in a ring.

Every donor does the same: when charging starts the remote wakes, and a moment later shows
a battery, then photographs one after another, round again; a key starts the ring over
from the battery, and when charging stops the remote goes back to what it was showing.
The interpreter here adds to the activities tests' what charging needs: timers, the mode
stack, and leaving a screen before entering the next.
"""
from __future__ import annotations

import json
import shutil

import pytest
from test_harmony_one_activities import PROJECT, _Remote

from afterglow import paths
from afterglow.backends.harmony_one import (
    charging, generate, gspm, idle, keys, scaffold, ui_index)

LEAVE = 0x07


class _Charging(_Remote):
    def __init__(self, image):
        super().__init__(image)
        self.running: set[int] = set()
        self.stack: list[int] = []

    def timer(self, index):
        at = int.from_bytes(self.image[gspm.section_ranges(self.image)[13][0] + 1 + 3 * index:
                                       gspm.section_ranges(self.image)[13][0] + 4 + 3 * index],
                            "little") - gspm.BASE
        return (int.from_bytes(self.image[at + 1:at + 4], "little"),
                (int.from_bytes(self.image[at + 4:at + 6], "little"), self.image[at + 6]))

    def fire(self, index):
        """Timer ``index`` runs out."""
        assert index in self.running, f"timer {index} is not running"
        self.running.discard(index)
        self.run(self.timer(index)[1])

    def run(self, *instructions):
        """One step at a time, so a test drops the next step whichever interpreter runs
        it; the rest is the activities' interpreter's."""
        skip = False
        for operand, opcode in instructions:
            if skip:
                skip = False
                continue
            high = operand >> 8
            if opcode in (0x70, 0x71):
                value = self.variables.get(operand & 0xFF, 0)
                held = [value == self.byte, value != self.byte, value < self.byte,
                        value > self.byte, value <= self.byte, value >= self.byte][high & 0xF]
                skip = held if high & 0x80 else not held
            elif opcode == 0x1F and high == idle.START_TIMER:
                self.running.add(operand & 0xFF)
            elif opcode == 0x1F and high == idle.STOP_TIMER:
                self.running.discard(operand & 0xFF)
            elif (operand, opcode) == (idle.STATUS, idle.MODE_STACK):
                self.running.clear()
            elif (operand, opcode) == (idle.PUSH_MODE, idle.MODE_STACK):
                self.stack.append(self.mode)
            elif (operand, opcode) == (idle.POP_MODE, idle.MODE_STACK):
                self.enter(self.stack.pop())
            elif opcode == 0x7F:
                self.run(*self.objects[operand]["atoms"])
            else:
                super().run((operand, opcode))

    def enter(self, ordinal):
        if self.mode is not None and LEAVE in self.header(self.mode):
            self.run(self.header(self.mode)[LEAVE])
        super().enter(ordinal)

    def event(self, code):
        found = self.row(scaffold.EVENT_CONTEXT, code)
        assert found, f"nothing answers event {code:#04x}"
        self.run(found)


def _pictures(image) -> list[int]:
    """The screens the image owns that are one whole-screen picture and nothing else."""
    out = []
    screens = ui_index.screen_slots(image)
    for ordinal in range(scaffold.SYSTEM_SCREENS, len(screens)):
        items = [item for slot in screens[ordinal]["slots"]
                 for item in ui_index.drawing_program(image, slot["program_offset"])[
                     "instructions"] if item["opcode"] not in ("end", "return")]
        if [(item["opcode"], item.get("x"), item.get("y")) for item in items] == [
                ("bitmap", 0, 0)]:
            out.append(ordinal)
    return out


@pytest.fixture(scope="module")
def built():
    return generate.build(PROJECT)["image"]


def _on_home(image):
    machine = _Charging(image)
    machine.enter(scaffold.SYSTEM_SCREENS)          # Activities, as start-up shows it
    return machine


def test_the_scaffold_s_charging_pictures_are_shown_battery_first():
    pictures = json.loads((paths.scaffolds("harmony-one") / "assets.json").read_text())[
        "pictures"]
    assert charging.roles(pictures) == ["charging/battery", "charging/photo-1",
                                        "charging/photo-2", "charging/photo-3"]


def test_each_charging_screen_is_its_picture_alone(built):
    assert len(_pictures(built)) == 4


def test_charging_shows_the_battery_a_moment_later_then_the_photos_round_again(built):
    machine = _on_home(built)
    ring = _pictures(built)
    machine.event(idle.CHARGING_STARTED)
    assert machine.mode == scaffold.SYSTEM_SCREENS        # woken, still on what was shown
    [show] = machine.running - {t for t in machine.running
                                if machine.timer(t)[0] != idle.SHOW_DELAY}
    machine.fire(show)
    assert machine.mode == ring[0]
    seen = [machine.mode]
    for _ in range(len(ring)):
        [frame] = machine.running
        machine.fire(frame)
        seen.append(machine.mode)
    assert seen == ring + ring[:1]


def test_a_key_on_the_cradle_starts_the_ring_again_from_the_battery(built):
    machine = _on_home(built)
    ring = _pictures(built)
    machine.event(idle.CHARGING_STARTED)
    machine.fire(next(t for t in machine.running if machine.timer(t)[0] == idle.SHOW_DELAY))
    [frame] = machine.running
    machine.fire(frame)
    assert machine.mode == ring[1]
    machine.press(keys.code(keys.SCANS["VolumeUp"]))
    assert machine.mode == ring[0]
    assert len(machine.running) == 1                      # just the battery's own timer


def test_charging_stopping_goes_back_to_what_was_shown(built):
    machine = _on_home(built)
    machine.event(idle.CHARGING_STARTED)
    machine.fire(next(t for t in machine.running if machine.timer(t)[0] == idle.SHOW_DELAY))
    machine.event(idle.CHARGING_STOPPED)
    assert machine.mode == scaffold.SYSTEM_SCREENS
    assert not machine.stack
    # and lifted before the ring opened, it never opens
    machine.event(idle.CHARGING_STARTED)
    machine.event(idle.CHARGING_STOPPED)
    assert all(machine.timer(t)[0] != idle.SHOW_DELAY for t in machine.running)
    assert machine.mode == scaffold.SYSTEM_SCREENS


def test_the_battery_rising_on_the_cradle_shows_what_was_shown_then_the_ring_again(built):
    machine = _on_home(built)
    ring = _pictures(built)
    machine.event(idle.CHARGING_STARTED)
    machine.fire(next(t for t in machine.running if machine.timer(t)[0] == idle.SHOW_DELAY))
    assert machine.mode == ring[0]
    machine.event(idle.BATTERY_UP)
    assert machine.mode == scaffold.SYSTEM_SCREENS and not machine.stack
    machine.fire(next(t for t in machine.running if machine.timer(t)[0] == idle.SHOW_DELAY))
    assert machine.mode == ring[0]


def test_a_charging_problem_shows_the_firmware_s_notice(built):
    machine = _on_home(built)
    machine.event(idle.CHARGING_PROBLEM)
    assert machine.mode == idle.SCREEN_NINE


def test_a_theme_without_a_battery_picture_shows_nothing_while_charging(tmp_path):
    theme = tmp_path / "theme"
    shutil.copytree(paths.scaffolds("harmony-one"), theme)
    manifest = json.loads((theme / "assets.json").read_text())
    manifest["pictures"] = {role: item for role, item in manifest["pictures"].items()
                            if not role.startswith("charging/")}
    (theme / "assets.json").write_text(json.dumps(manifest))
    image = generate.build(PROJECT, directory=theme)["image"]
    assert not _pictures(image)
    machine = _Charging(image)
    assert machine.row(scaffold.EVENT_CONTEXT, idle.CHARGING_STARTED) is None
