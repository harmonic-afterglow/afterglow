"""Talking to the remote: the libconcord binding and the event channel.

None of this needs hardware. What is checked is the part that can be wrong without a
remote attached - the guards, the conversions, and the refusals - because the operation
they protect is the one that cannot be undone.
"""
import ctypes
from pathlib import Path

import pytest

from afterglow import concord, hao, ir_signal
from afterglow.backends.harmony_pk import ssir


# the binding
def test_the_web_calls_are_not_bound():
    """libconcord can still phone members.harmonyremote.com. That service is gone, and
    binding those calls could only ever hang a flash on a dead host."""
    remote = concord.Remote() if concord.available() else None
    if remote is None:
        pytest.skip("libconcord not installed")
    source = Path(concord.__file__).read_text()
    for call in ("post_preconfig", "post_postconfig", "post_connect_test_success",
                 "post_new_code", "post_postfirmware"):
        assert f'"{call}"' not in source, f"{call} must not be bound"


def test_callback_signature_matches_the_library():
    """void(uint32 x5, void*, const uint32*) - a mismatch here corrupts the stack
    during a flash, which is the worst possible moment."""
    LC = concord.LC_CALLBACK
    assert LC._restype_ is None
    assert LC._argtypes_ == (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_uint32))


def test_writing_refuses_a_config_for_another_remote(a_config):
    """The file says which remote it is for. Writing a Harmony 900 config to something
    else would invalidate that remote's flash before failing."""
    with pytest.raises(concord.RemoteError, match="Refusing to write"):
        concord.Remote._verify_intended_for(
            Path(a_config), {"skin": 54, "model": "Harmony One"})


def test_writing_accepts_a_config_for_this_remote(a_config):
    concord.Remote._verify_intended_for(Path(a_config), {"skin": 61,
                                                         "model": "Harmony 900"})


