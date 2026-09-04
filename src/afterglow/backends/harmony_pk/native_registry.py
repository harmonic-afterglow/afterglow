"""Generate Harmony PK native programs from the portable protocol catalogue.

There is deliberately no native protocol-file catalogue. A generated entry is accepted
only through :mod:`ir_emit`, which binds the backend's measured timing calibration to one
portable semantic revision, executes the result in the literal carrier VM, and compares
several edge/mixed parameter vectors with the portable waveform. Portable semantics remain
the application source of truth; calibrated native timings remain a hidden backend concern.
This module only collects ephemeral build products and deduplicates protocols that share
one program.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from . import ir_emit, mappings, protocol_json


@lru_cache(maxsize=1)
def _generated() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for protocol_id, mapping in mappings.PROTOCOLS.items():
        if not mapping.get("emitter"):
            continue
        try:
            spec = ir_emit.emit(protocol_id, mapping)
        except LookupError:
            # This catalogue is an *optimisation*: it recognises a dumped block as a
            # protocol already described portably, so importing can skip reconstructing
            # one. A protocol that is not installed simply cannot be recognised, and the
            # block goes through `extract_definition` and `promote` like any other -
            # which reproduces it from the file itself.
            #
            # Raising here made an empty library fatal to *import*, which is backwards:
            # importing is precisely the operation that does not need a library, because
            # every protocol it needs is in the configuration being read.
            continue
        existing = out.get(spec["id"])
        if existing is not None:
            if (protocol_json.encode(existing, position=10)
                    != protocol_json.encode(spec, position=10)):
                raise ValueError(
                    f"portable protocols generate conflicting block {spec['id']}")
            continue
        out[spec["id"]] = spec
    return out


def catalog() -> dict[str, dict]:
    """Return fresh copies of every VM-proven generated native build product."""
    return deepcopy(_generated())


@lru_cache(maxsize=1)
def code_codecs() -> dict[str, str]:
    """``{generated block id: Code codec}`` for every family this backend can frame.

    The builder needs to know whether it can *manufacture* a command for a block, not
    merely emit the block's pulse program. Those two capabilities are tracked
    separately, and the second list went stale: `codes.SYNTHESIZABLE_PROTOCOLS` still
    named only NEC, Samsung and RC6 long after `ir_emit` gained Sony, JVC and RC5 and
    `mappings` gained their codecs, so a build with a generated Sony device was refused
    as "donor-only" even though every piece needed to make it was present.

    Deriving it from `mappings.PROTOCOLS` keeps one source of truth: a family that
    declares an emitter *and* a codec is synthesizable by construction, and adding the
    next one needs no second edit here.

    One block may legitimately serve several codecs: NEC1 and NEC-extended emit the same
    pulse program and differ only in how the address bytes are framed, so the block id
    identifies the program, never the Code format. Callers use this to ask *whether* a
    block can be manufactured; the codec for a given command comes from that command's
    own protocol mapping, via `codes.portable_code`.
    """
    out: dict[str, str] = {}
    for protocol_id, mapping in mappings.PROTOCOLS.items():
        if not mapping.get("emitter") or not mapping.get("code_codec"):
            continue
        try:
            spec = ir_emit.emit(protocol_id, mapping)
        except LookupError:
            # Same reasoning as `_generated`: a protocol that is not installed has no
            # generated block, so nothing can be keyed to it. Blocks reconstructed from an
            # imported configuration carry their own Codes and never consult this map.
            continue
        out.setdefault(spec["id"], mapping["code_codec"])
    return out
