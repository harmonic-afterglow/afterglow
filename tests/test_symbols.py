"""The window's own buttons draw Google's Material Symbols (src/afterglow/symbols, Apache
2.0), not "+", "->" or a braille dot pattern as text, which looked different in every
font."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from afterglow import paths

SOURCE = Path(__file__).resolve().parents[1] / "src" / "afterglow"
# an arrow, a single right angle quote or braille in a string, or a string starting "+ "
SYMBOLS = re.compile("[\"'][^\"']*[\u2190-\u21ff\u203a\u2800-\u28ff]|[\"']\\+ [A-Z]")
USED = ("add", "arrow_forward", "chevron_left", "chevron_right", "content_copy", "delete",
        "drag_indicator", "menu", "search")


@pytest.mark.parametrize("name", USED)
def test_each_icon_is_shipped(name):
    assert paths.symbols(f"{name}.svg").is_file()


def test_the_icons_carry_their_licence():
    assert "Apache License" in paths.symbols("LICENSE").read_text(encoding="utf-8")
    assert "Material Symbols" in paths.symbols("NOTICE.md").read_text(encoding="utf-8")


def test_an_icon_is_drawn_in_the_palette_s_colour(qapp_or_skip):
    from afterglow.gui import symbols
    assert not symbols.icon("add").pixmap(16, 16).isNull()
    assert b'fill="#123456"' in symbols.svg("add", "#123456")


def test_no_button_or_text_draws_an_arrow_or_plus_as_a_character():
    found = []
    for path in [*SOURCE.joinpath("gui").glob("*.py"), SOURCE / "concord.py"]:
        if path.name == "symbols.py":            # its docstring quotes the old labels
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(SYMBOLS, code):
                found.append(f"{path.name}:{number}: {line.strip()}")
    assert found == []