def test_writing_refuses_something_that_is_not_a_config(tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("this is not a configuration")
    with pytest.raises(concord.RemoteError, match="not a configuration"):
        concord.Remote._verify_intended_for(junk, {"skin": 61, "model": "Harmony 900"})


# learned codes
def test_a_learned_signal_becomes_a_capture():
    """libconcord returns unsigned alternating durations starting with a mark; a
    capture stores them signed, + for mark and - for space."""
    capture = concord.learned_capture(37944, [8934, 4563, 543, 576], "VolumeUp")
    assert capture["pulses_us"] == [8934, -4563, 543, -576]
    assert capture["carrier_hz"] == 37944
    assert capture["kind"] == "waveform"
    assert "native" not in capture


def test_a_learned_capture_becomes_a_carrier_period_for_ssir():
    """irgen consumes SsIr's u32 prefix as a period in nanoseconds."""
    capture = concord.learned_capture(38000, [500, 500], "X")
    assert int.from_bytes(ssir.capture_header(capture), "little") == round(1e9 / 38000)


def test_a_real_capture_keeps_its_own_header():
    """A capture read from a configuration is carried, never recomputed."""
    capture = ir_signal.waveform(
        [100, -100], native={"harmony-pk": {
            "ssir_carrier_period_ns": 32572, "status": "observed"}})
    assert ssir.capture_header(capture).hex() == "3c7f0000"


def test_a_capture_with_neither_is_refused():
    """Better to fail the build than invent a carrier."""
    with pytest.raises(ValueError, match="neither an observed.*nor a measured carrier_hz"):
        ssir.capture_header({"name": "mystery", "pulses_us": [100]})


def test_learned_codes_reach_the_build_spec():
    """A learned command points into the capture table with 0xFFFF<index>00; if the
    two halves disagree the command silently does nothing."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.device_wizard import _attach_learned
    from afterglow import backends, project_devices, remotes

    spec = {"schema": project_devices.SCHEMA, "id": "7", "label": "Test",
            "type": "Receiver", "mfr": "", "model": "",
            "commands": [["VolumeUp", "Vol +", "", "", None]], "signals": {}}
    learned = {"VolumeUp": concord.learned_capture(37944, [500, 500], "VolumeUp")}
    _attach_learned(spec, {}, learned)
    assert spec["signals"] == learned
    assert "raw_codes" not in spec and "raw_ir" not in spec
    lowered = backends.for_profile(remotes.get("harmony-900")).lower_devices(
        [spec], remotes.get("harmony-900"))[0]
    code = lowered["raw_codes"]["VolumeUp"]
    assert ssir.is_raw(code)
    assert str(ssir.raw_index(code)) in lowered["raw_ir"]
    entries, remap = ssir.collect([lowered])
    assert len(entries) == 1 and remap[("7", "VolumeUp")] == ssir.make_code(0)
    assert int.from_bytes(entries[0][:4], "little") == round(1e9 / 37944)


def test_learning_does_not_disturb_existing_captures():
    """Adding a learned key to a device that already has recorded ones must not
    renumber the others out from under their commands."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.device_wizard import _attach_learned
    old = ir_signal.waveform(
        [100, -100], native={"harmony-pk": {
            "ssir_prefix_hex": "3c7f0000", "status": "observed"}})
    existing = {"signals": {"Old": old}}
    spec = {"id": "7", "commands": [], "signals": {"Old": old}}
    new = concord.learned_capture(38000, [500, 500], "New")
    _attach_learned(spec, existing,
                    {"New": new})
    assert spec["signals"] == {"Old": old, "New": new}
    assert "raw_codes" not in spec and "raw_ir" not in spec


# the event channel
def test_the_pairing_message_is_what_the_remote_itself_sends():
    """Taken from the remote's own app-main.swf (AddReceiver.as). If this drifts, the
    remote ignores it and pairing silently never starts."""
    assert hao.ADD_RECEIVER == ("<Event><Payload><Name>RF:AddReceiver</Name>"
                                "<Params></Params></Payload></Event>")
    assert hao.READY == "<Event><Payload><Name>RF:ReadyForRF</Name></Payload></Event>"


def test_destructive_rf_messages_are_documented_but_unused():
    """ResetNetwork forgets every pairing. Nothing should send it by accident."""
    source = Path(hao.__file__).read_text()
    for name in hao.DESTRUCTIVE:
        assert f'"{name}"' not in source.split("DESTRUCTIVE")[1].split("}")[1], (
            f"{name} is sent somewhere in hao.py")


def test_event_names_are_parsed():
    assert hao.event_name("<Event><Payload><Name>NewReceiversFound</Name>"
                          "</Payload></Event>") == "NewReceiversFound"
    assert hao.event_name("nonsense") == "?"


def test_unreachable_remote_gives_the_same_advice_as_every_other_link_failure():
    """A remote that stops answering has one likely cause and one fix, whichever layer
    noticed. Naming the Linux helper script is only correct for a link that was never
    brought up, and reads as nonsense when the connection dropped mid-operation; the
    Linux note stays, but not as the headline and not on Windows.
    """
    import sys as _sys

    with pytest.raises(hao.NotReachable) as caught:
        hao.Channel(host="127.0.0.1", port=1, timeout=0.2)
    message = str(caught.value)
    assert concord.NOT_CONNECTED_ADVICE in message
    assert message.index("127.0.0.1:1") < message.index(concord.NOT_CONNECTED_ADVICE)
    assert ("Set up the USB link" in message) is _sys.platform.startswith("linux")
    assert "harmony_net" not in message, "do not tell them to run what we already ran"


# where the controls live
def test_pairing_is_not_behind_a_device(qapp_or_skip):
    """A blaster is paired with the REMOTE. Putting the button on a device's Edit page
    meant you could not add your first blaster until you had invented a device."""
    from afterglow.gui.device_wizard import IdentityPage
    from afterglow.gui.tabs import SettingsTab
    settings = SettingsTab({"settings": {}})
    assert hasattr(settings, "add_blaster_btn"), "Remote Settings has no pairing button"
    page = IdentityPage({"id": "1"}, project={"devices": [], "settings": {}})
    assert hasattr(page, "rf_combo"), "the per-device output picker should stay"
    assert not hasattr(page, "add_blaster_btn"), "pairing must not be on a device page"


def test_learning_is_offered_where_the_device_is_looked_up(qapp_or_skip):
    """Learning is what you do when the library has nothing for your hardware, so it
    belongs among the ways of identifying a device - not behind a device that does not
    exist yet, and not as a separate button elsewhere."""
    from afterglow.gui.device_wizard import SearchPage
    page = SearchPage([], {})
    options = [page.search_type.itemData(i) for i in range(page.search_type.count())]
    assert "learn" in options, "no way to say the device is not in the library"


def test_choosing_to_learn_hides_the_search_boxes(qapp_or_skip):
    """Searching a database that cannot contain the device is noise; and switching
    back must restore what was there."""
    from afterglow.gui.device_wizard import SearchPage
    page = SearchPage([], {})
    learn = [page.search_type.itemData(i)
             for i in range(page.search_type.count())].index("learn")
    page.search_type.setCurrentIndex(learn)
    assert not page._mfr_box.isVisibleTo(page)
    assert page._learn_note.isVisibleTo(page)
    page.search_type.setCurrentIndex(0)
    assert page._mfr_box.isVisibleTo(page)
    assert not page._learn_note.isVisibleTo(page)


# a device that exists only because it was learned
def test_a_purely_learned_device_builds_from_its_measured_carriers(tmp_path, qapp_or_skip):
    """No library entry, no protocol block - every command a recorded waveform.

    This is what you get when your hardware is not in the database, which is the whole
    reason learning exists. It used to fail outright: the builder rejected
    `protocol: None`, and the only reason the existing raw-only test passed was that a
    *missing* key silently defaulted to NEC.
    """
    import io
    import zipfile
    from conftest import ROOT
    from afterglow.build_service import ConfigBuildService
    from afterglow.gui.device_wizard import _attach_learned

    spec = {"id": "40009001", "label": "Yamaha RAV16", "type": "Receiver",
            "codec": "donor", "protocol": None, "power_cmd": "PowerToggle",
            "commands": [["VolumeUp", "Vol +", "", "", None],
                         ["PowerToggle", "Power", "", "", None]], "inputs": []}
    _attach_learned(spec, {}, {
        "VolumeUp": concord.learned_capture(37944, [8934, 4563, 543, 576], "VolumeUp"),
        "PowerToggle": concord.learned_capture(37944, [8934, 4563, 543, 1695], "Power")})

    out = tmp_path / "learned.ezhex"
    project = {"devices": [spec], "activities": [], "assets": [],
               "settings": {"remote": "harmony-900", "out_file": str(out),
                            "first_name": "T", "last_name": "U"}}
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _m: None).build(project)

    with zipfile.ZipFile(out) as archive:
        entries = ssir.parse(archive.read("userconfig/SsIr.bin"))
    assert len(entries) == 2
    assert {int.from_bytes(entry[:4], "little") for entry in entries} == {
        round(1e9 / 37944)}


