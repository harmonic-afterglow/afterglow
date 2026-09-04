"""Harmony PK native lowering metadata, kept out of portable protocol JSON.

A portable protocol says what reaches the IR receiver.  The block id and command codec
below say how one Logitech architecture happens to express that signal.  These used to
live under ``native.harmony-pk`` in the shared protocol definitions, making a supposedly
portable catalogue depend on one remote family.  Backend ownership also lets another
remote implement the same protocol without modifying the shared definition.
"""

# How much is actually known about a lowering, weakest first. The tier is a claim about
# *this backend's* native emission, not about the portable protocol, which is why it
# lives here and not in `library/protocols`.
#
# Each step is a different kind of evidence, and they are not interchangeable:
#
#   vm-validated       The emitted program agrees with the portable definition when run
#                      through our port of the remote's carrier VM. Both sides are our
#                      code, so a systematic error in the port would be invisible.
#
#   emission-measured  The remote was flashed and its infrared output captured by an
#                      independent probe (`../ir_bench`), and the mark/space structure
#                      matched. This rules out a VM port error. It does NOT verify the
#                      carrier frequency - a demodulator strips it - and does not show
#                      that any appliance responds.
#
#   hardware-anchored  The strongest: the generated program reproduces a proven donor
#                      block byte-for-byte AND a real appliance was observed responding,
#                      so carrier, timing and framing are all confirmed together.
#
# Never promote on a clean build. Promote on evidence, and record the evidence with its
# date.
VALIDATION_TIERS = ("vm-validated", "emission-measured", "hardware-anchored")

PROTOCOLS = {
    "nec1": {
        "block_id": "a7b8a0e6c639", "code_codec": "nec", "emitter": "nec-family",
        "portable_signature": "699374fce557", "validation": "hardware-anchored"},
    "nec1-toshiba": {
        "block_id": "a7b8a0e6c639", "code_codec": "nec", "emitter": "nec-family",
        "portable_signature": "f338cf8682b6", "validation": "hardware-anchored"},
    "nec-ext": {
        "block_id": "a7b8a0e6c639", "code_codec": "necext", "emitter": "nec-family",
        "portable_signature": "dbe19ab1b126", "validation": "hardware-anchored"},
    "nec2": {
        "code_codec": "nec", "repeat_data_copy": True, "data_period_us": 95000,
        "emitter": "nec-family", "portable_signature": "a54b59e803e3",
        "validation": "vm-validated"},
    "nec2-ext": {
        "code_codec": "necext", "repeat_data_copy": True, "data_period_us": 95000,
        "emitter": "nec-family", "portable_signature": "33ec0bd9f727",
        "validation": "vm-validated"},
    "samsung32": {
        "block_id": "e8f716b9ee19",
        "code_codec": "samsung",
        "repeat_data_copy": True,
        "leader": "samsung",
        "emitter": "nec-family",
        "portable_signature": "adb4953fcddd",
        "validation": "hardware-anchored",
    },
    "rc6-mce": {
        "block_id": "6bd42e0eea79", "code_codec": "rc6-mce", "emitter": "rc6",
        "portable_signature": "3ef5b2278f82", "validation": "hardware-anchored"},
    "sony12": {
        "code_codec": "sony12", "emitter": "sony",
        "portable_signature": "1d9e6c6c2cfe", "validation": "emission-measured"},
    "sony15": {
        "code_codec": "sony15", "emitter": "sony",
        "portable_signature": "ee771c3442ee", "validation": "vm-validated"},
    "sony20": {
        "code_codec": "sony20", "emitter": "sony",
        "portable_signature": "1cd83cc5c65d", "validation": "emission-measured"},
    "jvc16": {
        "code_codec": "jvc16", "emitter": "jvc16",
        "portable_signature": "24bc4cd639af", "validation": "emission-measured"},
    "rc5-13": {
        "code_codec": "rc5-13", "emitter": "rc5",
        "portable_signature": "e219f3968400", "validation": "emission-measured"},
}



def protocol(protocol_id: str) -> dict | None:
    """A copy of one proven lowering, or ``None`` when this backend cannot do it."""
    mapping = PROTOCOLS.get(protocol_id)
    return dict(mapping) if mapping is not None else None
