"""Suggesting which archive model a device is, from its codes and its name."""
from __future__ import annotations

from afterglow import device_match, ir_protocol, ir_recognise, ir_signal, project_devices


def _pronto(pulses: list[int], carrier: int = 38000) -> str:
    unit = 1_000_000 / carrier
    words = [round(abs(pulse) / unit) for pulse in pulses]
    return " ".join(f"{word:04X}" for word in [0, round(unit / 0.241246), len(words) // 2, 0]
                    + words)


def _nec(command: int) -> list[int]:
    return ir_protocol.transmission(ir_protocol.catalog()["nec1"],
                                    {"address": 4, "command": command}, "press")[0]


class Archive:
    """The archive's API, as much of it as a suggestion reads."""
    has_code_index = True

    def __init__(self, sets: dict, users: dict):
        self.sets, self.users = sets, users

    def code_sets_sending(self, key):
        return [(codeset, command["Name"]) for codeset, commands in self.sets.items()
                for command in commands
                if ir_recognise.fingerprint(device_match._pronto(command["pronto"])) == key]

    def code_set_users(self, codeset):
        return [dict(user) for user in self.users[codeset]]

    def code_set(self, codeset):
        return self.sets[codeset]


ARCHIVE = Archive(
    {"aaa": [{"Name": "PowerToggle", "pronto": _pronto(_nec(8))},
             {"Name": "VolumeUp", "pronto": _pronto(_nec(2))}],
     "bbb": [{"Name": "PowerToggle", "pronto": _pronto(_nec(8))},
             {"Name": "Netflix", "pronto": _pronto(_nec(2))}]},
    {"aaa": [{"id": 1, "manufacturer": "Acme", "model": "B-200", "type": "Television"}],
     "bbb": [{"id": 2, "manufacturer": "Sony", "model": "KDL-40", "type": "Television"}]})


def _device(label: str) -> dict:
    return {"schema": project_devices.SCHEMA, "id": "harmony-one-0", "label": label,
            "type": "Television", "manufacturer": "", "model": "",
            "commands": [["PowerToggle", "PowerToggle", "", "", None],
                         ["Command 1F", "Command 1F", "", "", None]],
            "signals": {"PowerToggle": ir_signal.waveform(_nec(8), carrier_hz=38001),
                        "Command 1F": ir_signal.waveform(_nec(2), carrier_hz=38001)}}


def test_the_sets_that_send_a_device_s_codes_are_suggested_its_name_breaking_ties():
    found = device_match.suggest(_device("Sony TV"), ARCHIVE)
    assert [item["codeset"] for item in found] == ["bbb", "aaa"]
    assert found[0]["matched"] == found[0]["keyed"] == 2
    assert found[0]["models"][0]["model"] == "KDL-40"
    assert device_match.suggest(_device("Acme"), ARCHIVE)[0]["codeset"] == "aaa"


def test_choosing_a_model_names_the_device_and_the_commands_it_could_not():
    device = _device("Sony TV")
    activity = {"id": "7", "label": "Watch", "enter": [["command", "harmony-one-0", "Command 1F"]]}
    [best, _other] = device_match.suggest(device, ARCHIVE)
    renames = device_match.apply(device, best, best["models"][0], [activity])
    assert renames == {"Command 1F": "Netflix"}
    assert (device["manufacturer"], device["model"]) == ("Sony", "KDL-40")
    assert set(device["signals"]) == {"PowerToggle", "Netflix"}
    assert activity["enter"] == [["command", "harmony-one-0", "Netflix"]]


def test_an_archive_without_a_code_index_suggests_nothing():
    class Old:
        has_code_index = False
    assert device_match.suggest(_device("Sony TV"), Old()) == []


def test_find_model_on_a_device_card_names_the_device_picked(qapp_or_skip, monkeypatch):
    from afterglow import harmony_archive
    from afterglow.gui import background, tabs
    from afterglow.qt.QtWidgets import QInputDialog, QMessageBox

    monkeypatch.setattr(harmony_archive, "ApiArchive", lambda *_args: ARCHIVE)
    monkeypatch.setattr(background, "call", lambda _parent, _message, work: work())
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda _p, _t, _l, items, *_rest: (items[0], True)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_args: None))
    project = {"devices": [_device("Sony TV")], "activities": [],
               "settings": {"remote": "harmony-one"}}
    tab = tabs.DevicesTab(project, [])
    tab.find_model(0)
    device = project["devices"][0]
    assert (device["mfr"], device["model"]) == ("Sony", "KDL-40")
    assert "Netflix" in device["signals"]
