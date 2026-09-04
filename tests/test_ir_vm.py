"""The native carrier VM is an oracle for protocol-program synthesis.

These checks use generated package data, not private donor files.  The native blocks
contain measured timings, so NEC/Samsung compare by topology and tolerance; RC6's known
block happens to match the portable definition exactly after storage chunks are merged.
"""
from afterglow import ir_protocol, ir_signal
from afterglow.backends.harmony_pk import ir_vm, protocol_json
from afterglow.backends.harmony_pk.builder import codes


def _payload(block_id):
    return protocol_json.assemble([protocol_json.catalog()[block_id]])


def _render(protocol, parameters, phase="press"):
    waveform, _state = ir_protocol.render_transmission(
        ir_signal.protocol_signal(protocol, parameters), phase=phase)
    return tuple(waveform["pulses_us"])


def _pulses(words):
    return tuple((word & 0x7FFF) * (1 if word & 0x8000 else -1)
                 for word in words if word & 0x7FFF)


def _assert_measured_equivalent(expected, actual):
    actual = ir_vm.normalise_pulses(actual)
    assert len(actual) == len(expected)
    assert all((left > 0) == (right > 0) for left, right in zip(expected, actual))
    # The blocks carry observed timings rather than ideal protocol constants.  Six
    # percent with a 30 us floor covers those measurements without accepting a missing
    # half-bit or a wrong symbol.
    for left, right in zip(expected, actual):
        assert abs(abs(left) - abs(right)) <= max(30, round(abs(left) * 0.06))


def test_native_nec_vm_reproduces_the_yamaha_volume_up_waveform():
    parameters = {"address": 0x7A, "command": 0x1A}
    result = ir_vm.simulate_sequence(
        _payload("a7b8a0e6c639"),
        codes.nec_code(parameters["address"], parameters["command"]))

    assert result.carrier_hz == 38001
    assert result.pulses_us[:4] == (8990, -4490, 568, -552)
    assert sum(abs(pulse) for pulse in result.pulses_us) == 107870
    _assert_measured_equivalent(_render("nec1", parameters), result.pulses_us)


def test_native_samsung_vm_reproduces_a_full_samsung32_frame():
    parameters = {"address": 0x07, "command": 0x02}
    result = ir_vm.simulate_sequence(
        _payload("e8f716b9ee19"),
        codes.samsung_code(parameters["address"], parameters["command"]))

    assert result.pulses_us[:4] == (4500, -4500, 568, -1662)
    _assert_measured_equivalent(_render("samsung32", parameters), result.pulses_us)


def test_native_rc6_vm_applies_the_sender_owned_toggle_bit():
    parameters = {"code": 0x0800F041}
    payload = _payload("6bd42e0eea79")
    code = codes.rc6_mce_code(parameters["code"])

    toggle_one = ir_vm.normalise_pulses(
        ir_vm.simulate_sequence(payload, code, toggle_state=1).pulses_us)
    toggle_zero = ir_vm.normalise_pulses(
        ir_vm.simulate_sequence(payload, code, toggle_state=0).pulses_us)

    # The portable lifecycle advances its initial zero before a press, so its first
    # transmitted RC6 frame carries toggle one.
    assert toggle_one == _render("rc6-mce", parameters)
    assert toggle_zero != toggle_one


def test_native_vm_rejects_a_code_selecting_a_missing_protocol():
    code = bytearray.fromhex(codes.nec_code(0x7A, 0x1A).removeprefix("0x"))
    code[0] = 1
    try:
        ir_vm.simulate_sequence(_payload("a7b8a0e6c639"), bytes(code))
    except ir_vm.IrVmError as exc:
        assert "payload has 1" in str(exc)
    else:
        raise AssertionError("missing native protocol was accepted")


def test_native_vm_follows_initial_and_repeat_sequence_stages():
    payload = _payload("a7b8a0e6c639")
    code = codes.nec_code(0x7A, 0x1A)
    first = ir_vm.simulate_sequence(payload, code)
    complete = ir_vm.simulate_transmission(payload, code)

    assert complete.sequence_stages == (2, 3)
    assert complete.sequence_word_counts == (len(first.words), 6)
    assert complete.words[:len(first.words)] == first.words
    _assert_measured_equivalent(
        _render("nec1", {"address": 0x7A, "command": 0x1A}, phase="hold"),
        _pulses(complete.words[-complete.sequence_word_counts[-1]:]))

    # Code byte 4 is the firmware's minimum stage-3 execution count. It is not a
    # portable guess: ProcessIrCmd copies this exact byte to the field consulted by
    # ir_carrier_prepare_next_data.
    minimum_three = bytearray.fromhex(code.removeprefix("0x"))
    minimum_three[4] = 3
    repeated = ir_vm.simulate_transmission(payload, minimum_three)
    assert repeated.sequence_stages == (2, 3, 3, 3)
    assert repeated.sequence_word_counts == (len(first.words), 6, 6, 6)


def test_native_vm_bounds_physical_hold_and_timed_send_modes():
    payload = _payload("e8f716b9ee19")
    code = codes.samsung_code(0x07, 0x02)

    held = ir_vm.simulate_transmission(payload, code, held_replays=2)
    assert held.sequence_stages == (2, 3, 3, 3)
    assert len(set(held.sequence_word_counts)) == 1
    size = held.sequence_word_counts[0]
    _assert_measured_equivalent(
        _render("samsung32", {"address": 0x07, "command": 0x02}, phase="hold"),
        _pulses(held.words[size:2 * size]))

    timed = ir_vm.simulate_transmission(payload, code, duration_us=300_000)
    elapsed = [word & 0x7FFF for word in timed.words]
    before_last = sum(elapsed[:-timed.sequence_word_counts[-1]])
    assert timed.sequence_stages == (2, 3, 3)
    assert before_last < 300_000 <= sum(elapsed)

    try:
        ir_vm.simulate_transmission(
            payload, code, held_replays=1, duration_us=1)
    except ir_vm.IrVmError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("physical-hold and timed-send modes were combined")


def test_native_rc6_stage_three_replays_keep_one_press_toggle_state():
    payload = _payload("6bd42e0eea79")
    result = ir_vm.simulate_transmission(
        payload, codes.rc6_mce_code(0x0800F041), toggle_state=1, held_replays=2)

    assert result.sequence_stages == (3, 3, 3)
    size = result.sequence_word_counts[0]
    assert result.sequence_word_counts == (size, size, size)
    assert result.words[:size] == result.words[size:2 * size] == result.words[2 * size:]


def test_native_vm_reaches_a_stage_five_finish_sequence_after_delimiter():
    payload = _payload("a7b8a0e6c639")
    code = bytearray.fromhex(codes.nec_code(0x7A, 0x1A).removeprefix("0x"))
    data = code[7:11]
    code.extend((1, 0))  # stage-5 sequence count and full-frame element index
    code.extend(data)

    result = ir_vm.simulate_transmission(payload, code)

    assert result.sequence_stages == (2, 3, 5)
    assert result.sequence_word_counts[0] == result.sequence_word_counts[2]