def test_the_gui_learning_button_reaches_the_corrected_ssir_encoder(
        tmp_path, qapp_or_skip, monkeypatch):
    """Exercise the user-facing click, not only the helpers behind it.

    Hardware supplies the same `(carrier, durations)` object represented by this stub.
    The test clicks Learn, collects the resulting device, builds it, and inspects the
    actual SsIr entry. This catches a GUI that displays success but drops the capture
    before the corrected encoder sees it.
    """
    import contextlib
    import io
    import zipfile

    from PyQt6.QtWidgets import QInputDialog, QMessageBox
    from conftest import ROOT
    from afterglow.build_service import ConfigBuildService
    from afterglow.gui import remote_ops
    from afterglow.gui.device_wizard import CommandsPage, _attach_learned

    capture = concord.learned_capture(
        37944, [8934, 4563, 543, 576], "VolumeUp")
    # The Learn button is disabled when the library is absent, so without this the test
    # silently checks nothing on any machine that has no libconcord - it passed only
    # where one happened to be installed, and reported an empty capture dict in CI. The
    # question here is whether the click reaches the encoder, not whether the hardware
    # library is present; `run_with_progress` below is already stubbed for that reason.
    monkeypatch.setattr(concord, "available", lambda: True)
    monkeypatch.setattr(QInputDialog, "getText",
                        lambda *_args, **_kwargs: ("VolumeUp", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        remote_ops, "run_with_progress",
        lambda *_args, **_kwargs: (True, "Learned", capture),
    )

    page = CommandsPage({})
    page.learn_btn.click()
    assert page.learned_captures() == {"VolumeUp": capture}
    assert page.get_commands()[0][0] == "VolumeUp"

    spec = {
        "id": "40009001",
        "label": "GUI learned device",
        "type": "Receiver",
        "codec": "donor",
        "protocol": None,
        "commands": page.get_commands(),
        "inputs": [],
    }
    _attach_learned(spec, {}, page.learned_captures())
    out = tmp_path / "gui-learned.ezhex"
    project = {
        "devices": [spec],
        "activities": [],
        "assets": [],
        "settings": {
            "remote": "harmony-900",
            "out_file": str(out),
            "first_name": "T",
            "last_name": "U",
        },
    }
    with contextlib.redirect_stdout(io.StringIO()):
        ConfigBuildService(ROOT, lambda _message: None).build(project)

    with zipfile.ZipFile(out) as archive:
        entries = ssir.parse(archive.read("userconfig/SsIr.bin"))
    assert len(entries) == 1
    assert int.from_bytes(entries[0][:4], "little") == round(1e9 / 37944)
    assert ssir.decode_capture(entries[0])["pulses_us"] == capture["pulses_us"]


def test_a_device_with_no_protocol_is_not_called_nec(qapp_or_skip):
    """`None` meant "not set". Folding it in with legacy index 0 labelled every
    learned or half-filled device NEC - the same wrong-timing trap the builder
    refuses elsewhere."""
    from afterglow.gui.device_wizard import IdentityPage
    page = IdentityPage({})
    assert "NEC" not in page.proto_label.text()
    learned = IdentityPage({"signals": {
        "Vol": ir_signal.waveform([500, -500], carrier_hz=38000)}})
    assert "recorded waveform" in learned.proto_label.text()
    semantic = IdentityPage({"signals": {
        "Vol": ir_signal.protocol_signal("nec1", {"address": 1, "command": 2})}})
    assert "nec1" in semantic.proto_label.text()


# the interface must not block
def test_remote_operations_run_off_the_main_thread():
    """Learning waits five seconds for a keypress and pairing the better part of a
    minute. Doing either on the main thread greys the window out and the desktop
    offers to kill it."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui import remote_ops
    assert hasattr(remote_ops, "run_with_progress")
    gui = Path(remote_ops.__file__).parent
    # Learning is a single blocking call, so it goes on a worker thread. The blaster
    # window is a minute of waiting with a visible clock, so it is timer-driven. Both
    # are fine; hand-pumping the event loop is not.
    assert "run_with_progress" in (gui / "device_wizard.py").read_text()
    assert "QTimer" in (gui / "blaster_scan.py").read_text()
    for module in ("device_wizard", "rf_routing", "blaster_scan"):
        source = (gui / f"{module}.py").read_text()
        assert "processEvents" not in source, (
            f"{module} pumps events by hand instead of using a worker or a timer")


def test_reading_the_remote_writes_a_real_ezhex():
    """`read_config_from_remote` hands back the binary blob only; the envelope comes
    from `write_config_to_file`. Saving the blob produced a file nothing could read -
    including the step immediately after it, which crashed the application."""
    source = Path(concord.__file__).read_text()
    assert "write_config_to_file" in source
    save = source.split("def save_config")[1].split("def ")[0]
    assert "write_config_to_file" in save, "save_config must build the envelope"
    assert "write_bytes" not in save, "the raw blob must not be written as a file"


def test_a_missed_post_flash_reconnect_is_not_reported_as_a_failed_write():
    """A reset always makes the remote disappear; Linux can miss its re-enumeration.

    `update_configuration` has already completed at that point, so losing the USB link
    must not turn a successful write into an exception that invites the user to flash
    again. libconcord deinitialises itself on this error, so the context manager must
    also not try to close an already-closed connection.
    """
    class Library:
        def __init__(self):
            self.deinit_calls = 0

        def reset_remote(self, _callback, _context):
            return 7

        def lc_strerror(self, error):
            assert error == 7
            return b"Error connecting or finding the remote"

        def deinit_concord(self):
            self.deinit_calls += 1

    remote = object.__new__(concord.Remote)
    remote.lib = Library()
    remote._open = True
    remote.last_restart_error = None
    remote._callback = lambda _progress: None

    assert remote.restart() is False
    assert remote.last_restart_error == "Error connecting or finding the remote"
    assert remote._open is False
    remote.__exit__()
    assert remote.lib.deinit_calls == 0


def test_failing_to_connect_says_what_to_do_about_it():
    """libconcord's own message reads as "this remote is not supported".

    The usual cause is the opposite: a supported remote that has not finished enumerating
    yet, which resolves itself in seconds. Keep the library's text - it is the real error
    - and add the part a user can act on, including the point at which waiting longer has
    stopped being the answer.
    """
    class Library:
        def init_concord(self):
            return 7

        def lc_strerror(self, error):
            assert error == 7
            return b"Error connecting or finding the remote"

    remote = object.__new__(concord.Remote)
    remote.lib = Library()
    remote._open = False

    with pytest.raises(concord.RemoteError) as caught:
        remote.__enter__()
    message = str(caught.value)
    assert "Error connecting or finding the remote" in message
    assert "20 seconds" in message
    assert "plug it back in" in message
    # A failed connect must not leave the object believing it holds one, or `__exit__`
    # will deinitialise a link that was never established.
    assert remote._open is False


def test_a_missed_reboot_is_reported_as_written_and_not_as_a_linux_chore(qapp_or_skip,
                                                                        monkeypatch):
    """The reboot is the last step of a flash and the one that looks most like a failure.

    Two things must hold in that message. It has to open by saying the configuration was
    written - the remote has no vendor recovery, and someone who reads this as a failed
    flash will flash again. And it has to give the same advice as every other connection
    message: the old text said "which is normal on Linux, re-run linux/harmony_net.sh",
    which a Windows user cannot act on at all.
    """
    import sys as _sys

    from afterglow.gui import remote_ops

    class Remote:
        last_restart_error = "Error connecting or finding the remote"

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def identity(self, *_a):
            return {"model": "Harmony 900"}

        def write_config(self, *_a):
            return None

    monkeypatch.setattr(remote_ops.concord, "Remote", Remote)
    worker = remote_ops.RemoteWorker("write", None, path="whatever.ezhex")
    said = {}
    worker.done.connect(lambda ok, text: said.update(ok=ok, text=text))
    worker.run()                       # in this thread; `start()` would need an event loop

    assert said["ok"] is True, "a missed reboot is not a failed write"
    assert said["text"].startswith("The configuration was written")
    assert "20 seconds" in said["text"] and "plug it back in" in said["text"]
    assert ("Set up the USB link" in said["text"]) is _sys.platform.startswith("linux")
    assert "harmony_net" not in said["text"]


def test_the_log_reports_outcomes_in_words_and_keeps_the_advice_readable(qapp_or_skip):
    """Two things about one line, both of which have to hold on the user's screen.

    The outcome is a word, not a tick: the glyphs are a coin flip across fonts, and a
    screen reader announces nothing useful for either. And `QTextEdit.append` chooses
    between rich and plain text by sniffing its argument, so a message carrying newlines
    - the connection advice does - could arrive with them collapsed into one run-on
    paragraph. Assert against the rendered document rather than the string passed in.
    """
    from PyQt6.QtWidgets import QTextEdit

    log = QTextEdit()
    log.setReadOnly(True)
    failure = ("connecting to the remote: Error connecting or finding the remote\n\n"
               "If the remote is plugged in, it has most likely not finished "
               "connecting yet.")
    log.append("\nSUCCESS: " + "Connected to Harmony 900.")
    log.append("\nFAILED: " + failure)

    lines = log.toPlainText().splitlines()
    assert "SUCCESS: Connected to Harmony 900." in lines
    assert "FAILED: connecting to the remote: Error connecting or finding the remote" \
        in lines
    assert any(line.startswith("If the remote is plugged in") for line in lines)


# knowing when the remote has actually saved something
def test_rf_settings_are_parsed_from_a_string_not_only_a_directory():
    """The same file arrives two ways: inside a configuration dump, and live over HTTP
    from the remote. One parser, so the live path cannot drift from the stored one."""
    from afterglow import rf
    xml = """<RemoteInfo><Controllers>
      <Controller><Guid>0</Guid><Label>0</Label></Controller>
      <Controller><Guid>00:04:20:e0:00:00:00:01</Guid><Label>1</Label>
        <Firmware>3.4</Firmware></Controller>
      </Controllers><Controller2UserDeviceMap>
      <Controller guid="00:04:20:e0:00:00:00:01">
        <Device><UserDeviceId>7</UserDeviceId><PortNumber>1</PortNumber></Device>
      </Controller></Controller2UserDeviceMap></RemoteInfo>"""
    parsed = rf.parse_rf_xml(xml)
    assert parsed["receivers"] == [{"mac": "00:04:20:e0:00:00:00:01", "label": 1,
                                    "firmware": "3.4"}]
    assert parsed["assign"] == {"7": "1-A"}


def test_pairing_waits_for_the_address_to_be_saved():
    """`rfsExportDbAsXML` ends in a fire-and-forget POST, and nothing acknowledges it
    on the event channel - so "a receiver joined" and "the settings say so" are two
    different moments. Reading immediately can read the old file."""
    assert hasattr(hao, "wait_for_new_receiver")
    source = Path(hao.__file__).read_text()
    body = source.split("def wait_for_new_receiver")[1].split("\ndef ")[0]
    assert "deadline" in body and "before" in body, "it must poll, not read once"

    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui import remote_ops
    pair = Path(remote_ops.__file__).read_text().split("def _pair")[1].split("\n    def ")[0]
    assert "wait_for_new_receiver" in pair, "pairing must wait for the saved address"


def test_a_receiver_already_known_is_not_reported_as_new():
    """Only a MAC that was not there before is a new blaster; re-running pairing with
    nothing joining must not claim success."""
    before = {"00:04:20:e0:00:07:a8:45"}
    current = [{"mac": "00:04:20:e0:00:07:a8:45", "label": 1}]
    assert [r for r in current if r["mac"] not in before] == []


# finding blasters
def _stub_remote(monkeypatch, receivers):
    """A dialog driven against a fake remote, so the logic is testable without a radio."""
    from afterglow.gui import blaster_scan
    state = {"receivers": list(receivers), "reset": 0, "started": 0}
    monkeypatch.setattr(blaster_scan.hao, "receivers_now",
                        lambda *a, **k: list(state["receivers"]))
    monkeypatch.setattr(blaster_scan.hao, "probe",
                        lambda *a, **k: {blaster_scan.hao.HAO_PORT: True})
    monkeypatch.setattr(blaster_scan.hao, "start_pairing",
                        lambda *a, **k: state.update(started=state["started"] + 1))
    monkeypatch.setattr(blaster_scan.hao, "reset_network",
                        lambda *a, **k: state.update(reset=state["reset"] + 1))
    return state


def test_a_blaster_already_in_the_project_cannot_be_added_twice(qapp_or_skip,
                                                                monkeypatch):
    """It is still shown - an empty list would look like a failure when the blaster is
    simply already set up - but it is not selectable."""
    from PyQt6.QtCore import Qt
    from afterglow.gui.blaster_scan import BlasterScanDialog
    _stub_remote(monkeypatch, [{"mac": "AA:AA", "label": 1}])
    dialog = BlasterScanDialog({"AA:AA"})
    item = dialog._list.item(0)
    assert "already in this project" in item.text()
    assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
    dialog._accept()
    assert dialog.chosen == []


def test_only_the_newly_found_blasters_are_returned(qapp_or_skip, monkeypatch):
    from afterglow.gui.blaster_scan import BlasterScanDialog
    state = _stub_remote(monkeypatch, [{"mac": "AA:AA", "label": 1}])
    dialog = BlasterScanDialog({"AA:AA"})
    dialog._window = dialog._left = 2
    dialog.start()
    state["receivers"].append({"mac": "BB:BB", "label": 2})
    dialog._tick()
    dialog.finish()
    dialog._accept()
    assert [r["mac"] for r in dialog.chosen] == ["BB:BB"]


def test_the_window_counts_down_and_can_be_cut_short(qapp_or_skip, monkeypatch):
    """A minute is a long time to stare at a spinner, so it shows what is left and
    stops on request."""
    from afterglow.gui.blaster_scan import BlasterScanDialog
    _stub_remote(monkeypatch, [])
    dialog = BlasterScanDialog(set())
    dialog._window = dialog._left = 60
    dialog.start()
    assert "60s left" in dialog._clock.text()
    dialog._tick()
    assert "59s left" in dialog._clock.text()
    assert dialog._stop.isEnabled()
    dialog.finish()
    assert not dialog._stop.isEnabled()
    assert "Finished" in dialog._clock.text()


def test_scanning_never_erases_the_pairing_table(qapp_or_skip, monkeypatch):
    """Erasing unpairs every blaster and cannot be undone from a backup - the radio
    association is not in the configuration. Reachability makes it unnecessary."""
    from afterglow.gui.blaster_scan import BlasterScanDialog
    state = _stub_remote(monkeypatch, [])
    dialog = BlasterScanDialog(set())
    dialog._window = dialog._left = 1
    dialog.start()
    assert state["reset"] == 0, "a scan must not erase anything"
    assert state["started"] == 1


def test_a_blaster_paired_long_ago_still_counts_as_found(qapp_or_skip, monkeypatch):
    """The point of the reachability flag: a blaster the remote knows does not announce
    itself as *new*, but it is still out there and should be addable without erasing
    anything first."""
    from afterglow.gui.blaster_scan import BlasterScanDialog
    _stub_remote(monkeypatch, [{"mac": "BB", "label": 2, "status": 1}])
    dialog = BlasterScanDialog(set())              # not in the project yet
    dialog._window = dialog._left = 1
    dialog.start()
    dialog.finish()
    dialog._accept()
    assert [r["mac"] for r in dialog.chosen] == ["BB"]


def test_a_known_but_silent_blaster_is_not_offered(qapp_or_skip, monkeypatch):
    """ControllerStatus 0 means the remote's link to it is down. Adding it would route
    devices to something unreachable."""
    from PyQt6.QtCore import Qt
    from afterglow.gui.blaster_scan import BlasterScanDialog
    _stub_remote(monkeypatch, [{"mac": "CC", "label": 3, "status": 0}])
    dialog = BlasterScanDialog(set())
    dialog._window = dialog._left = 1
    dialog.start()
    dialog.finish()
    item = dialog._list.item(0)
    assert "not responding" in item.text()
    assert not item.flags() & Qt.ItemFlag.ItemIsEnabled
    dialog._accept()
    assert dialog.chosen == []


def test_a_receiver_with_no_status_is_assumed_present():
    """The flag is a positive signal and an older configuration may predate it;
    treating its absence as "gone" would hide working hardware."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.blaster_scan import responding
    assert responding({"mac": "AA"}) is True
    assert responding({"mac": "AA", "status": 1}) is True
    assert responding({"mac": "AA", "status": 0}) is False


def test_nothing_found_explains_why(qapp_or_skip, monkeypatch):
    """An empty result has to say why or it reads as a broken feature."""
    from afterglow.gui.blaster_scan import BlasterScanDialog
    _stub_remote(monkeypatch, [{"mac": "AA:AA", "label": 1, "status": 1}])
    dialog = BlasterScanDialog({"AA:AA"})
    dialog._window = dialog._left = 1
    dialog.start()
    dialog.finish()
    assert "already in this project" in dialog._clock.text()


def test_routing_survives_a_reset_even_if_the_numbers_change(qapp_or_skip):
    """Labels are slots, not identities: `rfsGetAvailableLabel` hands out the first
    free number 1-5, so a blaster re-paired after a reset can come back as a different
    one. Carrying the tokens across unchanged would point devices at whichever base
    took that slot."""
    from afterglow.gui.rf_routing import assignments_by_mac, assignments_for
    before = [{"mac": "AA", "label": 1}, {"mac": "BB", "label": 2}]
    anchored = assignments_by_mac(before, {"7": "1-A", "8": "2", "9": "1"})
    assert anchored == {"7": ("AA", "A"), "8": ("BB", ""), "9": ("AA", "")}

    after = [{"mac": "BB", "label": 1}, {"mac": "AA", "label": 2}]   # swapped
    restored, orphaned = assignments_for(anchored, after)
    assert restored == {"7": "2-A", "8": "1", "9": "2"}, "routing followed the wrong base"
    assert orphaned == []


def test_a_device_whose_blaster_never_returned_is_reported():
    """Silently leaving it pointing at a base that no longer exists is the failure
    that looks like broken hardware."""
    pytest.importorskip("PyQt6.QtWidgets")
    from afterglow.gui.rf_routing import assignments_by_mac, assignments_for
    anchored = assignments_by_mac([{"mac": "AA", "label": 1}, {"mac": "BB", "label": 2}],
                                  {"7": "1-A", "8": "2"})
    restored, orphaned = assignments_for(anchored, [{"mac": "AA", "label": 1}])
    assert restored == {"7": "1-A"}
    assert orphaned == ["8"]


def test_an_existing_blaster_is_not_announced_as_new_before_any_scan(qapp_or_skip,
                                                                     monkeypatch):
    """Opening the dialog draws the list once, before anything has been listened for.

    The "was it here before?" set was only filled in when a scan started, so on that
    first draw it was empty and every blaster fell through to the newly-paired branch -
    a base paired weeks ago was announced as new just for opening the window.
    """
    from afterglow.gui.blaster_scan import BlasterScanDialog
    _stub_remote(monkeypatch, [{"mac": "AA", "label": 1, "status": 1}])
    dialog = BlasterScanDialog(set())          # not in the project yet
    assert "newly paired" not in dialog._list.item(0).text()
    assert "already paired, responding" in dialog._list.item(0).text()


def test_a_blaster_that_joins_during_the_window_is_marked_new(qapp_or_skip,
                                                              monkeypatch):
    """The other half of the same distinction: after a scan has run, something that
    was not there at the start really is new."""
    from afterglow.gui.blaster_scan import BlasterScanDialog
    state = _stub_remote(monkeypatch, [{"mac": "AA", "label": 1, "status": 1}])
    dialog = BlasterScanDialog(set())
    dialog._window = dialog._left = 2
    dialog.start()
    state["receivers"].append({"mac": "BB", "label": 2, "status": 1})
    dialog._tick()
    labels = [dialog._list.item(i).text() for i in range(dialog._list.count())]
    assert any("BB" in t and "newly paired" in t for t in labels), labels
    assert any("AA" in t and "already paired" in t for t in labels), labels


def test_the_dialog_opens_even_if_the_remote_is_unreachable(qapp_or_skip, monkeypatch):
    """The window is where the user finds out the remote is asleep; it cannot itself
    fail to open because of it."""
    from afterglow.gui import blaster_scan
    monkeypatch.setattr(blaster_scan.hao, "receivers_now",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))
    dialog = blaster_scan.BlasterScanDialog(set())
    assert dialog._list.count() == 0


