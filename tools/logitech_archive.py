#!/usr/bin/env python3
"""Audit or convert a user-supplied Logitech Harmony IR archive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afterglow import logitech_archive, remotes  # noqa: E402


def _write_json(path: Path, value: dict, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    kwargs = ({"ensure_ascii": False, "separators": (",", ":")}
              if compact else {"ensure_ascii": False, "indent": 2})
    temporary.write_text(json.dumps(value, **kwargs) + "\n", encoding="utf-8")
    temporary.replace(path)


def _revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _source_revision(archive: logitech_archive.Archive) -> str | None:
    return archive.revision or _revision(archive.root)


def _convert_device(args, archive: logitech_archive.Archive) -> int:
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {output}")
    output.mkdir(parents=True)
    device, codeset, protocols = logitech_archive.transform_device(
        archive, args.device)
    device_relative = logitech_archive.device_path(device["source"]["record"])
    _write_json(output / device_relative, device, compact=args.compact)
    if codeset is not None:
        _write_json(output / device["codeset"], codeset, compact=args.compact)
    for relative, protocol in protocols.items():
        _write_json(output / relative, protocol, compact=args.compact)

    classifications = {}
    command_count = 0
    if codeset:
        command_count = len(codeset["commands"])
        for command in codeset["commands"]:
            category = command["classification"]
            classifications[category] = classifications.get(category, 0) + 1
    manifest = {
        "schema": logitech_archive.CORPUS_SCHEMA,
        "source": {
            "kind": "logitech-harmony-ir-archive",
            "schema_version": logitech_archive.ARCHIVE_SCHEMA_VERSION,
            "manifest_sha256": logitech_archive.digest(archive.manifest),
            "revision": _source_revision(archive),
        },
        "records": {
            "devices": [device_relative],
            "codesets": [] if codeset is None else [device["codeset"]],
            "protocols": sorted(protocols),
        },
        "counts": {
            "devices": 1,
            "codesets": int(codeset is not None),
            "protocols": len(protocols),
            "commands": command_count,
            "classifications": dict(sorted(classifications.items())),
        },
    }
    if manifest["source"]["revision"] is None:
        del manifest["source"]["revision"]
    _write_json(output / "manifest.json", manifest, compact=args.compact)
    print(f"converted {device['manufacturer']} {device['model']} to {output}")
    print(json.dumps(manifest["counts"], indent=2))
    return 0


def _audit(args, archive: logitech_archive.Archive) -> int:
    previous = None
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))

    def checkpoint(state):
        _write_json(args.output, state)

    profile = remotes.get(args.reproduce) if args.reproduce else None
    state = logitech_archive.audit(
        archive,
        previous=previous,
        limit=args.limit,
        revision=_source_revision(archive),
        checkpoint=checkpoint,
        checkpoint_every=args.checkpoint_every,
        reproduce=profile,
    )
    report = {
        "processed": state["processed"],
        "classifications": state["classifications"],
        "complete": state["complete"],
        "output": str(args.output),
    }
    # Representation and reproduction answer different questions and have been quoted
    # interchangeably before. Print them together or not at all.
    if state.get("reproduction"):
        report["reproduction"] = {
            "remote": state["reproduction"]["remote"],
            "strategies": state["reproduction"]["strategies"],
        }
    print(json.dumps(report, indent=2))
    return 0


def _new_conversion_manifest(archive: logitech_archive.Archive) -> dict:
    source = {
        "kind": "logitech-harmony-ir-archive",
        "schema_version": logitech_archive.ARCHIVE_SCHEMA_VERSION,
        "manifest_sha256": logitech_archive.digest(archive.manifest),
    }
    revision = _source_revision(archive)
    if revision:
        source["revision"] = revision
    return {
        "schema": logitech_archive.CORPUS_SCHEMA,
        "source": source,
        "layout": {
            "devices": "devices/<sha256(globalDeviceId)[:2]>/<globalDeviceId>.json",
            "codesets": "codesets/<source-shard>/<source-id>.json",
            "protocols": "protocols/<sha256[:2]>/<sha256>.json",
        },
        "conversion": {"phase": "protocols", "last": None, "complete": False},
        "counts": {
            "devices": 0,
            "codesets": 0,
            "protocols": 0,
            "unique_commands": 0,
            "classifications": {},
        },
    }


def _resume_after(items, last):
    started = last is None
    for key, value in items:
        if not started:
            if key == last:
                started = True
            continue
        yield key, value


def _convert_all(args, archive: logitech_archive.Archive) -> int:
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise SystemExit("bulk corpus output must stay outside the Afterglow repository")
    manifest_path = output / "manifest.json"
    if output.exists():
        if not manifest_path.is_file():
            raise SystemExit(
                f"refusing existing output without an adapter manifest: {output}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fingerprint = manifest.get("source", {}).get("manifest_sha256")
        if fingerprint != logitech_archive.digest(archive.manifest):
            raise SystemExit("output belongs to a different source archive")
    else:
        output.mkdir(parents=True)
        manifest = _new_conversion_manifest(archive)
        _write_json(manifest_path, manifest)
    if manifest.get("conversion", {}).get("complete"):
        print(f"conversion is already complete: {output}")
        return 0

    remaining = args.limit_records
    since_checkpoint = 0

    def consume() -> bool:
        nonlocal remaining, since_checkpoint
        since_checkpoint += 1
        if remaining is not None:
            remaining -= 1
        if since_checkpoint >= args.checkpoint_every:
            _write_json(manifest_path, manifest)
            since_checkpoint = 0
        return remaining == 0

    phase = manifest["conversion"]["phase"]
    last = manifest["conversion"].get("last")
    if phase == "protocols":
        indexed = ((name, archive.protocol(name))
                   for name in sorted(archive.protocol_index))
        for name, (relative, source_protocol) in _resume_after(indexed, last):
            wrapped = logitech_archive.protocol_record(relative, source_protocol)
            _write_json(
                output / logitech_archive.protocol_path(wrapped), wrapped,
                compact=not args.pretty)
            manifest["counts"]["protocols"] += 1
            manifest["conversion"]["last"] = name
            if consume():
                _write_json(manifest_path, manifest)
                print(f"checkpointed corpus conversion in {output}")
                return 0
        manifest["conversion"] = {"phase": "codesets", "last": None, "complete": False}
        _write_json(manifest_path, manifest)
        phase, last = "codesets", None

    if phase == "codesets":
        for relative, source_codeset in _resume_after(archive.iter_codesets(), last):
            codeset, _protocols = logitech_archive.transform_codeset(
                archive, relative, source_codeset)
            _write_json(output / relative, codeset, compact=not args.pretty)
            manifest["counts"]["codesets"] += 1
            manifest["counts"]["unique_commands"] += len(codeset["commands"])
            classes = manifest["counts"]["classifications"]
            for command in codeset["commands"]:
                category = command["classification"]
                classes[category] = classes.get(category, 0) + 1
            manifest["conversion"]["last"] = relative
            if consume():
                _write_json(manifest_path, manifest)
                print(f"checkpointed corpus conversion in {output}")
                return 0
        manifest["counts"]["classifications"] = dict(sorted(
            manifest["counts"]["classifications"].items()))
        manifest["conversion"] = {"phase": "devices", "last": None, "complete": False}
        _write_json(manifest_path, manifest)
        phase, last = "devices", None

    if phase == "devices":
        for relative, source_device in _resume_after(archive.iter_devices(), last):
            device = logitech_archive.device_record(relative, source_device)
            _write_json(
                output / logitech_archive.device_path(source_device), device,
                compact=not args.pretty)
            manifest["counts"]["devices"] += 1
            manifest["conversion"]["last"] = relative
            if consume():
                _write_json(manifest_path, manifest)
                print(f"checkpointed corpus conversion in {output}")
                return 0
        manifest["conversion"] = {"phase": "complete", "last": None, "complete": True}
        manifest["source_expanded_counts"] = archive.manifest.get("counts", {})
        _write_json(manifest_path, manifest)

    print(json.dumps({"complete": True, "counts": manifest["counts"],
                      "output": str(output)}, indent=2))
    return 0


def _verify_all(args, archive: logitech_archive.Archive) -> int:
    from afterglow import ir_protocol, ir_signal

    output = args.output.resolve()
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"no transformed corpus manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != logitech_archive.CORPUS_SCHEMA:
        raise SystemExit("output is not an Afterglow IR corpus")
    if not manifest.get("conversion", {}).get("complete"):
        raise SystemExit("conversion is incomplete; resume convert-all before verifying")
    if (manifest.get("source", {}).get("manifest_sha256")
            != logitech_archive.digest(archive.manifest)):
        raise SystemExit("output and source archive fingerprints differ")

    protocol_paths = set()
    protocol_count = 0
    for path in sorted(output.glob("protocols/*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != logitech_archive.PROTOCOL_RECORD_SCHEMA:
            raise SystemExit(f"wrong protocol schema: {path}")
        if path.stem != record.get("id"):
            raise SystemExit(f"protocol filename/id mismatch: {path}")
        source = record.get("source") or {}
        if source.get("sha256") != logitech_archive.digest(source.get("record")):
            raise SystemExit(f"protocol source hash mismatch: {path}")
        source_relative = source.get("path")
        if archive.read_json(source_relative) != source.get("record"):
            raise SystemExit(f"protocol source record differs: {path}")
        if record.get("portable"):
            ir_protocol.validate(record["portable"])
        relative = path.relative_to(output).as_posix()
        protocol_paths.add(relative)
        protocol_count += 1

    classifications = {}
    codeset_paths = set()
    codeset_count = 0
    unique_commands = 0
    for path in sorted(output.glob("codesets/*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != logitech_archive.CODESET_SCHEMA:
            raise SystemExit(f"wrong code-set schema: {path}")
        if path.stem != record.get("id"):
            raise SystemExit(f"code-set filename/id mismatch: {path}")
        source = record.get("source") or {}
        if source.get("sha256") != logitech_archive.digest(source.get("record")):
            raise SystemExit(f"code-set source hash mismatch: {path}")
        if archive.read_json(source.get("path")) != source.get("record"):
            raise SystemExit(f"code-set source record differs: {path}")
        commands = record.get("commands")
        if not isinstance(commands, list):
            raise SystemExit(f"code set has no command list: {path}")
        for command in commands:
            category = command.get("classification")
            if category not in logitech_archive.CLASSIFICATIONS:
                raise SystemExit(f"unknown command classification in {path}: {category!r}")
            classifications[category] = classifications.get(category, 0) + 1
            if command.get("protocol") not in protocol_paths:
                raise SystemExit(f"command names a missing protocol: {path}")
            command_source = command.get("source") or {}
            if (command_source.get("sha256")
                    != logitech_archive.digest(command_source.get("record"))):
                raise SystemExit(f"command source hash mismatch: {path}")
            signal = command.get("signal")
            if category == "semantic-with-pronto-agreement":
                if not signal or signal.get("kind") != "protocol":
                    raise SystemExit(f"semantic command has no protocol signal: {path}")
            elif category == "waveform-only":
                if not signal or signal.get("kind") != "waveform":
                    raise SystemExit(f"waveform command has no waveform signal: {path}")
            if signal:
                ir_signal.validate(signal)
        relative = path.relative_to(output).as_posix()
        codeset_paths.add(relative)
        codeset_count += 1
        unique_commands += len(commands)

    device_count = 0
    for path in sorted(output.glob("devices/*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema") != logitech_archive.DEVICE_SCHEMA:
            raise SystemExit(f"wrong device schema: {path}")
        source = record.get("source") or {}
        if source.get("sha256") != logitech_archive.digest(source.get("record")):
            raise SystemExit(f"device source hash mismatch: {path}")
        if archive.read_json(source.get("path")) != source.get("record"):
            raise SystemExit(f"device source record differs: {path}")
        expected_path = output / logitech_archive.device_path(source["record"])
        if path != expected_path:
            raise SystemExit(f"device path is not deterministic: {path}")
        codeset = record.get("codeset")
        if codeset is not None and codeset not in codeset_paths:
            raise SystemExit(f"device names a missing code set: {path}")
        device_count += 1

    actual = {
        "devices": device_count,
        "codesets": codeset_count,
        "protocols": protocol_count,
        "unique_commands": unique_commands,
        "classifications": dict(sorted(classifications.items())),
    }
    if actual != manifest.get("counts"):
        raise SystemExit(
            "verified record counts differ from manifest:\n"
            f"actual={json.dumps(actual, sort_keys=True)}\n"
            f"manifest={json.dumps(manifest.get('counts'), sort_keys=True)}")
    print(json.dumps({"verified": True, "counts": actual,
                      "output": str(output)}, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archive",
        help="local checkout, or a pinned raw HTTPS base URL in managed mode",
    )
    parser.add_argument(
        "--revision",
        help="full source commit for managed HTTPS mode; URL may contain {revision}",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        help="managed HTTPS cache directory (required for a URL source)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser(
        "convert-device", help="convert one representative device and its dependencies")
    convert.add_argument("device", help="archive-relative devices/... JSON path")
    convert.add_argument("output", type=Path, help="new output directory")
    convert.add_argument("--compact", action="store_true", help="write compact JSON")

    audit_parser = subparsers.add_parser(
        "audit", help="audit all unique code sets; rerun with the same output to resume")
    audit_parser.add_argument("output", type=Path, help="audit state/report JSON")
    audit_parser.add_argument("--limit", type=int, help="process at most this many code sets")
    audit_parser.add_argument("--checkpoint-every", type=int, default=100)
    audit_parser.add_argument(
        "--reproduce", metavar="REMOTE",
        help="also measure what this remote profile (e.g. harmony-900) can actually "
             "transmit; portable representation is not the same claim")

    convert_all = subparsers.add_parser(
        "convert-all",
        help="materialize the complete deduplicated corpus outside this repository",
    )
    convert_all.add_argument("output", type=Path, help="new or resumable output directory")
    convert_all.add_argument(
        "--limit-records", type=int,
        help="checkpoint after this many protocol/code-set/device records",
    )
    convert_all.add_argument("--checkpoint-every", type=int, default=100)
    convert_all.add_argument(
        "--pretty", action="store_true",
        help="indent bulk JSON (compact output is the efficient default)",
    )

    verify = subparsers.add_parser(
        "verify", help="parse and cross-check every transformed corpus record")
    verify.add_argument("output", type=Path)

    args = parser.parse_args(argv)
    if args.archive.startswith("https://"):
        if not args.revision or args.cache is None:
            parser.error("a URL source requires --revision and --cache")
        archive = logitech_archive.CachedHttpArchive(
            args.archive, args.cache, args.revision)
    else:
        archive = logitech_archive.Archive(Path(args.archive))
    if args.command == "convert-device":
        return _convert_device(args, archive)
    if args.command == "convert-all":
        return _convert_all(args, archive)
    if args.command == "verify":
        return _verify_all(args, archive)
    return _audit(args, archive)


if __name__ == "__main__":
    raise SystemExit(main())
