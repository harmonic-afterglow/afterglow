"""Lay an arch-9 image out from named pieces, then give every pointer its address.

A build knows what every structure holds before it knows where any of it lands, and a
structure's size never depends on the addresses it holds - a pointer is three bytes
wherever it points. So an image is laid out twice: once with every address read as zero,
which fixes each piece's size and so its place, and once with the addresses that gave.
The second pass must produce the same sizes, or the image is refused.

Small structures are kept inside one 64 KiB window, as the 650's and the One's builders
keep them (structures._align_window): no object or drawing block of a 650 measured crosses
one (docs/harmony_650_700/gspm.md, "Building an image"), and arch 9's container is the
650's parent (docs/harmony_5xx/ahcm.md, "Outer structure").

Format reference: docs/harmony_5xx/ahcm.md, docs/harmony_650_700/gspm.md
"""

from __future__ import annotations

from typing import Callable

from . import gspm

WINDOW = 0x10000


class Pieces:
    """The pieces of an image in the order they are laid out, each named."""

    def __init__(self, header: Callable[["Pieces"], bytes]):
        self.header = header
        self.items: list[tuple[str, Callable[["Pieces"], bytes], bool]] = []
        self.names: set[str] = set()
        self.at: dict[str, int] = {}
        self.final = False

    def add(self, name: str, produce: Callable[["Pieces"], bytes], *,
            window: bool = True) -> str:
        """Add a piece; ``produce`` is given this object, whose ``address`` answers for
        every piece by name. With ``window``, the piece does not cross a 64 KiB window."""
        if name in self.names:
            raise ValueError(f"two pieces are named {name!r}")
        self.names.add(name)
        self.items.append((name, produce, window))
        return name

    def offset(self, name: str) -> int:
        """Where a piece lands, relative to the image; 0 while sizes are being measured."""
        if not self.final:
            return 0
        return self.at[name]

    def address(self, name: str) -> int:
        """A piece's absolute address, as a pointer holds it."""
        return gspm.BASE + self.offset(name)

    def pointer(self, name: str) -> bytes:
        return self.address(name).to_bytes(3, "little")

    def _lay(self) -> tuple[bytearray, dict[str, int], dict[str, int]]:
        out = bytearray(self.header(self))
        at, sizes = {}, {}
        for name, produce, window in self.items:
            body = produce(self)
            if window and len(body) <= WINDOW:
                start = gspm.BASE + len(out)
                if start // WINDOW != (start + len(body) - 1) // WINDOW:
                    out += bytes(WINDOW - start % WINDOW)
            at[name] = len(out)
            sizes[name] = len(body)
            out += body
        return out, at, sizes

    def lay_out(self) -> bytearray:
        """Measure, then write with the addresses the measuring gave."""
        self.final = False
        _out, at, sizes = self._lay()
        self.at, self.final = at, True
        out, at_again, sizes_again = self._lay()
        if at_again != at or sizes_again != sizes:
            moved = [name for name in at if at[name] != at_again.get(name)]
            raise ValueError(f"pieces changed size once given addresses: {moved[:5]}")
        return out
