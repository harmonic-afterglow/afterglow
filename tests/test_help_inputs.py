"""An input's own name read back from Help's question about it (backends/help_inputs):
the 650s, 700s, Ones and 800s keep only how many inputs a device has, and an import
called them "Input 1", "Input 2" - which a tester's rebuilt remote then asked about."""
from afterglow.backends import help_inputs


def _asked(text):
    patterns = [help_inputs.question(wording) for wording in (
        "Is the {device} set to the {input} input?",
        "Ist für {device} der Eingang {input} gewählt?",
        *help_inputs.LOGITECH)]
    # every wording that matches: the import keeps the one whose device is a device's
    # name ("LG TV", not the "LG TV nu" the wording without "nu" leaves)
    found = [(match["device"].strip(), match["input"].strip()) for pattern in patterns
             for match in [pattern.search(" ".join(text.split()))] if match]
    return min(found, key=lambda pair: len(pair[0])) if found else None


def test_the_question_is_read_in_the_remotes_language_as_its_font_draws_it():
    assert _asked("Is the Soniq TV set to the HDMI 3 input? No Yes") == ("Soniq TV", "HDMI 3")
    # a German One: its font has no glyph for some letters, and breaks a name at a hyphen
    assert _asked("Ist f?r AV-Receiver- Wohnzimmer der Eingang QuickSelect1 gew?hlt? Ja "
                  "Nein") == ("AV-Receiver- Wohnzimmer", "QuickSelect1")
    # Logitech's French and Dutch, worded otherwise than a translation of the English
    assert _asked("Le/la TV OLD est-il/elle r?gl?(e) sur I'entr?e TV Tuner? Oui Non") \
        == ("TV OLD", "TV Tuner")
    assert _asked("Is uw LG TV nu ingesteld op ingang Smart TV? Ja Nee") == (
        "LG TV", "Smart TV")
    assert _asked("Is the TV on? No Yes") is None


def test_a_device_is_the_one_whose_name_help_broke_over_lines():
    assert help_inputs._same("AV-Receiver-Wohnzimmer", "AV-Receiver- Wohnzimmer")
    assert not help_inputs._same("TV", "TV OLD")


def test_only_an_input_known_by_its_number_takes_the_name():
    devices = [
        {"input_cycle": {"values": ["Input 1", "Input 2", "Input 3"]}},
        {"inputs": [["Input 1"], ["InputHdmi1", "InputHdmi1"], ["Input 3"]],
         "online_inputs": ["Input 3"]},
    ]
    help_inputs.apply(devices, {(0, 1): "HDMl 2", (1, 1): "HDMI 1", (1, 2): "Netflix",
                                (1, 0): "Netflix"})
    # "HDMl": the font draws l and I alike
    assert devices[0]["input_cycle"]["values"] == ["Input 1", "HDMI 2", "Input 3"]
    # named after its command, it keeps that; a name taken already is not given twice;
    # an app input stays one under its new name
    assert [entry[0] for entry in devices[1]["inputs"]] == ["Input 1", "InputHdmi1",
                                                            "Netflix"]
    assert devices[1]["online_inputs"] == ["Netflix"]


def test_a_capital_i_drawn_as_an_l_is_read_back():
    assert [help_inputs._capital_i(name) for name in ("HDMl 2", "DVl", "Tool", "TVlnput")] \
        == ["HDMI 2", "DVI", "Tool", "TVlnput"]
