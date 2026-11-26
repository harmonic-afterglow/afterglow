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


def _many(label: str, count: int = 8) -> dict:
    """A device sending ``count`` NEC codes, as an import leaves it: no maker, no model."""
    device = _device(label)
    device["commands"] = [[f"Command {code:02X}", f"Command {code:02X}", "", "", None]
                          for code in range(count)]
    device["signals"] = {f"Command {code:02X}": ir_signal.waveform(_nec(code), carrier_hz=38001)
                         for code in range(count)}
    return device


def _sets(*models, count: int = 8) -> Archive:
    """One set of ``count`` codes for each list of ``(manufacturer, model)``."""
    commands = [{"Name": f"Key{code}", "pronto": _pronto(_nec(code))} for code in range(count)]
    return Archive({f"s{n}": commands for n in range(len(models))},
                   {f"s{n}": [{"id": n * 10 + m, "manufacturer": maker, "model": model,
                               "type": "Television"} for m, (maker, model) in enumerate(users)]
                    for n, users in enumerate(models)})


def test_only_a_device_naming_no_model_and_sending_enough_codes_is_looked_up():
    assert device_match.worth_looking_up(_many("Humax DVR"))
    # the testers' two-command IR relays "matched" an LG television
    assert not device_match.worth_looking_up(_many("IRTrans Power TV", 2))
    named = _many("Humax DVR")
    named["mfr"] = "Humax"
    assert not device_match.worth_looking_up(named)


def test_a_model_is_set_unasked_only_when_its_codes_and_its_name_point_at_it_alone():
    device = _many("Humax DVR")
    # the same model in two sets is still one model
    found = device_match.suggest(device, _sets([("Humax", "IR3000HD")],
                                               [("Humax", "IR3000HD")]), limit=5)
    assert device_match.confident(device, found)[1]["model"] == "IR3000HD"
    # many models send the same codes: someone picks
    found = device_match.suggest(device, _sets([("Humax", "A"), ("Humax", "B")]), limit=5)
    assert device_match.confident(device, found) is None
    assert [model["model"] for _s, model in device_match.candidates(found)] == ["A", "B"]
    # a name that names no maker, or another one, is no proof
    found = device_match.suggest(_many("Monitor"), _sets([("Panasonic", "TC-42")]), limit=5)
    assert device_match.confident(_many("Monitor"), found) is None
    found = device_match.suggest(_many("DuneHD"), _sets([("Strong", "LEAP")]), limit=5)
    assert device_match.confident(_many("DuneHD"), found) is None
    # too few of its codes in the set
    device = _many("Humax DVR", 12)
    found = device_match.suggest(device, _sets([("Humax", "IR3000HD")]), limit=5)
    assert found[0]["matched"] == 8 and device_match.confident(device, found) is None
    # one of ten is chance, not a model to offer
    device = _many("Climate Control", 10)
    found = device_match.suggest(device, _sets([("Daikin", "FTX")], count=4), limit=5)
    assert found and device_match.plausible(found) == []


def _no_waiting(monkeypatch, archive):
    from afterglow.gui import background, device_lookup
    monkeypatch.setattr(device_lookup, "_archive", lambda: archive)
    monkeypatch.setattr(background, "each",
                        lambda _parent, items, work, _message, **_kw: [work(i) for i in items])


def test_find_model_on_a_device_card_names_the_device_picked(qapp_or_skip, monkeypatch):
    from afterglow.gui import device_lookup, tabs
    from afterglow.qt.QtWidgets import QMessageBox

    _no_waiting(monkeypatch, ARCHIVE)
    shown = []

    def pick(review):
        shown.append([review.models.item(row).text() for row in range(review.models.count())])
        review.models.setCurrentRow(1)
        return True
    monkeypatch.setattr(device_lookup.MatchReview, "exec", pick)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_args: None))
    project = {"devices": [_device("Sony TV")], "activities": [],
               "settings": {"remote": "harmony-one"}}
    tab = tabs.DevicesTab(project, [])
    tab.find_model(0)
    device = project["devices"][0]
    assert shown[0][0] == "Leave as it is"
    assert (device["mfr"], device["model"]) == ("Sony", "KDL-40")
    assert "Netflix" in device["signals"]


def test_the_models_are_searched_by_maker_model_and_type(qapp_or_skip):
    from afterglow.gui import device_lookup

    device = _many("Monitor")
    archive = _sets([("Panasonic", "TC-42P1"), ("Panasonic", "TH-50"), ("Sony", "KDL-40")])
    review = device_lookup.MatchReview(
        [(device, device_match.suggest(device, archive, limit=5), None)])
    visible = lambda: [review.models.item(row).text().split(" - ")[0]
                       for row in range(review.models.count())
                       if not review.models.item(row).isHidden()]
    assert len(visible()) == 4 and review.count.text() == "3 models"
    review.search.setText("panasonic th")
    assert visible() == ["Leave as it is", "Panasonic TH-50"]
    assert review.count.text() == "1 of 3 models"
    review.models.setCurrentRow(2)
    assert review.chosen[0][1]["model"] == "TH-50"
    review.models.setCurrentRow(0)
    assert review.chosen[0] is None


