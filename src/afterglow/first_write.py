"""Recovery-backed first hardware write for an experimental remote profile.

This is deliberately separate from the GUI's verified-only write path:

    afterglow-first-write prepare candidate.ezhex --recovery recovery.ezhex \
        --report first-write.json
    afterglow-first-write apply first-write.json
    afterglow-first-write readback first-write.json --out readback.ezhex

Preparation captures the connected remote's current configuration, validates both files,
and records a backend-native change report. Applying rechecks every digest and identity and
requires the report-specific phrase. Readback is separate because a reboot may temporarily
remove the USB interface; a delayed reconnection must never look like a failed flash.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from . import backends, concord, ezhex, payloads, remotes

SCHEMA = "afterglow-first-write/1"
IDENTITY_FIELDS = ("arch", "skin", "flash", "board", "software_type", "firmware")
ARTIFACT_IDENTITY_FIELDS = ("arch", "skin", "flash", "board", "software_type")


class FirstWriteError(RuntimeError):
    """A precondition for the controlled first-write workflow was not met."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact(path: Path, profile=None) -> tuple[dict, bytes]:
    path = Path(path).resolve()
    try:
        raw = path.read_bytes()
        header, start, declared_size, declared_checksum = ezhex._split(raw)
    except (OSError, ValueError) as exc:
        raise FirstWriteError(f"cannot read {path}: {exc}") from exc
    payload = raw[start:start + declared_size]
    if start + declared_size != len(raw):
        raise FirstWriteError(f"{path.name} has bytes outside its declared payload")
    if declared_checksum is None or ezhex.checksum(payload) != declared_checksum:
        raise FirstWriteError(f"{path.name} fails its EZHex checksum")
    profile = profile or remotes.identify(header)
    identity = remotes.identity_of(header)
    problems = profile.identity_mismatches(identity, require_all=True)
    if problems:
        raise FirstWriteError(f"{path.name} violates its profile: {'; '.join(problems)}")
    carrier = payloads.get(profile.payload)
    sniff = getattr(carrier, "sniff", None)
    if callable(sniff) and not sniff(payload):
        raise FirstWriteError(
            f"{path.name} does not contain the profile's {profile.payload!r} payload")
    backend = backends.for_profile(profile)
    validator = getattr(backend, "validate_payload", None)
    if not callable(validator):
        raise FirstWriteError(
            f"backend {profile.backend!r} has no independent artifact validator")
    try:
        native = validator(payload, profile)
    except (OSError, ValueError) as exc:
        raise FirstWriteError(f"{path.name} fails native validation: {exc}") from exc
    return ({
        "path": str(path),
        "sha256": _digest(raw),
        "payload_sha256": _digest(payload),
        "size": len(raw),
        "payload_size": len(payload),
        "identity": identity,
        "validation": {
            "envelope": "size-and-checksum-valid",
            "native": native,
        },
    }, payload)


def _same_identity(expected: dict, actual: dict, fields=IDENTITY_FIELDS) -> list[str]:
    return [
        f"{field}: expected {expected.get(field)!r}, got {actual.get(field)!r}"
        for field in fields
        if expected.get(field) != actual.get(field)
    ]


def _write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def prepare(artifact, recovery, report, *, recovery_copy=None, remote_factory=concord.Remote):
    artifact_path = Path(artifact)
    recovery_path = Path(recovery).resolve()
    report_path = Path(report).resolve()
    copy_path = (Path(recovery_copy).resolve() if recovery_copy else
                 recovery_path.with_name(recovery_path.stem + ".copy" + recovery_path.suffix))
    for output in (recovery_path, copy_path, report_path):
        if output.exists():
            raise FirstWriteError(f"refusing to overwrite {output}")

    profile = ezhex.profile_of(artifact_path)
    if profile.status != remotes.EXPERIMENTAL:
        raise FirstWriteError(
            f"first-write preparation requires an experimental profile, got "
            f"{profile.status!r}")
    candidate, candidate_payload = _artifact(artifact_path, profile)

    recovery_path.parent.mkdir(parents=True, exist_ok=True)
    with remote_factory() as remote:
        live = remote.identity()
        problems = profile.identity_mismatches(live, require_all=True)
        if problems:
            raise FirstWriteError(f"attached remote violates the profile: {'; '.join(problems)}")
        if not live.get("can_read") or not live.get("can_write"):
            raise FirstWriteError("the attached remote must support both readback and writing")
        remote.save_config(recovery_path)

    recovery_info, recovery_payload = _artifact(recovery_path, profile)
    identity_problems = _same_identity(
        live, recovery_info["identity"], ARTIFACT_IDENTITY_FIELDS)
    if identity_problems:
        raise FirstWriteError(
            "the recovery artifact does not identify the attached remote: "
            + "; ".join(identity_problems))
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(recovery_path, copy_path)
    if _digest(copy_path.read_bytes()) != recovery_info["sha256"]:
        raise FirstWriteError("the second recovery copy does not match the first")

    backend = backends.for_profile(profile)
    comparer = getattr(backend, "compare_payloads", None)
    if not callable(comparer):
        raise FirstWriteError(f"backend {profile.backend!r} cannot produce a change report")
    changes = comparer(recovery_payload, candidate_payload, profile)
    phrase = f"WRITE {profile.id} {candidate['sha256'][:12]}"
    data = {
        "schema": SCHEMA,
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile.id,
        "identity": {field: live.get(field) for field in IDENTITY_FIELDS},
        "artifact": candidate,
        "recovery": recovery_info,
        "recovery_copy": {"path": str(copy_path), "sha256": recovery_info["sha256"]},
        "changes": changes,
        "confirmation": phrase,
    }
    _write_json(report_path, data)
    return data


