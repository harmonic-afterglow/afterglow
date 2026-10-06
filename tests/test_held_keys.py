"""A physical key bound to a device's command keeps repeating while it is held.

Logitech binds such a key to the command's own `<id>_<command>_Hold` ActionList. Import
stored it as a bare command, which the builder wrote as a one-step macro with a Press:
holding Volume Up sent it once.
"""
from afterglow.backends.harmony_pk.builder.activities import _gen_activity


def test_a_key_bound_to_one_held_command_is_bound_to_it_directly():
    by_id = {"1": {"id": "1", "commands": [["Mute", "Mute", "", "", None]]}}
    xml, action_lists = _gen_activity({
        "id": "9", "label": "A", "type": "VirtualGeneric", "display": "1",
        "control": "1", "bound_keys": ["VolumeMute"],
        "hard_macros": {"VolumeMute": [["command", "1", "Mute", "Hold"]]}}, by_id)
    assert "<ActionId>1_Mute_Hold</ActionId>" in xml and not action_lists


def test_a_longer_macro_still_gets_its_own_action_list():
    by_id = {"1": {"id": "1", "commands": [["Mute", "Mute", "", "", None]]}}
    xml, action_lists = _gen_activity({
        "id": "9", "label": "A", "type": "VirtualGeneric", "display": "1",
        "control": "1", "bound_keys": ["VolumeMute"],
        "hard_macros": {"VolumeMute": [["command", "1", "Mute", "Hold"],
                                       ["command", "1", "Mute"]]}}, by_id)
    assert "<ActionId>9_hardmacro_VolumeMute</ActionId>" in xml and len(action_lists) == 1