# --- learning a code off another remote --------------------------------------------
def test_a_zero_length_space_is_merged_rather_than_refused():
    """libconcord reports a real space of 0 microseconds; that is not corruption.

    Its odd-word branch computes `t - t_on`, which is zero whenever two bursts run
    together with no measurable gap. A zero-length element cannot be transmitted and has
    no meaning alone - two marks separated by a zero space *are* one longer mark - so the
    entry is dropped and its neighbours summed. Refusing the capture threw
    "waveform pulses_us must contain non-zero integers" at the user instead.
    """
    from afterglow.concord import merge_zero_durations

    # A zero space between two marks: they become one.
    assert merge_zero_durations([9000, 0, 560, 1690]) == [9560, -1690]
    # Removing an entry flips the parity of everything after it, so polarity cannot be
    # read back off the index - the trailing mark must stay a mark.
    assert merge_zero_durations([9000, 4500, 560, 0, 560, 1690]) == \
        [9000, -4500, 1120, -1690]
    # A waveform starts with a mark.
    assert merge_zero_durations([0, 4500, 560, 1690]) == [560, -1690]
    # A clean signal is untouched.
    assert merge_zero_durations([9000, 4500, 560, 1690]) == [9000, -4500, 560, -1690]
    # Nothing usable is empty, not an exception here.
    assert merge_zero_durations([0, 0, 0]) == []


