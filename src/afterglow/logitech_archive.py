#!/usr/bin/env python3
"""Pinned adapter for the optional Logitech Harmony IR archive.

The archive is useful evidence, but it is neither an Afterglow runtime dependency nor
data this project may silently redistribute.  This module reads a user-selected schema-1
checkout, retains every source record under provenance, and emits content-addressed
protocol records plus shared code sets and catalogue devices.  Devices continue to point
at code sets, so conversion does not multiply millions of identical commands.

Derived Pronto is treated as a conformance oracle and waveform fallback.  A command is
semantic only when an explicit adapter exists and its portable waveform agrees with the
Pronto timing.  Everything else receives an explicit, auditable classification.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterator
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import ir_protocol, ir_signal

# Schema 2 (upstream 2026-09-02) adds per-device `timing`, `power`, `inputs`,
# `channelTuning` and `states`. It is additive and absent-never-null: `codesets/`,
# `protocols/` and every index are byte-identical to schema 1, so a reader of either
# version sees the same commands. Both are accepted; `ARCHIVE_SCHEMA_VERSION` remains the
# one we write into audit state.
ARCHIVE_SCHEMA_VERSION = 2
SUPPORTED_ARCHIVE_SCHEMAS = (1, 2)
CORPUS_SCHEMA = "afterglow-ir-corpus/1"
PROTOCOL_RECORD_SCHEMA = "afterglow-ir-protocol-record/1"
CODESET_SCHEMA = "afterglow-ir-codeset/1"
DEVICE_SCHEMA = "afterglow-catalog-device/1"

CLASSIFICATIONS = (
    "semantic-with-pronto-agreement",
    "portable-with-pronto-agreement",
    "waveform-only",
    "non-ir",
    "target-incapable",
    "corrupt-source",
    "unsupported",
)


@dataclass(frozen=True)
class Verdict:
    """What one command was classified as, why, and its portable signal if it earned one.

    The classification is checked against `CLASSIFICATIONS` on construction, so an
    unrecognised one cannot reach a written corpus record.
    """

    classification: str
    reason: str
    signal: dict | None = None

    def __post_init__(self) -> None:
        if self.classification not in CLASSIFICATIONS:
            raise ValueError(
                f"unknown command classification {self.classification!r}")


@dataclass(frozen=True)
class _Candidate:
    """One conversion attempt: the signal it produced, or the reason it produced none.

    A failed attempt deliberately carries no classification. Whether it means
    `waveform-only` depends on whether a later attempt succeeds, which only
    `analyse_command` is in a position to decide.
    """

    signal: dict | None
    reason: str


# These mappings have both a checked-in portable definition and direct archive evidence.
# The numeric id prevents an unrelated future protocol with the same display name from
# being accepted accidentally.
# source protocol name -> (source id, portable id, one-frame override, value adapter)
#
# Most reviewed protocols expose one Code0 value directly. NEC-family catalogue names
# are the exception: their 32-bit value is written in wire order (MSB first), while the
# portable definition takes the logical address and command and emits each byte LSB first.
# The two representations are equivalent only after the byte integrity checks and bit
# reversal performed by `_portable_parameters` below.
PORTABLE_PROTOCOLS = {
    "Sony 12 Bit": (1, "sony12", "data", "code"),
    "Sony 15 Bit": (17, "sony15", "data", "code"),
    "Sony 20 Bit": (18, "sony20", "data", "code"),
    "JVC 16 Bit": (9, "jvc16", None, "code"),
    "Microsoft 30 Bit": (85, "rc6-mce", "data", "code"),
    "Philips RC5 13 Bit Toggle": (674, "rc5-13", "data", "code"),
    "Toshiba 32 Bit": (2, "nec1-toshiba", None, "nec-wire"),
    "GoVideoO1 32 Bit": (677, "samsung32", "press", "samsung-wire"),
}

NON_IR_PROTOCOLS = {"HID 16 Bit", "Sonos IP", "Roku IP"}
OUT_OF_IR_RANGE_PROTOCOLS = {"ATI 21 Bit"}
KEYCODE_RE = re.compile(
    r"^G:(?P<protocol>.*):\((?P<start>[^()]*)\)"
    r"\((?P<repeat>[^()]*)\)\((?P<finish>[^()]*)\):(?P<hint>[^:]*)$")
PRONTO_RE = re.compile(
    r"[0-9A-Fa-f]{4}(?: [0-9A-Fa-f]{4}){3}(?: [0-9A-Fa-f]+)+")


class ArchiveError(ValueError):
    """The selected source is not the archive schema this adapter understands."""


def canonical_bytes(value) -> bytes:
    """Stable JSON bytes used for content identities and source fingerprints."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _source(relative: str, record: dict) -> dict:
    return {
        "kind": "logitech-harmony-ir-archive",
        "path": relative,
        "sha256": digest(record),
        "record": record,
    }


