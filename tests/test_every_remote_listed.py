"""Every Harmony is its own remote, listed by its own name, even where one profile builds
several: the 510 had no name and the pickers listed it - once - as the 515 it is built
like, so a 510 owner could not find their remote. The names are Logitech's, from
MyHarmony's product catalogue (tests/fixtures/logitech-products.tsv), a European skin
with "(EMEA)"."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from afterglow import remotes

CATALOGUE = Path(__file__).parent / "fixtures" / "logitech-products.tsv"


def _catalogue() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for line in CATALOGUE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            skin, _region, shown, name = line.split("\t")
            out.setdefault(int(skin), []).extend([shown, name])
    return out


def _names() -> dict[int, str]:
    return {int(skin): entry["model"] for skin, entry in remotes.models().items()
            if not entry["model"].isdigit()}


def test_every_remote_logitech_lists_has_a_name():
    names = _names()
    assert sorted(set(_catalogue()) - set(names)) == []


def test_no_two_remotes_share_a_name():
    seen: dict[str, int] = {}
    for skin, name in _names().items():
        assert name not in seen, f"skins {seen[name]} and {skin} are both {name!r}"
        seen[name] = skin


@pytest.mark.parametrize("skin", sorted(_catalogue()))
def test_the_name_is_logitechs(skin):
    """Logitech's own, or it with "(EMEA)" for a European skin - "Harmony 650 EMEA" is
    listed "Harmony 650 (EMEA)" - or with what tells two of a name apart."""
    ours = _names()[skin]
    if skin in (37, 38):              # Monster's "AVL 100" is the AV-100 it prints
        assert ours.startswith("AV-100")
        return
    if skin == 54:                    # the One and the later One+: one skin, both names
        assert ours == "Harmony One / One+"
        return
    plain = re.sub(r" \((EMEA|white|EMEA, (bundled|retail)|bundled|retail)\)$", "", ours)
    theirs = {re.sub(r"(/EU| EU|EU|eu| EMEA)\b", "", name).strip().replace("  ", " ")
              for name in _catalogue()[skin]}
    theirs |= {re.sub(r" \((bundled|retail)\)$", "", name) for name in theirs}
    assert plain in theirs or ours in _catalogue()[skin], (skin, ours, theirs)


def test_every_remote_is_in_the_picker_once_by_its_own_name(qapp_or_skip):
    from afterglow.gui.remote_bar import ChooseRemoteDialog
    profiles = [p for p in remotes.load_all() if p.buildable]
    dialog = ChooseRemoteDialog(profiles, "Your remote", "", known=profiles)
    rows = [dialog.list.item(i) for i in range(dialog.list.count())]
    chosen = [(item.data(256), item.data(257)) for item in rows if item.data(256)]
    # each skin of each remote Afterglow builds, once, and by its own name
    assert sorted(chosen, key=str) == sorted(
        [(p.id, skin) for p in profiles for skin in p.skins], key=str)
    names = _names()
    for item in rows:
        if item.data(256):
            assert item.text().startswith(names[item.data(257)] + " ·"), item.text()
    # and every other remote Logitech lists, greyed
    shown = {item.text().split(" ·")[0] for item in rows}
    for skin in _catalogue():
        assert names[skin] in shown, names[skin]


def test_the_one_is_listed_as_the_one():
    """Skin 54 is the Harmony One, which Logitech's catalogue shows as the One+ that
    later shared it: named "Harmony One+" alone, the One was not in the list at all."""
    assert remotes.model_name(remotes.get("harmony-one"), 54) == "Harmony One / One+"


def test_a_european_skin_says_its_plain_name_on_the_remote():
    profile = remotes.get("harmony-650")
    assert remotes.model_name(profile, 74) == "Harmony 650 (EMEA)"
    assert remotes.printed_name(profile, 74) == "Harmony 650"
    assert remotes.printed_name(profile, 72) == "Harmony 650"