def _load_report(path) -> tuple[Path, dict]:
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FirstWriteError(f"cannot read report {path}: {exc}") from exc
    if data.get("schema") != SCHEMA:
        raise FirstWriteError(f"{path} is not an {SCHEMA} report")
    return path, data


def _revalidate_report(data: dict, profile) -> None:
    for name in ("artifact", "recovery"):
        current, _payload = _artifact(Path(data[name]["path"]), profile)
        if current["sha256"] != data[name]["sha256"]:
            raise FirstWriteError(f"{name} changed after the report was prepared")
    copy = Path(data["recovery_copy"]["path"])
    if _digest(copy.read_bytes()) != data["recovery_copy"]["sha256"]:
        raise FirstWriteError("the second recovery copy changed after preparation")


def apply(report, *, ask=input, remote_factory=concord.Remote) -> dict:
    report_path, data = _load_report(report)
    if data.get("status") != "prepared":
        raise FirstWriteError(f"report status is {data.get('status')!r}, not 'prepared'")
    profile = remotes.get(data["profile"])
    if profile.status != remotes.EXPERIMENTAL:
        raise FirstWriteError("the profile is no longer experimental")
    _revalidate_report(data, profile)
    phrase = data["confirmation"]
    if ask(f"Type {phrase!r} to write: ").strip() != phrase:
        raise FirstWriteError("confirmation did not match; nothing was written")

    try:
        with remote_factory() as remote:
            # Connection and identity checks are read-only, so do them while the report
            # can still truthfully remain prepared.
            remote._authorize_experimental_config(
                data["artifact"]["path"], data["identity"])
            # Persist this immediately before the first mutating call. If the process or
            # USB link disappears now, rerunning `apply` is refused; readback determines
            # what happened instead of risking a second write.
            data["status"] = "write-started"
            data["write_started_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(report_path, data)
            remote._apply_config(data["artifact"]["path"])
            restart_error = remote.last_restart_error
    except Exception as exc:
        if data.get("status") != "write-started":
            raise
        data["status"] = "write-outcome-unknown"
        data["write_error"] = f"{type(exc).__name__}: {exc}"
        _write_json(report_path, data)
        raise FirstWriteError(
            "the write outcome is unknown; do not apply again. Reconnect the remote and "
            "run readback to determine which payload is present") from exc
    data["status"] = "written-awaiting-readback"
    data["written_at"] = datetime.now(timezone.utc).isoformat()
    data["restart_warning"] = restart_error
    _write_json(report_path, data)
    return data


def readback(report, out, *, remote_factory=concord.Remote) -> dict:
    report_path, data = _load_report(report)
    if data.get("status") not in {
            "write-started", "write-outcome-unknown", "written-awaiting-readback"}:
        raise FirstWriteError("the report is not awaiting readback")
    profile = remotes.get(data["profile"])
    output = Path(out).resolve()
    if output.exists():
        raise FirstWriteError(f"refusing to overwrite {output}")
    with remote_factory() as remote:
        live = remote.identity()
        problems = _same_identity(data["identity"], live)
        if problems:
            raise FirstWriteError("readback remote differs: " + "; ".join(problems))
        remote.save_config(output)
    readback_info, _payload = _artifact(output, profile)
    if readback_info["payload_sha256"] != data["artifact"]["payload_sha256"]:
        raise FirstWriteError(
            "readback payload differs from the artifact; preserve all files and do not retry")
    data["status"] = "readback-verified"
    data["readback"] = readback_info
    data["readback_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(report_path, data)
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("artifact")
    prep.add_argument("--recovery", required=True)
    prep.add_argument("--recovery-copy")
    prep.add_argument("--report", required=True)
    write = commands.add_parser("apply")
    write.add_argument("report")
    verify = commands.add_parser("readback")
    verify.add_argument("report")
    verify.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(
                args.artifact, args.recovery, args.report,
                recovery_copy=args.recovery_copy)
            print(json.dumps({"status": result["status"], "changes": result["changes"],
                              "confirmation": result["confirmation"]}, indent=2))
        elif args.command == "apply":
            result = apply(args.report)
            print(f"write completed; report status: {result['status']}")
            print("Wait for the remote to boot, then run the readback command.")
        else:
            result = readback(args.report, args.out)
            print(f"readback verified: {result['readback']['payload_sha256']}")
    except (FirstWriteError, concord.NotAvailable, concord.RemoteError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
