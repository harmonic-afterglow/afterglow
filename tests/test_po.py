"""The standard-library gettext reader and template writer."""

from __future__ import annotations

from afterglow import po

FINNISH = r'''# a comment
msgid ""
msgstr ""
"Language: fi\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgctxt "hub.no-devices"
msgid "No devices"
msgstr "Ei laitteita"

#, fuzzy
msgctxt "hub.devices-title"
msgid "Devices"
msgstr "Laitteet?"

msgctxt "system.screen.9"
msgid "Charging problem."
msgstr ""
"Latausongelma.\n"
"Ota yhteys \"tukeen\""

msgctxt "pages"
msgid "page"
msgid_plural "pages"
msgstr[0] "sivu"
msgstr[1] "sivua"

#~ msgctxt "old"
#~ msgid "Gone"
#~ msgstr "Poissa"
'''


def test_a_catalogue_answers_by_context_and_reads_continued_and_escaped_strings():
    catalogue = po.parse(FINNISH)
    assert catalogue.get("hub.no-devices", "No devices") == "Ei laitteita"
    assert catalogue.get("system.screen.9", "Charging problem.") == \
        'Latausongelma.\nOta yhteys "tukeen"'
    assert catalogue.header["Language"] == "fi"


def test_fuzzy_and_obsolete_entries_are_not_translations():
    catalogue = po.parse(FINNISH)
    assert catalogue.get("hub.devices-title", "Devices") is None
    assert catalogue.get("old", "Gone") is None


def test_plural_forms_follow_the_catalogue_s_own_rule():
    catalogue = po.parse(FINNISH)
    assert catalogue.get("pages", "page", 1) == "sivu"
    assert catalogue.get("pages", "page", 5) == "sivua"
    # three forms, as Russian has them
    russian = po.parse(FINNISH.replace(
        "nplurals=2; plural=(n != 1);",
        "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && "
        "(n%100<10 || n%100>=20) ? 1 : 2);").replace(
        'msgstr[1] "sivua"', 'msgstr[1] "two-four"\nmsgstr[2] "many"'))
    assert [russian.get("pages", "page", n) for n in (1, 3, 5, 21)] == [
        "sivu", "two-four", "many", "sivu"]


def test_a_template_reads_back_as_an_empty_catalogue():
    text = po.template([po.Message("a.b", "Hello", "where it is drawn"),
                        po.Message("c", "page", plural="pages"),
                        po.Message("d", "Message {number}", brace_format=True)], "test")
    assert "#. where it is drawn" in text and "#, python-brace-format" in text
    catalogue = po.parse(text)
    assert catalogue.get("a.b", "Hello") is None and catalogue.plural is None
