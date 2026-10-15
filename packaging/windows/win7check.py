"""Flag Windows DLLs and executables that will not load on Windows 7.

    python packaging/windows/win7check.py <file or folder> [<file or folder> ...]
    python packaging/windows/win7check.py @list.txt    # one path per line

A Windows binary that imports a function its system lacks does not start at all: the
loader stops with "The procedure entry point ... could not be located in the dynamic link
library", before any of our code can explain. Nothing in a build on Windows 10 or 11
notices, because there every function exists.

This reads each file's import tables (normal and delay-loaded) and reports:

* functions that first appeared in Windows 8 or later, from a list of the ones that
  real toolchains and libraries actually reach for - not a full catalogue of the API,
  so a clean result is strong evidence rather than proof;
* DLLs that Windows 7 does not have at all.

Exit status 1 if anything is found. Plain Python, so it also runs on Linux against a
cross-compiled DLL.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

# Functions newer than Windows 7, by the DLL that exports them. Lowercase DLL names.
NEWER_FUNCTIONS = {
    "kernel32.dll": {
        "GetSystemTimePreciseAsFileTime", "CreateFile2", "GetOverlappedResultEx",
        "GetCurrentThreadStackLimits", "SetThreadDescription", "GetThreadDescription",
        "PrefetchVirtualMemory", "GetProcessMitigationPolicy",
        "SetProcessMitigationPolicy", "GetPackageFamilyName", "GetCurrentPackageId",
        "GetCurrentPackageFullName", "GetCurrentPackageFamilyName", "GetFirmwareType",
        "InitializeSynchronizationBarrier", "EnterSynchronizationBarrier",
        "DeleteSynchronizationBarrier", "CopyFile2", "CreateFileMappingFromApp",
        "MapViewOfFileFromApp", "VirtualAllocFromApp", "QueryUnbiasedInterruptTimePrecise",
        "GetSystemCpuSetInformation", "SetThreadSelectedCpuSets", "WaitOnAddress",
        "WakeByAddressSingle", "WakeByAddressAll", "GetFileInformationByName",
        "SetThreadInformation", "GetThreadInformation", "SetProcessInformation",
        "GetProcessInformation", "DiscardVirtualMemory", "OfferVirtualMemory",
        "ReclaimVirtualMemory", "VirtualAlloc2", "MapViewOfFile3",
        "GetIntegratedDisplaySize", "GetOsSafeBootMode", "CreatePseudoConsole",
        "GetTempPath2W", "GetTempPath2A",
    },
    "kernelbase.dll": {"WaitOnAddress", "WakeByAddressSingle", "WakeByAddressAll",
                       "VirtualAlloc2", "MapViewOfFile3"},
    "user32.dll": {
        "GetDpiForWindow", "GetDpiForSystem", "SetThreadDpiAwarenessContext",
        "GetThreadDpiAwarenessContext", "AreDpiAwarenessContextsEqual",
        "GetSystemMetricsForDpi", "AdjustWindowRectExForDpi", "EnableNonClientDpiScaling",
        "SetProcessDpiAwarenessContext", "GetAwarenessFromDpiAwarenessContext",
        "SystemParametersInfoForDpi", "GetWindowDpiAwarenessContext",
        "GetPointerType", "GetPointerInfo", "GetPointerTouchInfo", "GetPointerPenInfo",
        "GetPointerFrameInfo", "EnableMouseInPointer", "IsMouseInPointerEnabled",
        "RegisterPointerInputTarget", "InitializeTouchInjection", "InjectTouchInput",
        "SetCoalescableTimer", "GetPointerDevices", "SkipPointerFrameMessages",
        "EvaluateProximityToRect", "GetDisplayAutoRotationPreferences",
        "SetDisplayAutoRotationPreferences", "LogicalToPhysicalPointForPerMonitorDPI",
        "PhysicalToLogicalPointForPerMonitorDPI", "GetDialogDpiChangeBehavior",
    },
    "bcrypt.dll": {"BCryptHash", "BCryptKeyDerivation", "BCryptCreateMultiHash",
                   "BCryptProcessMultiOperations"},
    "advapi32.dll": {"CreateAppContainerProfile"},
    "ws2_32.dll": {"GetAddrInfoExCancel", "GetAddrInfoExOverlappedResult"},
    "ntdll.dll": {"RtlGetDeviceFamilyInfoEnum", "RtlWaitOnAddress",
                  "RtlWakeAddressSingle", "RtlWakeAddressAll"},
}

# DLLs Windows 7 does not ship. The API sets Windows 7 does have (`api-ms-win-*-l1-1-0`
# for core functions) are allowed, as is the Universal CRT (`api-ms-win-crt-*`, which
# Python carries) and `api-ms-win-core-path-l1-1-0`, which the Windows 7 Python build
# carries as a shim.
MISSING_DLLS = {
    "combase.dll", "shcore.dll", "bcryptprimitives.dll", "windows.storage.dll",
    "d3d12.dll", "dxcore.dll", "mfreadwrite.dll", "coremessaging.dll",
    "wintypes.dll", "api-ms-win-core-winrt-l1-1-0.dll",
    "api-ms-win-core-winrt-string-l1-1-0.dll", "api-ms-win-shcore-scaling-l1-1-1.dll",
    "api-ms-win-core-synch-l1-2-0.dll", "api-ms-win-core-sysinfo-l1-2-0.dll",
    "api-ms-win-core-file-l1-2-0.dll", "api-ms-win-core-file-l2-1-0.dll",
    "api-ms-win-core-libraryloader-l1-2-0.dll", "api-ms-win-core-memory-l1-1-1.dll",
    "api-ms-win-core-processthreads-l1-1-1.dll",
    "api-ms-win-core-processthreads-l1-1-2.dll", "api-ms-win-core-wow64-l1-1-1.dll",
}
# `bcryptprimitives.dll` exists on Windows 7, but the only thing anything imports from
# it is `ProcessPrng`, which is Windows 8+; flagging the DLL catches it either way.
ALLOWED_API_SETS = ("api-ms-win-crt-", "api-ms-win-core-path-l1-1-0")


def _rva_to_offset(sections, rva):
    for virtual, size, raw, raw_size in sections:
        if virtual <= rva < virtual + max(size, raw_size):
            return rva - virtual + raw
    return None


def _string(data, offset):
    end = data.index(b"\0", offset)
    return data[offset:end].decode("ascii", "replace")


def imports(data: bytes) -> dict[str, set[str]]:
    """{dll name (lowercase): imported function names} for a PE file, or {} if not one."""
    if data[:2] != b"MZ":
        return {}
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return {}
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    wide = magic == 0x20B
    directories = optional + (112 if wide else 96)
    sections = []
    table = optional + optional_size
    for index in range(count):
        entry = table + index * 40
        size, virtual, raw_size, raw = struct.unpack_from("<IIII", data, entry + 8)
        sections.append((virtual, size, raw, raw_size))
    found: dict[str, set[str]] = {}
    thunk_size, ordinal_flag = (8, 1 << 63) if wide else (4, 1 << 31)

    def walk_thunks(rva):
        names = set()
        offset = _rva_to_offset(sections, rva) if rva else None
        while offset is not None:
            value = struct.unpack_from("<Q" if wide else "<I", data, offset)[0]
            if not value:
                break
            if not value & ordinal_flag:
                name_at = _rva_to_offset(sections, value & 0x7FFFFFFF)
                if name_at is not None:
                    names.add(_string(data, name_at + 2))
            offset += thunk_size
        return names

    # Normal imports: data directory 1, 20-byte descriptors.
    rva = struct.unpack_from("<I", data, directories + 8)[0]
    offset = _rva_to_offset(sections, rva) if rva else None
    while offset is not None:
        lookup, _stamp, _chain, name, address = struct.unpack_from("<IIIII", data, offset)
        if not name:
            break
        dll = _string(data, _rva_to_offset(sections, name)).lower()
        found.setdefault(dll, set()).update(walk_thunks(lookup or address))
        offset += 20
    # Delay-loaded imports: data directory 13, 32-byte descriptors.
    rva = struct.unpack_from("<I", data, directories + 13 * 8)[0]
    offset = _rva_to_offset(sections, rva) if rva else None
    while offset is not None:
        fields = struct.unpack_from("<IIIIIIII", data, offset)
        if not fields[1]:
            break
        dll = _string(data, _rva_to_offset(sections, fields[1])).lower()
        found.setdefault(dll, set()).update(walk_thunks(fields[4]))
        offset += 32
    return found


def problems(path: Path, shipped: frozenset[str] = frozenset()) -> list[str]:
    """What in `path` would not load on Windows 7. `shipped` names the DLLs (lowercase)
    travelling with it, which count as present - the Universal CRT's own API-set files
    are exactly that."""
    try:
        table = imports(path.read_bytes())
    except (struct.error, ValueError, IndexError) as error:
        return [f"could not read imports: {error}"]
    found = []
    for dll, names in sorted(table.items()):
        if dll in shipped:
            pass
        elif dll in MISSING_DLLS or (dll.startswith("api-ms-win-")
                                   and not dll.startswith(ALLOWED_API_SETS)
                                   and not dll.endswith("-l1-1-0.dll")):
            found.append(f"imports {dll}, which Windows 7 does not have")
        for name in sorted(names & NEWER_FUNCTIONS.get(dll, set())):
            found.append(f"imports {dll}!{name}, which is newer than Windows 7")
    return found


def _paths(arguments):
    for argument in arguments:
        if argument.startswith("@"):
            yield from _paths(line.strip() for line in
                              Path(argument[1:]).read_text().splitlines() if line.strip())
            continue
        path = Path(argument)
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*")
                              if p.suffix.lower() in (".dll", ".pyd", ".exe"))
        else:
            yield path


def main(argv=None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print(__doc__)
        return 2
    checked = bad = 0
    paths = list(_paths(arguments))
    shipped = frozenset(path.name.lower() for path in paths)
    for path in paths:
        checked += 1
        for problem in problems(path, shipped):
            bad += 1
            print(f"{path}: {problem}")
    print(f"checked {checked} file(s): "
          + (f"{bad} problem(s)" if bad else "nothing newer than Windows 7"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
