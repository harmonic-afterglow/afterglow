"""Every IR protocol IRDB, Flipper-IRDB and Logitech's archive use has a way to the
remote, or a reason it cannot have one.

The snapshots in fixtures/ir-sources list every protocol name each source used when they
were taken (tools/ir_source_snapshot.py refreshes them), with how many commands use it.
A device from IRDB once arrived with none of its commands because plain "NEC" was not a
name anything read; with these, a name a source starts using fails here when the
snapshot is refreshed, instead of on someone's remote.
"""
import json

import pytest

from afterglow import logitech_archive, paths
from afterglow.public_ir_sources import protocol_handling



def _snapshot(name):
    from pathlib import Path
    path = Path(__file__).parent / "fixtures" / "ir-sources" / f"{name}-protocols.json"
    return json.loads(path.read_text(encoding="utf-8"))["protocols"]


@pytest.mark.parametrize("source", ["irdb", "flipper"])
def test_every_protocol_a_public_source_names_is_handled(source):
    unhandled = {name: entry["commands"] for name, entry in _snapshot(source).items()
                 if protocol_handling(source, name) is None}
    assert not unhandled, f"{source} protocols with no definition or reason: {unhandled}"


@pytest.mark.parametrize("source", ["irdb", "flipper"])
def test_the_snapshot_says_how_each_name_is_handled_now(source):
    """The snapshot doubles as the list of what happens to each name; a change to the
    handling shows up as a change to it."""
    stale = {name: (entry["handling"], protocol_handling(source, name))
             for name, entry in _snapshot(source).items()
             if entry["handling"] != protocol_handling(source, name)}
    assert not stale, f"refresh with tools/ir_source_snapshot.py: {stale}"


def test_every_protocol_the_logitech_archive_uses_can_be_sent():
    unsendable = {key: entry["commands"] for key, entry in _snapshot("logitech").items()
                  if logitech_archive.protocol_handling(
                      entry["id"], entry["name"], commands=entry["commands"],
                      with_pronto=entry["with_pronto"]) is None}
    assert not unsendable, f"archive protocols no command of which can be sent: {unsendable}"


def test_the_logitech_snapshot_says_how_each_protocol_is_handled_now():
    stale = {}
    for key, entry in _snapshot("logitech").items():
        now = logitech_archive.protocol_handling(
            entry["id"], entry["name"], commands=entry["commands"],
            with_pronto=entry["with_pronto"])
        if entry["handling"] != now:
            stale[key] = (entry["handling"], now)
    assert not stale, f"refresh with tools/ir_source_snapshot.py: {stale}"


def test_the_snapshots_cover_what_was_measured():
    """Guards against an empty or truncated snapshot passing the tests above."""
    irdb, flipper, logitech = (_snapshot(name) for name in ("irdb", "flipper", "logitech"))
    assert sum(entry["commands"] for entry in irdb.values()) > 100_000
    assert sum(entry["commands"] for entry in flipper.values()) > 100_000
    assert len(logitech) > 600
    assert irdb["NEC"]["handling"] == "native"
    assert sum(e["sent"] for e in irdb.values()) / \
        sum(e["commands"] for e in irdb.values()) > 0.98
