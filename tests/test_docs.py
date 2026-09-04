"""The format documentation exists and is reachable from the code.

Documentation that nothing links to goes stale unnoticed. These are cheap checks that the
files are present and that every `Format reference:` line in the package names one that
exists.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PACKAGE = ROOT / "src" / "afterglow"

EXPECTED = (
    "README.md",
    "harmony_pk/README.md",
    "harmony_pk/ezhex.md",
    "harmony_pk/configuration.md",
    "harmony_pk/irproto.md",
    "harmony_pk/ssir.md",
    "harmony_pk/remote-identities.md",
)


def test_the_format_documents_are_present():
    missing = [name for name in EXPECTED if not (DOCS / name).is_file()]
    assert not missing, f"missing format documentation: {missing}"


def test_every_format_reference_points_at_a_real_document():
    """Modules cite the docs instead of restating the format. A citation that has gone
    stale is worse than no citation, because it reads as authoritative."""
    broken = []
    for source in PACKAGE.rglob("*.py"):
        for line in source.read_text().splitlines():
            for target in re.findall(r"docs/([\w/.-]+\.md)", line):
                if not (DOCS / target).is_file():
                    broken.append(f"{source.relative_to(ROOT)} -> docs/{target}")
    assert not broken, f"references to documents that do not exist: {broken}"


def test_the_readme_and_icon_set_are_present():
    """The mark is referenced from the README and the icon set is complete.

    The window icon, the About dialog and the Windows executable all read from
    `branding/`, and each small size is a separate drawing rather than a downscale, so a
    missing one degrades quietly rather than failing.
    """
    branding = PACKAGE / "branding"
    for name in ("afterglow-icon-16.svg", "afterglow-icon-24.svg",
                 "afterglow-icon-32.svg", "afterglow-icon.svg",
                 "afterglow.ico"):
        assert (branding / name).is_file(), f"missing branding asset: {name}"

    # The README uses the flat mark from `branding/`, not a rendered PNG: it is the same
    # geometry, it scales, and it is the copy the application already ships.
    readme = (ROOT / "README.md").read_text()
    mark = "src/afterglow/branding/afterglow-icon.svg"
    assert mark in readme, "the README does not show the mark"
    assert (ROOT / mark).is_file()


def test_the_windows_icon_carries_every_size():
    """A single-size .ico makes Windows scale one drawing to all of them, which is what
    the size-specific SVGs exist to avoid."""
    import struct

    data = (PACKAGE / "branding" / "afterglow.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "not an icon file"
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert sizes == {16, 24, 32, 48, 64, 128, 256}, sizes


def test_the_index_links_every_document():
    index = (DOCS / "README.md").read_text()
    unlinked = [name for name in EXPECTED
                if name != "README.md" and f"]({name})" not in index]
    assert not unlinked, f"not linked from docs/README.md: {unlinked}"


def test_ci_does_not_skip_a_path_the_suite_reads():
    """`paths-ignore` names files no code build depends on."""
    import re

    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    ignored = set(re.findall(r'^\s*-\s*"([^"]+)"\s*$', workflow, re.M))

    read_by_tests = {"assets", "pyproject.toml",
                     "src", "tests", "packaging", "afterglow.py"}
    overlap = {path for path in ignored
               if path.split("/")[0].rstrip("*").rstrip("/") in read_by_tests}
    assert not overlap, f"CI ignores paths the suite depends on: {overlap}"