def test_each_device_starts_with_its_own_models_unsearched(qapp_or_skip):
    from afterglow.gui import device_lookup

    archive = _sets([("Panasonic", "TC-42P1"), ("Sony", "KDL-40")])
    rows = [(device, device_match.suggest(device, archive, limit=5), None)
            for device in (_many("Monitor"), _many("TV"))]
    review = device_lookup.MatchReview(rows)
    assert not review.devices.isHidden() or len(rows) == 1
    review.search.setText("panasonic")
    review.devices.setCurrentRow(1)
    assert review.search.text() == ""
    assert review.count.text() == "2 models"


def test_an_import_asks_first_and_sets_a_sure_match_without_a_window(qapp_or_skip, monkeypatch):
    from afterglow.gui import device_lookup
    from afterglow.qt.QtWidgets import QMessageBox

    _no_waiting(monkeypatch, _sets([("Humax", "IR3000HD")]))
    asked, told = [], []
    answer = [QMessageBox.StandardButton.No]
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *args, **_kw: asked.append(args[2]) or answer[0]))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *args: told.append(args[2])))
    monkeypatch.setattr(device_lookup.MatchReview, "exec",
                        lambda _self: (_ for _ in ()).throw(AssertionError("no window")))
    project = {"devices": [_many("Humax DVR"), _many("IR relay", 2)], "activities": [],
               "settings": {"remote": "harmony-one"}}
    # declined: nothing is read, nothing changes
    assert not device_lookup.offer_after_import(None, project)
    assert "1 imported device(s)" in asked[0] and "IR relay" not in asked[0]
    assert not project["devices"][0].get("model")
    answer[0] = QMessageBox.StandardButton.Yes
    assert device_lookup.offer_after_import(None, project)
    assert (project["devices"][0]["mfr"], project["devices"][0]["model"]) == (
        "Humax", "IR3000HD")
    assert "Humax DVR: Humax IR3000HD" in told[-1]


def test_a_device_the_database_could_not_be_read_for_is_not_called_unknown(qapp_or_skip,
                                                                           monkeypatch):
    from afterglow.gui import device_lookup
    from afterglow.qt.QtWidgets import QMessageBox

    class Down:
        has_code_index = True

        def code_sets_sending(self, _key):
            raise OSError("no network")
    _no_waiting(monkeypatch, Down())
    told = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *args: told.append(args[2])))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *args: told.append(args[2])))
    project = {"devices": [_many("Humax DVR")], "activities": [],
               "settings": {"remote": "harmony-one"}}
    assert not device_lookup.look_up(None, project, [0], ask=False)
    assert "could not be read" in told[0] and "No model" not in told[0]


def test_a_model_that_names_its_maker_is_not_named_twice():
    from afterglow.gui import device_lookup
    assert device_lookup._model_name({"manufacturer": "Apple", "model": "Apple TV"}) == \
        "Apple TV"
    assert device_lookup._model_name({"manufacturer": "Humax", "model": "IR3000HD"}) == \
        "Humax IR3000HD"


def test_a_remote_that_keeps_its_devices_models_is_never_asked(qapp_or_skip, monkeypatch):
    from afterglow.gui import device_lookup
    from afterglow.qt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *_args, **_kw: (_ for _ in ()).throw(AssertionError("asked"))))
    for remote in ("harmony-900", "harmony-1100"):
        project = {"devices": [_many("Humax DVR")], "activities": [],
                   "settings": {"remote": remote}}
        assert not device_lookup.offer_after_import(None, project)


def _samsung36(address: int, command: int, wobble: float = 1.0) -> list[int]:
    """A Samsung36 frame: 4500/-4500, 16 bits, a 4500 us space between its halves."""
    out = [round(4500 * wobble), -4500]
    def bits(value, count):
        for bit in range(count):
            out.extend([round(500 * wobble), -1500 if value >> bit & 1 else -500])
    bits(address, 16)
    out.extend([500, -4500])
    bits(command, 20)
    return out + [500, -50000]


def test_a_frame_split_in_two_is_keyed_by_its_pairs_the_same_however_drawn():
    key = ir_recognise.fingerprint(_samsung36(0x0707, 0x2D))
    assert key and key.startswith("g18-")
    # a recording drawn a little longer is the same code; another command is not
    assert ir_recognise.fingerprint(_samsung36(0x0707, 0x2D, wobble=1.02)) == key
    assert ir_recognise.fingerprint(_samsung36(0x0707, 0x2E)) != key


def test_a_code_the_first_rules_read_keeps_the_key_an_older_index_has():
    # the archive's index built before pairs were keyed still answers these
    assert not ir_recognise.fingerprint(_nec(8)).startswith("g")
    assert ir_recognise.fingerprint([500, -500] * 3 + [500, -50000]) is None