class Archive:
    """Read-only view of one local archive checkout."""

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.revision: str | None = None
        self.manifest = self.read_json("manifest.json")
        version = self.manifest.get("schemaVersion")
        if version not in SUPPORTED_ARCHIVE_SCHEMAS:
            raise ArchiveError(
                f"expected Logitech archive schema in {SUPPORTED_ARCHIVE_SCHEMAS}, "
                f"got {version!r}")
        self._protocol_index: dict[str, dict] | None = None
        self._protocol_cache: dict[str, tuple[str, dict]] = {}

    def _path(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ArchiveError(f"archive path escapes its root: {relative!r}")
        path = (self.root / Path(*pure.parts)).resolve()
        if not path.is_relative_to(self.root):
            raise ArchiveError(f"archive path escapes its root: {relative!r}")
        return path

    def read_json(self, relative: str):
        path = self._path(relative)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ArchiveError(f"archive record does not exist: {relative}") from exc
        except json.JSONDecodeError as exc:
            raise ArchiveError(f"invalid JSON in archive record {relative}: {exc}") from exc

    @property
    def protocol_index(self) -> dict[str, dict]:
        if self._protocol_index is None:
            entries = self.read_json("protocols/index.json")
            found = {}
            for entry in entries:
                name = entry.get("n")
                filename = entry.get("f")
                if not name or not filename:
                    raise ArchiveError("protocols/index.json contains an incomplete entry")
                if name in found:
                    raise ArchiveError(f"duplicate archive protocol name {name!r}")
                found[name] = entry
            self._protocol_index = found
        return self._protocol_index

    def protocol(self, name: str) -> tuple[str, dict]:
        cached = self._protocol_cache.get(name)
        if cached is not None:
            return cached
        try:
            filename = self.protocol_index[name]["f"]
        except KeyError:
            raise ArchiveError(f"archive protocol {name!r} is not indexed") from None
        relative = f"protocols/{filename}"
        record = self.read_json(relative)
        if record.get("name") != name:
            raise ArchiveError(
                f"protocol index names {name!r}, but {relative} contains "
                f"{record.get('name')!r}")
        result = (relative, record)
        self._protocol_cache[name] = result
        return result

    def device(self, relative: str) -> dict:
        if not relative.startswith("devices/") or relative.endswith("/index.json"):
            raise ArchiveError("a device path must name devices/<manufacturer>/<model>.json")
        record = self.read_json(relative)
        required = {"manufacturer", "model", "globalDeviceId", "deviceType", "codeset"}
        missing = required - set(record)
        if missing:
            raise ArchiveError(f"device {relative} is missing {sorted(missing)}")
        return record

    def iter_codesets(self) -> Iterator[tuple[str, dict]]:
        for path in sorted(self.root.glob("codesets/*/*.json")):
            relative = path.relative_to(self.root).as_posix()
            yield relative, self.read_json(relative)

    def iter_devices(self) -> Iterator[tuple[str, dict]]:
        for path in sorted(self.root.glob("devices/*/*.json")):
            if path.name == "index.json":
                continue
            relative = path.relative_to(self.root).as_posix()
            yield relative, self.device(relative)


class CachedHttpArchive(Archive):
    """Fetch selected records from an immutable raw-HTTP source into a local cache.

    The base URL must contain either ``{revision}`` or the exact 40-hex revision.  This
    makes it impossible for a moving branch URL to masquerade as pinned provenance.  A
    representative device conversion downloads only its manifest, protocol index, device,
    shared code set, and referenced protocols; a whole-corpus audit still requires a local
    checkout because the source has no code-set index.
    """

    def __init__(self, base_url: str, cache, revision: str):
        if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
            raise ArchiveError("managed HTTP mode needs a full 40-hex source revision")
        if "{revision}" in base_url:
            base_url = base_url.replace("{revision}", revision)
        elif revision.lower() not in base_url.lower():
            raise ArchiveError("managed HTTP base URL must contain its pinned revision")
        if not base_url.startswith("https://"):
            raise ArchiveError("managed archive fetching requires an HTTPS base URL")
        self.base_url = base_url.rstrip("/")
        self.cache_root = Path(cache).expanduser().resolve() / revision.lower()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        super().__init__(self.cache_root)
        self.revision = revision.lower()

    def read_json(self, relative: str):
        path = self._path(relative)
        if not path.is_file():
            encoded = "/".join(quote(part, safe="") for part in PurePosixPath(relative).parts)
            request = Request(
                f"{self.base_url}/{encoded}",
                headers={"User-Agent": "Afterglow Logitech archive adapter/1"},
            )
            try:
                with urlopen(request, timeout=60) as response:
                    payload = response.read()
            except OSError as exc:
                raise ArchiveError(f"could not fetch archive record {relative}: {exc}") from exc
            try:
                json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArchiveError(f"fetched archive record is not JSON: {relative}") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        return super().read_json(relative)

    def iter_codesets(self) -> Iterator[tuple[str, dict]]:
        raise ArchiveError(
            "whole-corpus audit needs a local checkout; managed HTTP mode fetches "
            "selected indexed records only")

    def iter_devices(self) -> Iterator[tuple[str, dict]]:
        raise ArchiveError(
            "whole-corpus conversion needs a local checkout; managed HTTP mode fetches "
            "selected indexed records only")


class LiveHttpArchive(Archive):
    """Read the current contents of an HTTPS archive without cloning it.

    Unlike ``CachedHttpArchive``, this source deliberately follows a moving remote URL.
    Each requested record is fetched once per catalog session and replaces its cached
    copy. The cache is only a record of what was read; a network failure is reported
    instead of silently presenting an old database as current.
    """

    def __init__(self, base_url: str, cache):
        if not base_url.startswith("https://"):
            raise ArchiveError("live archive fetching requires an HTTPS base URL")
        self.base_url = base_url.rstrip("/")
        self.cache_root = Path(cache).expanduser().resolve() / "live"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._fetched: set[str] = set()
        super().__init__(self.cache_root)

    def read_json(self, relative: str):
        path = self._path(relative)
        if relative not in self._fetched:
            encoded = "/".join(quote(part, safe="") for part in PurePosixPath(relative).parts)
            request = Request(
                f"{self.base_url}/{encoded}",
                headers={"User-Agent": "Afterglow Logitech archive adapter/1"},
            )
            try:
                with urlopen(request, timeout=60) as response:
                    payload = response.read()
            except OSError as exc:
                raise ArchiveError(f"could not fetch live archive record {relative}: {exc}") \
                    from exc
            try:
                json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArchiveError(f"fetched archive record is not JSON: {relative}") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
            self._fetched.add(relative)
        return Archive.read_json(self, relative)

    def iter_codesets(self) -> Iterator[tuple[str, dict]]:
        raise ArchiveError(
            "whole-corpus audit needs a local checkout; the live source reads selected "
            "indexed records only")

    def iter_devices(self) -> Iterator[tuple[str, dict]]:
        raise ArchiveError(
            "whole-corpus conversion needs a local checkout; the live source reads "
            "selected indexed records only")


def _pronto_words(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        raise ArchiveError("Pronto must be a non-empty string")
    clean = text.strip()
    if not PRONTO_RE.fullmatch(clean):
        raise ArchiveError("Pronto must contain space-separated four-digit hex words")
    words = clean.split(" ")
    if len(words) < 4:
        raise ArchiveError("Pronto needs a four-word header")
    if words[0].upper() != "0000":
        raise ArchiveError(f"only learned/raw Pronto 0000 is supported, got {words[0]}")
    try:
        divisor, intro_pairs, repeat_pairs = (
            int(words[1], 16), int(words[2], 16), int(words[3], 16))
    except ValueError as exc:
        raise ArchiveError("Pronto contains an invalid header word") from exc
    if divisor == 0:
        raise ArchiveError("Pronto carrier divisor cannot be zero")
    intro_pulses = intro_pairs * 2
    repeat_pulses = repeat_pairs * 2
    expected = 4 + intro_pulses + repeat_pulses
    if len(words) != expected:
        raise ArchiveError(
            f"Pronto header declares {expected - 4} durations, found {len(words) - 4}")
    if intro_pulses + repeat_pulses == 0:
        raise ArchiveError("Pronto contains no waveform durations")
    return words


def parse_pronto(text: str) -> dict:
    """Decode raw Pronto ``0000`` into signed microseconds and section sizes."""
    words = _pronto_words(text)
    divisor = int(words[1], 16)
    intro_pulses = int(words[2], 16) * 2
    repeat_pulses = int(words[3], 16) * 2

    period_us = divisor * 0.241246
    durations = [int(word, 16) for word in words[4:]]
    if any(duration == 0 for duration in durations):
        raise ArchiveError("Pronto waveform durations cannot be zero")
    raw = [max(1, round(duration * period_us)) for duration in durations]
    pulses = [value if index % 2 == 0 else -value for index, value in enumerate(raw)]
    return {
        "carrier_hz": round(1_000_000 / period_us),
        "pulses_us": pulses,
        "sections": {
            "intro_pulses": intro_pulses,
            "repeat_pulses": repeat_pulses,
        },
    }


def _keycode_groups(keycode: str) -> dict[str, list[str]]:
    match = KEYCODE_RE.match(keycode)
    if not match:
        raise ArchiveError("keycode does not have Logitech's G:... group shape")
    return {
        phase: ([] if not match.group(phase) else match.group(phase).split("_"))
        for phase in ("start", "repeat", "finish")
    }


def _code0(command: dict, protocol: dict) -> int:
    field = (protocol.get("keycodeFields") or {}).get("Code0")
    if not isinstance(field, dict):
        raise ArchiveError("portable mapping needs one indexed Code0 field")
    groups = _keycode_groups(command["keycode"])
    sequence = field.get("sequence")
    token_index = field.get("token")
    if sequence not in groups or not isinstance(token_index, int):
        raise ArchiveError("Code0 has an invalid keycode group or token index")
    try:
        token = groups[sequence][token_index]
    except IndexError as exc:
        raise ArchiveError("keycode does not contain the indexed Code0 token") from exc
    segment = str(field.get("segment"))
    if len(token) < 3 or token[0] != segment or token[1].lower() != "x":
        raise ArchiveError(f"Code0 token {token!r} does not name segment {segment!r}")
    try:
        value = int(token[2:], 16)
    except ValueError as exc:
        raise ArchiveError(f"Code0 token {token!r} is not hexadecimal") from exc
    bits = field.get("bits")
    if not isinstance(bits, int) or value >= 1 << bits:
        raise ArchiveError(f"Code0 value does not fit its declared {bits!r}-bit field")
    return value


def _bit_reverse(value: int) -> int:
    return int(f"{value:08b}"[::-1], 2)


def _portable_parameters(value: int, adapter: str) -> dict:
    """Turn an archive Code0 value into one portable protocol's parameters.

    The address-complement check below is *not* what blocks the 441,156 "Toshiba 32 Bit"
    commands that the Harmony 900 cannot transmit - 41% of all its refusals. Those values
    genuinely lack the complement, so they are NEC extended addressing; substituting a
    hardware-anchored `nec-ext` changes nothing, with 22,296 of 40,036 sampled commands
    passing either way.

    The measured blocker is frame *composition*, not protocol identity. Their derived
    Pronto carries the data frame **and one NEC repeat frame** in its intro section
    (`8993, -2235, 579, -96085` after the 68-pulse frame), while a portable `press`
    renders the frame alone - 72 observed pulses against 68 expected, with every timing
    inside tolerance up to that point. Logitech marks these keycodes `sequence: "start"`
    where the working Sony adapters use `"repeat"`. Fix the sequence composition, not the
    complement rule.
    """
    if adapter == "code":
        return {"code": value}
    if value >= 1 << 32:
        raise ArchiveError("NEC-family Code0 value does not fit 32 bits")
    address, check, command, command_check = value.to_bytes(4, "big")
    if command_check != command ^ 0xFF:
        raise ArchiveError("NEC-family command byte has an invalid complement")
    if adapter == "nec-wire":
        if check != address ^ 0xFF:
            raise ArchiveError("NEC address byte has an invalid complement")
    elif adapter == "samsung-wire":
        if check != address:
            raise ArchiveError("Samsung address byte is not repeated")
    else:
        raise ArchiveError(f"unknown portable value adapter {adapter!r}")
    return {
        "address": _bit_reverse(address),
        "command": _bit_reverse(command),
    }


def _segment_id(protocol_name: str, segment_name: str) -> str:
    """The one-character token id Logitech derives from a segment display name."""
    if segment_name == protocol_name:
        return "0"
    marker = f"{protocol_name} KeyCode"
    if segment_name.startswith(marker):
        return segment_name[len(marker):]
    prefix = f"{protocol_name} "
    return segment_name[len(prefix):] if segment_name.startswith(prefix) else segment_name


def _atom_pulses(atoms, label: str) -> list[int]:
    """Logitech typed atoms -> signed emission durations, dropping explicit zero time."""
    if not isinstance(atoms, list):
        raise ArchiveError(f"{label} atoms must be a list")
    pulses = []
    for atom in atoms:
        if not isinstance(atom, dict):
            raise ArchiveError(f"{label} contains a non-object atom")
        kind, value = atom.get("Type"), atom.get("Value")
        if kind not in (0, 1) or isinstance(value, bool) or not isinstance(value, int):
            raise ArchiveError(f"{label} contains an invalid typed duration")
        if value < 0:
            raise ArchiveError(f"{label} contains a negative atom duration")
        if value:
            pulses.append(value if kind == 1 else -value)
    return pulses


def _check_hold_minimum(hold_minimum, label: str) -> None:
    """Reject a `HoldMinimumRepeats` whose value has never been seen.

    Multiplying it into the `hold` sequence asserts that one repeat *cycle* contains N
    frames, and nothing supports that reading. Mapping it onto the portable
    `hold_minimum` is also wrong:
    `hold_minimum` lowers to native Code byte 4, a floor on repeat runs that applies to a
    tap as much as to a held key, and `ir_emit._verify_generic` rejects the result because
    the rendered one-frame press no longer matches the four-frame emission.

    Byte 4 empirically tracks `PressMinimumRepeats` instead - `Sony 12 Bit` declares
    `Press=3, Hold=None` and its flashed Codes carry 3. `HoldMinimumRepeats` sits beside
    `HoldDelay` and reads as hold *policy*, which neither the portable grammar nor the
    firmware's single repeat counter can express as "a floor only while held".

    Every family in the archive as checked out declares it `null`, so there is no evidence
    to settle it with and no output to preserve. Refuse loudly rather than guess: a raw
    database that does populate it should surface here on first contact, not convert
    silently into something plausible and wrong.
    """
    if hold_minimum is None:
        return
    if (isinstance(hold_minimum, bool) or not isinstance(hold_minimum, int)
            or hold_minimum < 0):
        raise ArchiveError(f"{label} has an invalid hold repeat count")
    if hold_minimum > 1:
        raise ArchiveError(
            f"{label} declares HoldMinimumRepeats={hold_minimum}, which has no "
            "established meaning: no family in the reference archive populates it, and "
            "it does not map to the firmware's single repeat counter. Please open an "
            "Issue with this protocol record so it can be settled from evidence")


def _portable_protocol(source_record: dict) -> tuple[dict, dict]:
    """Mechanically lower one complete Logitech definition plus private decode layout."""
    name = source_record.get("name")
    definition = source_record.get("definition")
    if not isinstance(name, str) or not name or not isinstance(definition, dict):
        raise ArchiveError("source protocol has no complete definition")
    carrier = definition.get("CarrierFrequency", source_record.get("carrierHz"))
    if isinstance(carrier, bool) or not isinstance(carrier, int) or carrier < 0:
        raise ArchiveError(f"protocol {name!r} has an invalid carrier frequency")

    bursts: dict[str, list[int]] = {}
    alphabets: dict[str, dict] = {}
    parameters: dict[str, dict] = {}
    frames: dict[str, dict] = {}
    state: dict[str, dict] = {}
    frame_by_name: dict[str, str] = {}
    frame_by_id: dict[str, str] = {}
    payload_meta: dict[str, dict] = {}

    def add_burst(burst_name: str, atoms, label: str) -> str | None:
        pulses = _atom_pulses(atoms, label)
        if not pulses:
            return None
        bursts[burst_name] = pulses
        return burst_name

    source_segments = [
        *(('encoded', segment) for segment in definition.get("IRSegments") or []),
        *(('fixed', segment) for segment in definition.get("CodeSegments") or []),
    ]
    for index, (kind, segment) in enumerate(source_segments):
        if not isinstance(segment, dict) or not isinstance(segment.get("Name"), str):
            raise ArchiveError(f"protocol {name!r} contains an incomplete segment")
        frame_name = f"segment-{index}"
        source_name = segment["Name"]
        source_id = _segment_id(name, source_name)
        if source_name in frame_by_name or source_id in frame_by_id:
            raise ArchiveError(f"protocol {name!r} contains duplicate segment identity")
        frame_by_name[source_name] = frame_name
        frame_by_id[source_id] = frame_name
        frame_segments = []
        local_parameters = {}

        if kind == "fixed":
            fixed = add_burst(
                f"{frame_name}-fixed", segment.get("Atoms") or [],
                f"protocol {name!r} fixed segment {source_name!r}")
            if fixed:
                frame_segments.append({"burst": fixed})
        else:
            header = add_burst(
                f"{frame_name}-header", segment.get("Header") or [],
                f"protocol {name!r} header {source_name!r}")
            if header:
                frame_segments.append({"burst": header})
            payload = segment.get("Payload")
            if payload is not None:
                if not isinstance(payload, dict):
                    raise ArchiveError(f"protocol {name!r} has an invalid payload")
                encodings = payload.get("Encodings") or []
                count = len(encodings)
                width = (count - 1).bit_length() if count else 0
                if count < 2 or count != 1 << width or width > 8:
                    raise ArchiveError(
                        f"protocol {name!r} has a non-power-of-two symbol alphabet")
                alphabet_name = f"alphabet-{index}"
                symbols = {}
                for encoding in encodings:
                    if not isinstance(encoding, dict):
                        raise ArchiveError(f"protocol {name!r} has an invalid encoding")
                    symbol_id = encoding.get("BitType")
                    if (isinstance(symbol_id, bool) or not isinstance(symbol_id, int)
                            or not 0 <= symbol_id < count):
                        raise ArchiveError(f"protocol {name!r} has an invalid symbol id")
                    symbol = add_burst(
                        f"{frame_name}-symbol-{symbol_id}", encoding.get("Atoms") or [],
                        f"protocol {name!r} symbol {symbol_id}")
                    if symbol is None:
                        raise ArchiveError(f"protocol {name!r} has an empty symbol encoding")
                    symbols[format(symbol_id, f"0{width}b")] = symbol
                alphabets[alphabet_name] = {
                    "bits_per_symbol": width,
                    "symbols": symbols,
                }
                units = payload.get("NumberOfBits")
                if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
                    raise ArchiveError(f"protocol {name!r} has an invalid payload width")
                encoding_type = payload.get("EncodingType")
                payload_bits = units * width if encoding_type in (2, 3) else units
                local_parameters["payload"] = {"bits": payload_bits}
                payload_meta[frame_name] = {
                    "encoding_type": encoding_type,
                    "units": units,
                    "symbol_bits": width,
                    "payload_bits": payload_bits,
                }
                field = {
                    "field": "payload", "bits": payload_bits,
                    "order": "msb", "alphabet": alphabet_name,
                }
                toggle = payload.get("ToggleBit")
                if toggle is None:
                    frame_segments.append(field)
                else:
                    if (width != 1 or isinstance(toggle, bool)
                            or not isinstance(toggle, int) or not 0 <= toggle < payload_bits):
                        raise ArchiveError(f"protocol {name!r} has an invalid toggle position")
                    if toggle:
                        frame_segments.append({
                            **field,
                            "offset": payload_bits - toggle,
                            "bits": toggle,
                        })
                    state["toggle"] = {
                        "kind": "toggle", "initial": 0, "advance": "press"}
                    frame_segments.append({
                        "state": "toggle", "order": "msb", "alphabet": alphabet_name})
                    trailing = payload_bits - toggle - 1
                    if trailing:
                        frame_segments.append({
                            **field, "offset": 0, "bits": trailing})
            trailer = add_burst(
                f"{frame_name}-trailer", segment.get("Trailer") or [],
                f"protocol {name!r} trailer {source_name!r}")
            if trailer:
                frame_segments.append({"burst": trailer})

        if not frame_segments:
            raise ArchiveError(f"protocol {name!r} contains an empty frame")
        frame = {"segments": frame_segments}
        if local_parameters:
            frame["parameters"] = local_parameters
        total = segment.get("TotalLength")
        if total:
            if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
                raise ArchiveError(f"protocol {name!r} has an invalid total length")
            frame["minimum_period_us"] = total
        frames[frame_name] = frame

    if not frames:
        raise ArchiveError(f"protocol {name!r} has no IR frames")

    occurrence_fields = {}
    for field_name, field in (source_record.get("keycodeFields") or {}).items():
        if not isinstance(field_name, str) or not isinstance(field, dict):
            raise ArchiveError(f"protocol {name!r} has an invalid keycode field")
        frame_name = frame_by_id.get(str(field.get("segment")))
        meta = payload_meta.get(frame_name)
        sequence, token = field.get("sequence"), field.get("token")
        if (meta is None or sequence not in ("start", "repeat", "finish")
                or isinstance(token, bool) or not isinstance(token, int) or token < 0):
            raise ArchiveError(f"protocol {name!r} has an invalid keycode field mapping")
        width = meta["payload_bits"]
        existing = parameters.get(field_name)
        if existing is not None and existing["bits"] != width:
            raise ArchiveError(f"protocol {name!r} reuses a field at different widths")
        parameters[field_name] = {"bits": width}
        key = (sequence, token, frame_name)
        if key in occurrence_fields:
            raise ArchiveError(f"protocol {name!r} maps two fields to one occurrence")
        occurrence_fields[key] = field_name

    keycode = definition.get("KeyCode") or {}

    def sequence(source_name: str) -> list[dict]:
        phase = source_name.lower()
        items = []
        for token, entry in enumerate(keycode.get(source_name) or []):
            if not isinstance(entry, dict):
                raise ArchiveError(f"protocol {name!r} has an invalid sequence item")
            frame_name = frame_by_name.get(entry.get("SegmentName"))
            if frame_name is None:
                raise ArchiveError(f"protocol {name!r} names an unknown segment")
            item = {"frame": frame_name}
            if frames[frame_name].get("parameters"):
                field_name = occurrence_fields.get((phase, token, frame_name))
                if field_name is None:
                    raise ArchiveError(
                        f"protocol {name!r} has a payload occurrence with no field")
                item["bind"] = {"payload": field_name}
            items.append(item)
        return items

    start = sequence("Start")
    repeat = sequence("Repeat")
    finish = sequence("Finish")
    minimum = definition.get("PressMinimumRepeats")
    if minimum is not None and (
            isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0):
        raise ArchiveError(f"protocol {name!r} has an invalid press repeat count")
    if start:
        press = start + repeat * (1 if minimum is None else minimum)
    else:
        press = repeat * max(1, minimum or 1)
    if not press:
        raise ArchiveError(f"protocol {name!r} has no press sequence")
    _check_hold_minimum(definition.get("HoldMinimumRepeats"), f"protocol {name!r}")
    # One repeat cycle, exactly as declared. `PressMinimumRepeats` above stays unrolled
    # and is not the same construct: `press` is Pronto's one-time burst, which genuinely
    # does contain those frames - `_portable_candidate` compares it against
    # `command["pronto"]` that way, and the archive-wide agreement figure rests on it.
    hold = list(repeat)

    modulation = ({"kind": "carrier", "carrier_hz": carrier}
                  if carrier else {"kind": "unmodulated"})
    spec = {
        "schema": ir_protocol.SCHEMA,
        "id": "pending",
        "name": f"{name} (generic payload)",
        "modulation": modulation,
        "parameters": parameters,
        "bursts": bursts,
        "alphabets": alphabets,
        "frames": frames,
        "transmission": {"press": press, "hold": hold, "release": finish},
        "provenance": {
            "kind": "mechanically-converted-protocol",
            "source": "Logitech Harmony IR archive",
            "logitech_protocol_id": source_record.get("logitechProtocolId"),
            "source_name": name,
            "field_semantics": "generic materialized payload; address/checksum names unknown",
        },
    }
    if state:
        spec["state"] = state
    ir_protocol.validate(spec)
    source_id = source_record.get("logitechProtocolId")
    identity = str(source_id) if source_id is not None else digest(source_record)[:8]
    spec["id"] = f"logitech-{identity}-{ir_protocol.semantic_fingerprint(spec)}"
    ir_protocol.validate(spec)
    return spec, {
        "frame_by_name": frame_by_name,
        "frame_by_id": frame_by_id,
        "payload_meta": payload_meta,
        "occurrence_fields": occurrence_fields,
    }


def portable_protocol(source_record: dict) -> dict:
    """Convert one complete source protocol without guessing semantic field names."""
    return _portable_protocol(source_record)[0]


def _payload_value(token: str, segment_id: str, meta: dict, label: str) -> str:
    prefix = f"{segment_id}x"
    if len(token) <= len(prefix) or token[:len(prefix)].lower() != prefix.lower():
        raise ArchiveError(
            f"{label} token {token!r} does not name segment {segment_id!r}")
    digits = token[len(prefix):]
    try:
        if meta["encoding_type"] in (2, 3):
            symbols = [int(digit, 16) for digit in digits]
            if any(symbol >= 1 << meta["symbol_bits"] for symbol in symbols):
                raise ArchiveError(f"{label} contains a symbol outside its alphabet")
            units = meta["units"]
            symbols = ([0] * max(0, units - len(symbols)) + symbols)[-units:]
            value = 0
            for symbol in symbols:
                value = value << meta["symbol_bits"] | symbol
        else:
            value = int(digits, 16) & ((1 << meta["payload_bits"]) - 1)
    except ValueError as exc:
        raise ArchiveError(f"{label} is not hexadecimal") from exc
    width = meta["payload_bits"]
    return f"0x{value:0{(width + 3) // 4}X}"


def _generic_parameters(command: dict, protocol: dict, layout: dict) -> dict:
    groups = _keycode_groups(command["keycode"])
    values = {}
    for field_name, field in (protocol.get("keycodeFields") or {}).items():
        sequence, token_index = field.get("sequence"), field.get("token")
        if sequence not in groups or not isinstance(token_index, int):
            raise ArchiveError(f"field {field_name!r} has an invalid keycode location")
        try:
            token = groups[sequence][token_index]
        except IndexError as exc:
            raise ArchiveError(
                f"keycode does not contain field {field_name!r}") from exc
        segment_id = str(field.get("segment"))
        frame_name = layout["frame_by_id"].get(segment_id)
        meta = layout["payload_meta"].get(frame_name)
        if meta is None:
            raise ArchiveError(f"field {field_name!r} does not name an encoded segment")
        values[field_name] = _payload_value(
            token, segment_id, meta, f"field {field_name!r}")
    return values


def _command_transmission(command: dict, protocol: dict, spec: dict,
                          layout: dict) -> tuple[dict, dict[str, list[dict]]]:
    """Materialize an exceptional command's own frame recipe and occurrence values."""
    groups = _keycode_groups(command["keycode"])
    identities = sorted(layout["frame_by_id"], key=len, reverse=True)

    def item(token: str) -> dict:
        exact = layout["frame_by_id"].get(token)
        if exact is not None and not (spec["frames"][exact].get("parameters") or {}):
            return {"frame": exact}
        segment_id = next(
            (identity for identity in identities
             if token[:len(identity) + 1].lower() == f"{identity}x".lower()),
            None,
        )
        if segment_id is None:
            raise ArchiveError(f"keycode token {token!r} names no protocol segment")
        frame_name = layout["frame_by_id"][segment_id]
        local = spec["frames"][frame_name].get("parameters") or {}
        if set(local) != {"payload"}:
            raise ArchiveError(
                f"keycode token {token!r} cannot supply frame {frame_name!r}")
        meta = layout["payload_meta"].get(frame_name)
        if meta is None:
            raise ArchiveError(f"keycode token {token!r} names no encoded payload")
        return {
            "frame": frame_name,
            "arguments": {
                "payload": _payload_value(token, segment_id, meta, "keycode payload")},
        }

    source = {phase: [item(token) for token in groups[phase]]
              for phase in ("start", "repeat", "finish")}
    definition = protocol["definition"]
    minimum = definition.get("PressMinimumRepeats")
    if minimum is not None and (
            isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0):
        raise ArchiveError("protocol has an invalid press repeat count")
    if source["start"]:
        press = source["start"] + source["repeat"] * (1 if minimum is None else minimum)
    else:
        press = source["repeat"] * max(1, minimum or 1)
    if not press:
        raise ArchiveError("command keycode has no press sequence")
    _check_hold_minimum(definition.get("HoldMinimumRepeats"), "protocol")
    hold = list(source["repeat"])
    return ({"press": press, "hold": hold, "release": source["finish"]}, source)


def _append_pulses(out: list[int], pulses) -> None:
    for pulse in pulses:
        if not pulse:
            continue
        if out and (out[-1] > 0) == (pulse > 0):
            out[-1] += pulse
        else:
            out.append(pulse)


def _as_sections(start: list[int], repeat: list[int],
                 finish: list[int]) -> list[list[int]]:
    """Fold a source lifecycle into the intro/repeat pair a Pronto waveform has.

    Pronto carries two sections; the archive carries three. Start and Finish therefore
    join the first pass to form the intro, and only Repeat stands alone. Both section
    builders resolve their frames differently and agree from here on.
    """
    if start or finish:
        intro: list[int] = []
        for section in (start, repeat, finish):
            _append_pulses(intro, section)
        return [section for section in (intro, repeat) if section]
    return [repeat] if repeat else []


def _generic_expected_sections(protocol: dict, spec: ir_protocol.Protocol, layout: dict,
                               parameters: dict, state: dict) -> list[list[int]]:
    keycode = protocol["definition"].get("KeyCode") or {}
    frames = spec.raw["frames"]

    def render(source_name: str) -> list[int]:
        phase = source_name.lower()
        pulses = []
        for token, entry in enumerate(keycode.get(source_name) or []):
            frame_name = layout["frame_by_name"].get(entry.get("SegmentName"))
            if frame_name is None:
                raise ArchiveError("source sequence names an unknown portable frame")
            bindings = None
            if frames[frame_name].get("parameters"):
                field_name = layout["occurrence_fields"].get((phase, token, frame_name))
                if field_name is None:
                    raise ArchiveError("source payload occurrence has no portable binding")
                bindings = {"payload": field_name}
            _append_pulses(
                pulses,
                spec.frame(parameters, frame_name, state=state, bindings=bindings),
            )
        return pulses

    start, repeat, finish = (render(name) for name in ("Start", "Repeat", "Finish"))
    return _as_sections(start, repeat, finish)


def _command_expected_sections(spec: ir_protocol.Protocol,
                               source: dict[str, list[dict]],
                               state: dict) -> list[list[int]]:
    def render(items: list[dict]) -> list[int]:
        pulses = []
        for item in items:
            _append_pulses(
                pulses,
                spec.frame({}, item["frame"], state=state,
                           arguments=item.get("arguments")),
            )
        return pulses

    start, repeat, finish = (render(source[phase])
                             for phase in ("start", "repeat", "finish"))
    return _as_sections(start, repeat, finish)


def _generic_candidate(command: dict, protocol: dict, generic=None) -> _Candidate:
    try:
        source_spec, layout = generic or _portable_protocol(protocol)
        # Validated once here rather than on every frame this command renders: the two
        # section builders below each walk the lifecycle twice when the protocol has a
        # toggle, and each frame used to re-check the whole definition.
        spec = ir_protocol.Protocol(source_spec)
        observed = parse_pronto(command["pronto"])
        states = ({"toggle": 0}, {"toggle": 1}) if source_spec.get("state") else ({},)
        failures = []
        try:
            parameters = _generic_parameters(command, protocol, layout)
            signal = ir_signal.protocol_signal(
                spec.id, parameters, name=command.get("name", ""),
                provenance={
                    "kind": "logitech-harmony-ir-archive",
                    "protocol": protocol["name"],
                    "logitech_protocol_id": protocol.get("logitechProtocolId"),
                    "keycode": command["keycode"],
                    "field_semantics": "generic materialized payload",
                },
            )
            for state in states:
                expected = _generic_expected_sections(
                    protocol, spec, layout, parameters, state)
                agreed, reason = _waveforms_agree(
                    expected, observed, spec.modulation.get("carrier_hz", 0))
                if agreed:
                    return _Candidate(signal, reason)
                failures.append(reason)
        except (ArchiveError, KeyError, LookupError, TypeError, ValueError) as exc:
            failures.append(str(exc))

        transmission, source = _command_transmission(
            command, protocol, source_spec, layout)
        signal = ir_signal.protocol_signal(
            spec.id, {}, name=command.get("name", ""), transmission=transmission,
            provenance={
                "kind": "logitech-harmony-ir-archive",
                "protocol": protocol["name"],
                "logitech_protocol_id": protocol.get("logitechProtocolId"),
                "keycode": command["keycode"],
                "field_semantics": "generic occurrence payloads",
            },
        )
        for state in states:
            expected = _command_expected_sections(spec, source, state)
            agreed, reason = _waveforms_agree(
                expected, observed, spec.modulation.get("carrier_hz", 0))
            if agreed:
                return _Candidate(signal, reason)
            failures.append(reason)
        return _Candidate(None, failures[-1])
    except (ArchiveError, KeyError, LookupError, TypeError, ValueError) as exc:
        return _Candidate(None, str(exc))


def _sections(waveform: dict) -> list[list[int]]:
    intro = waveform["sections"]["intro_pulses"]
    repeat = waveform["sections"]["repeat_pulses"]
    pulses = waveform["pulses_us"]
    return [section for section in (pulses[:intro], pulses[intro:intro + repeat]) if section]


def _waveforms_agree(expected: list[list[int]], observed: dict,
                     carrier_hz: int) -> tuple[bool, str]:
    actual = _sections(observed)
    if len(expected) != len(actual):
        return False, f"expected {len(expected)} waveform sections, Pronto has {len(actual)}"
    observed_carrier = observed["carrier_hz"]
    expected_divisor = (round(1_000_000 / (carrier_hz * 0.241246))
                        if carrier_hz > 0 else None)
    observed_divisor = (round(1_000_000 / (observed_carrier * 0.241246))
                        if observed_carrier > 0 else None)
    if expected_divisor != observed_divisor:
        return False, "portable and Pronto carrier frequencies differ"
    for section_index, (wanted, got) in enumerate(zip(expected, actual, strict=True)):
        # A Pronto repeat section cannot begin with silence. Logitech omits a protocol's
        # leading repeat delay from the derived Pronto while retaining it in the source
        # definition; compare the emitted part of that section.
        if section_index and wanted[0] < 0 and got[0] > 0:
            wanted = wanted[1:]
        # Pronto stores mark/space pairs. Encoders therefore append one carrier-period
        # silence when the real waveform ends on a mark; it is serialization padding,
        # not a protocol pulse.
        if (len(got) == len(wanted) + 1 and got[-1] < 0
                and abs(got[-1]) <= 100):
            got = got[:-1]
        if len(wanted) != len(got):
            return False, (
                f"section {section_index} has {len(got)} pulses; expected {len(wanted)}")
        for pulse_index, (left, right) in enumerate(zip(wanted, got, strict=True)):
            if (left > 0) != (right > 0):
                return False, f"section {section_index} pulse {pulse_index} changes level"
            if abs(abs(left) - abs(right)) > max(50, abs(left) // 500):
                return False, f"section {section_index} pulse {pulse_index} differs in timing"
    return True, "portable waveform agrees with source Pronto within quantization"


def _catalogue(library) -> ir_protocol.Catalog:
    """A catalogue, from one already built or from a mapping or directory.

    Reading a library is the expensive step, so the audit and the codeset converter build
    theirs once and pass it down. Anything else is accepted and read here.
    """
    if isinstance(library, ir_protocol.Catalog):
        return library
    return ir_protocol.Catalog(library)


def _portable_candidate(command: dict, protocol: dict,
                        library: ir_protocol.Catalog) -> _Candidate:
    mapping = PORTABLE_PROTOCOLS.get(protocol.get("name"))
    if mapping is None:
        return _Candidate(None, "no reviewed portable adapter for this protocol")
    source_id, portable_id, single_frame, adapter = mapping
    if protocol.get("logitechProtocolId") != source_id:
        return _Candidate(None, "protocol name matches, but its Logitech id does not")
    try:
        value = _code0(command, protocol)
        definition = library[portable_id]
        parameters = _portable_parameters(value, adapter)
        signal = ir_signal.protocol_signal(
            portable_id,
            parameters,
            name=command.get("name", ""),
            provenance={
                "kind": "logitech-harmony-ir-archive",
                "protocol": protocol["name"],
                "logitech_protocol_id": source_id,
                "keycode": command["keycode"],
            },
        )
        if single_frame:
            state = {"toggle": 0} if definition.raw.get("state") else None
            expected = [definition.frame(parameters, single_frame, state=state)]
        else:
            press, state = definition.transmission(parameters, "press")
            hold, _state = definition.transmission(parameters, "hold", state=state)
            expected = [section for section in (press, hold) if section]
        observed = parse_pronto(command["pronto"])
        agreed, reason = _waveforms_agree(
            expected, observed, definition.modulation["carrier_hz"])
        return _Candidate(signal if agreed else None, reason)
    except (ArchiveError, LookupError, ValueError) as exc:
        return _Candidate(None, str(exc))


def analyse_command(command: dict, protocol: dict, *, generic=None,
                    library=None) -> Verdict:
    """Classify one command and return only a Pronto-proven portable signal."""
    if not isinstance(command, dict):
        return Verdict("corrupt-source", "command is not an object")
    required = {"name", "protocol", "keycode"}
    missing = required - set(command)
    if missing:
        return Verdict("corrupt-source", f"command is missing {sorted(missing)}")
    if command["protocol"] != protocol.get("name"):
        return Verdict("corrupt-source", "command and resolved protocol names differ")
    pronto = command.get("pronto")
    if not pronto:
        if command["protocol"] in NON_IR_PROTOCOLS:
            return Verdict("non-ir", "source protocol is HID or network control")
        if command["protocol"] in OUT_OF_IR_RANGE_PROTOCOLS:
            return Verdict(
                "target-incapable", "433 MHz carrier is outside infrared hardware")
        return Verdict("corrupt-source", "infrared command has no derived Pronto waveform")
    try:
        words = _pronto_words(pronto)
        if command.get("prontoRepeat"):
            standalone = _pronto_words(command["prontoRepeat"])
            intro_pulses = int(words[2], 16) * 2
            repeat_pulses = int(words[3], 16) * 2
            if (int(standalone[1], 16) != int(words[1], 16)
                    or int(standalone[2], 16) != 0
                    or int(standalone[3], 16) * 2 != repeat_pulses
                    or standalone[4:] != words[4 + intro_pulses:]):
                return Verdict(
                    "corrupt-source", "prontoRepeat disagrees with Pronto repeat")
    except ArchiveError as exc:
        return Verdict("corrupt-source", str(exc))

    portable = _portable_candidate(command, protocol, _catalogue(library))
    if portable.signal is not None:
        return Verdict(
            "semantic-with-pronto-agreement", portable.reason, portable.signal)
    lowered = _generic_candidate(command, protocol, generic)
    if lowered.signal is not None:
        return Verdict("portable-with-pronto-agreement", lowered.reason, lowered.signal)
    return Verdict("waveform-only", lowered.reason)


def protocol_record(relative: str, source_record: dict, *,
                    library=None) -> dict:
    """Retain source evidence plus reviewed and/or mechanical portable meaning."""
    record = {
        "schema": PROTOCOL_RECORD_SCHEMA,
        "id": digest(source_record),
        "name": source_record.get("name"),
        "source": _source(relative, source_record),
    }
    mapping = PORTABLE_PROTOCOLS.get(source_record.get("name"))
    if mapping and source_record.get("logitechProtocolId") == mapping[0]:
        record["portable"] = _catalogue(library)[mapping[1]].raw
        record["portable_status"] = "reviewed"
        try:
            generic, _layout = _portable_protocol(source_record)
        except ArchiveError:
            pass
        else:
            record["generic_portable"] = generic
    else:
        try:
            record["portable"] = portable_protocol(source_record)
        except ArchiveError as exc:
            record["portable_status"] = "unavailable"
            record["portable_reason"] = str(exc)
        else:
            record["portable_status"] = "generic"
    return record


def protocol_path(record: dict) -> str:
    identity = record["id"]
    return f"protocols/{identity[:2]}/{identity}.json"


def transform_codeset(archive: Archive, relative: str, source_record: dict, *,
                      library=None) -> tuple[dict, dict[str, dict]]:
    """Convert one shared code set without expanding any referring devices."""
    commands = source_record.get("commands")
    if not isinstance(commands, list):
        raise ArchiveError(f"codeset {relative} has no commands list")
    portable_library = _catalogue(library)
    protocols = {}
    generics = {}
    converted = []
    for command in commands:
        protocol_relative, source_protocol = archive.protocol(command.get("protocol"))
        wrapped = protocol_record(
            protocol_relative, source_protocol, library=portable_library)
        reference = protocol_path(wrapped)
        if reference not in protocols:
            protocols[reference] = wrapped
            try:
                generics[reference] = _portable_protocol(source_protocol)
            except ArchiveError:
                generics[reference] = None
        verdict = analyse_command(
            command, source_protocol, generic=generics[reference],
            library=portable_library)
        item = {
            "name": command.get("name"),
            "classification": verdict.classification,
            "reason": verdict.reason,
            "protocol": reference,
            "source": _source(relative, command),
        }
        if verdict.signal is not None:
            item["signal"] = verdict.signal
        elif command.get("pronto"):
            parsed = parse_pronto(command["pronto"])
            item["signal"] = ir_signal.waveform(
                parsed["pulses_us"],
                name=command.get("name", ""),
                carrier_hz=parsed["carrier_hz"],
                sections=parsed["sections"],
                provenance={
                    "kind": "derived-pronto",
                    "source_keycode": command.get("keycode"),
                },
            )
        converted.append(item)
    return ({
        "schema": CODESET_SCHEMA,
        "id": Path(relative).stem,
        "commands": converted,
        "source": _source(relative, source_record),
    }, protocols)


def device_path(source_record: dict) -> str:
    identity = str(source_record["globalDeviceId"])
    shard = hashlib.sha256(identity.encode("ascii")).hexdigest()[:2]
    return f"devices/{shard}/{identity}.json"


def device_record(relative: str, source_record: dict) -> dict:
    """Convert catalogue identity while retaining its shared code-set pointer."""
    record = {
        "schema": DEVICE_SCHEMA,
        "id": f"logitech:{source_record['globalDeviceId']}",
        "manufacturer": source_record["manufacturer"],
        "model": source_record["model"],
        "device_type": source_record["deviceType"],
        "codeset": source_record.get("codeset"),
        "source": _source(relative, source_record),
    }
    # Archive schema 2 publishes how to *drive* a device, not just what to send. Carried
    # verbatim under one key: these are Logitech's observations about the appliance, and
    # every consumer of them is free to model as much as it can. Absent-never-null
    # upstream, so a missing block means "not published", never "empty".
    control = {key: source_record[key] for key in
               ("timing", "power", "inputs", "channelTuning", "states")
               if key in source_record}
    if control:
        record["control"] = control
    return record


def transform_device(archive: Archive, relative: str, *,
                     library=None) -> tuple[dict, dict | None,
                                                           dict[str, dict]]:
    """Convert one catalogue device and its one shared code-set dependency."""
    source_device = archive.device(relative)
    codeset_relative = source_device.get("codeset")
    codeset = None
    protocols = {}
    if codeset_relative:
        source_codeset = archive.read_json(codeset_relative)
        codeset, protocols = transform_codeset(
            archive, codeset_relative, source_codeset, library=library)
    device = device_record(relative, source_device)
    return device, codeset, protocols


class _Reproduction:
    """Ask one remote backend what it could transmit, per resolved lifecycle.

    A corpus classification says whether a command fits the portable interchange model.
    That is not the same question as whether a user's remote can send it, and reporting
    only the first number has already misled this project's own roadmap: the archive is
    99.99% representable and the Harmony 900 refuses about half of it, because a frozen
    waveform cannot own a distinct hold frame, sender state or a release emission.

    The two numbers must therefore be produced by the same pass. This class is the
    remote-facing half. It resolves the backend through ``RemoteProfile`` exactly like
    the builder does, so the audit never imports a concrete backend.

    **Evaluated once per protocol and command-level transmission recipe, then weighted by
    command count.** Parameter values normally change symbols rather than compiler
    capability, while an exceptional Logitech keycode may replace the lifecycle and use
    otherwise unreferenced frames. Those recipes must not inherit the default lifecycle's
    verdict. The one remaining approximation is a frame-period lead-out sitting exactly
    on the 15-bit ``SsIr`` boundary; do not describe this as a per-command exhaustive
    measurement.
    """

    def __init__(self, profile):
        from . import backends
        self.profile = profile
        self.backend = backends.for_profile(profile)
        self.strategies = Counter()
        self.reasons = Counter()
        self.protocols: dict[str, Counter] = {}
        self._verdicts: dict[tuple[str, str], tuple[str, str]] = {}

    def _verdict(self, signal: dict, generic) -> tuple[str, str]:
        protocol_id = signal.get("protocol")
        if protocol_id is None:
            return "waveform", "recorded waveform"
        lifecycle_key = digest(signal.get("transmission") or {})
        key = (protocol_id, lifecycle_key)
        cached = self._verdicts.get(key)
        if cached is not None:
            return cached
        # A generically lowered protocol is not in the shipped library; it travels with
        # the project instead, so hand the backend the same definition a build would get.
        library = ir_protocol.LIBRARY
        if generic is not None and generic[0].get("id") == protocol_id:
            library = {protocol_id: generic[0]}
        try:
            answer = self.backend.capability(signal, self.profile, library=library)
            verdict = (answer.get("strategy") or "unsupported",
                       str(answer.get("reason") or ""))
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            verdict = ("unsupported", str(exc))
        self._verdicts[key] = verdict
        return verdict

    def record(self, signal: dict | None, source_protocol_name: str, generic) -> None:
        if signal is None:
            strategy, reason = "not-portable", "no portable signal to lower"
        else:
            strategy, reason = self._verdict(signal, generic)
        self.strategies[strategy] += 1
        self.reasons[reason] += 1
        self.protocols.setdefault(source_protocol_name, Counter())[strategy] += 1

    def state(self) -> dict:
        return {
            "remote": self.profile.model,
            "backend": (self.profile.infrared or {}).get("backend"),
            "evaluated": (
                "once per protocol and command transmission recipe, weighted by "
                "command count"),
            "strategies": dict(sorted(self.strategies.items())),
            "reasons": dict(sorted(self.reasons.items())),
            "protocols": {name: dict(sorted(counts.items()))
                          for name, counts in sorted(self.protocols.items())},
        }

    def load(self, saved: dict) -> None:
        self.strategies = Counter(saved.get("strategies") or {})
        self.reasons = Counter(saved.get("reasons") or {})
        self.protocols = {name: Counter(counts)
                          for name, counts in (saved.get("protocols") or {}).items()}


def new_audit(archive: Archive, *, revision: str | None = None) -> dict:
    source = {
        "kind": "logitech-harmony-ir-archive",
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "manifest_sha256": digest(archive.manifest),
        "generated": archive.manifest.get("generated"),
    }
    if revision:
        source["revision"] = revision
    return {
        "schema": CORPUS_SCHEMA,
        "source": source,
        "processed": {"codesets": 0, "unique_commands": 0},
        "classifications": {},
        "reasons": {},
        "protocols": {},
        "waveform_fallbacks": {"reasons": {}, "protocols": {}},
        "last_codeset": None,
        "complete": False,
    }


def audit(archive: Archive, *, previous: dict | None = None, limit: int | None = None,
          revision: str | None = None, library=None,
          checkpoint=None, checkpoint_every: int = 100, reproduce=None) -> dict:
    """Audit unique code sets, optionally resuming after ``last_codeset``.

    ``checkpoint`` is called periodically with the serializable state, allowing the CLI
    to persist progress without coupling this format module to a destination policy.

    ``reproduce`` is an optional ``RemoteProfile``. Supplying one adds a second, separate
    measurement: how much of what the interchange model *can represent* that remote can
    actually *transmit*. Keep both in one report - see :class:`_Reproduction`.
    """
    state = previous if previous is not None else new_audit(archive, revision=revision)
    expected_fingerprint = digest(archive.manifest)
    if state.get("source", {}).get("manifest_sha256") != expected_fingerprint:
        raise ArchiveError("audit state belongs to a different archive manifest")
    classifications = Counter(state.get("classifications") or {})
    reasons = Counter(state.get("reasons") or {})
    protocols = Counter(state.get("protocols") or {})
    fallback = state.get("waveform_fallbacks") or {}
    fallback_reasons = Counter(fallback.get("reasons") or {})
    fallback_protocols = Counter(fallback.get("protocols") or {})
    conversion_refusals = Counter(state.get("protocol_conversion_refusals") or {})
    generic_cache = {}
    portable_library = _catalogue(library)
    reproduction = _Reproduction(reproduce) if reproduce is not None else None
    if reproduction is not None and state.get("reproduction"):
        reproduction.load(state["reproduction"])
    last = state.get("last_codeset")
    started = last is None
    processed_now = 0

    for relative, codeset in archive.iter_codesets():
        if not started:
            if relative == last:
                started = True
            continue
        if limit is not None and processed_now >= limit:
            break
        commands = codeset.get("commands")
        if not isinstance(commands, list):
            classifications["corrupt-source"] += 1
            reasons["codeset has no commands list"] += 1
            command_count = 1
        else:
            command_count = len(commands)
            for command in commands:
                try:
                    _relative, source_protocol = archive.protocol(command.get("protocol"))
                    protocol_name = source_protocol.get("name")
                    if protocol_name not in generic_cache:
                        try:
                            generic_cache[protocol_name] = _portable_protocol(source_protocol)
                        except ArchiveError as exc:
                            generic_cache[protocol_name] = None
                            # A family that will not convert falls back to whatever else
                            # can classify the command, which loses why. Record it: a
                            # refusal added for a construct the reference archive never
                            # populates only earns its keep if it is visible the first
                            # time a fuller database does populate it.
                            conversion_refusals[f"{protocol_name}: {exc}"] += 1
                    verdict = analyse_command(
                        command, source_protocol, generic=generic_cache[protocol_name],
                        library=portable_library)
                except ArchiveError as exc:
                    verdict = Verdict("corrupt-source", str(exc))
                    protocol_name = command.get("protocol", "<missing>")
                classifications[verdict.classification] += 1
                reasons[verdict.reason] += 1
                protocols[command.get("protocol", "<missing>")] += 1
                if verdict.classification == "waveform-only":
                    fallback_reasons[verdict.reason] += 1
                    fallback_protocols[command.get("protocol", "<missing>")] += 1
                if reproduction is not None:
                    reproduction.record(
                        verdict.signal, protocol_name or "<missing>",
                        generic_cache.get(protocol_name))
        state["processed"]["codesets"] += 1
        state["processed"]["unique_commands"] += command_count
        state["last_codeset"] = relative
        processed_now += 1
        state["classifications"] = dict(sorted(classifications.items()))
        state["reasons"] = dict(sorted(reasons.items()))
        state["protocol_conversion_refusals"] = dict(sorted(conversion_refusals.items()))
        state["protocols"] = dict(sorted(protocols.items()))
        state["waveform_fallbacks"] = {
            "reasons": dict(sorted(fallback_reasons.items())),
            "protocols": dict(sorted(fallback_protocols.items())),
        }
        if reproduction is not None:
            state["reproduction"] = reproduction.state()
        if checkpoint and processed_now % checkpoint_every == 0:
            checkpoint(state)

    total_codesets = archive.manifest.get("counts", {}).get("codesets")
    state["complete"] = state["processed"]["codesets"] == total_codesets
    if state["complete"]:
        state["count_agreement"] = {
            "codesets": state["processed"]["codesets"] == total_codesets,
            "unique_commands_classified": sum(classifications.values())
            == state["processed"]["unique_commands"],
        }
        state["source_expanded_counts"] = archive.manifest.get("counts", {})
    if checkpoint:
        checkpoint(state)
    return state
