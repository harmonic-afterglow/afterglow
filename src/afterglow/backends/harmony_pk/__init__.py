"""The ``PK\x03\x04`` ezhex-payload backend, verified on the Harmony 900.

`IrProto.bin` bytecode blocks, `SsIr.bin` recorded waveforms, the readable JSON form of a
protocol block, and the compiler that lowers a portable signal into these. All of it is
specific to this payload and IR runtime. A tree-like layout on another Harmony model is
not evidence that it uses this backend; Harmony One, for example, begins with ``GSPM`` and
uses a different indexed configuration layout.

Submodules are deliberately **not** imported here. `ssir` and the portable `ir_signal`
reference each other, and an eager package import turns that into a hard cycle. Import
what you need explicitly:

    from afterglow.backends.harmony_pk import irproto
"""

NAME = "harmony-pk"
LEGACY_NAMES = ("harmony-z", "harmony-ziptree")
BACKEND_NAMES = (NAME, *LEGACY_NAMES)