def test_a_capture_with_nothing_usable_is_reported_as_a_failed_reading(qapp_or_skip,
                                                                      monkeypatch):
    """A bad reading is not a fault, and must not surface as a validator's message.

    "ValueError: waveform pulses_us must contain non-zero integers" is accurate and
    useless to somebody holding two remotes; the answer they need is to try again.
    """
    from afterglow.gui import remote_ops

    class Remote:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def set_learning_mode(self, *_a):
            return True

        def learn(self, *_a):
            return 37944, [0, 0, 0]

    monkeypatch.setattr(remote_ops.concord, "Remote", Remote)
    worker = remote_ops.RemoteWorker("learn", None, name="VolumeUp")
    said = {}
    worker.done.connect(lambda ok, text: said.update(ok=ok, text=text))
    worker.run()

    assert said["ok"] is False
    assert "ValueError" not in said["text"], "do not show the validator's message"
    assert "not usable" in said["text"] and "closer" in said["text"]


def test_a_learned_capture_survives_a_zero_space_end_to_end():
    """The whole path: libconcord's durations in, a valid portable waveform out."""
    from afterglow import concord

    capture = concord.learned_capture(37944, [9000, 0, 560, 1690, 560], "VolumeUp")
    assert capture["pulses_us"] == [9560, -1690, 560]
    assert capture["carrier_hz"] == 37944
