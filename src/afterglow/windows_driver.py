"""Switch the Harmony 900/1000/1100 to Windows' own WinUSB driver, and back.

Selects the "WinUsb Device" model from Windows' winusb.inf, as Device Manager's "Let me
pick from a list" does - no driver package or certificate of ours. Windows treats each
USB port as a new device, so a remote on a new port may need switching again. Needs an
administrator: Afterglow restarts itself elevated with `--usb-driver install|restore`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

REMOTE_IDS = ("VID_046D&PID_C11F",)       # Harmony 900, 1000 and 1100
WINUSB = "WINUSB"
INSTALL, RESTORE = "install", "restore"
CANCELLED = "cancelled"

_USB_DEVICE_CLASS = "{88BAE032-5A81-49F0-BC3D-A4FF138216D6}"
_WINUSB_MODEL = "WinUsb Device"


def applicable() -> bool:
    return sys.platform == "win32"


# --- SetupAPI ---------------------------------------------------------------------------

def _api():
    """SetupAPI structures and functions, bound on first use (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class DEVINFO(ctypes.Structure):                       # SP_DEVINFO_DATA
        _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID),
                    ("DevInst", wintypes.DWORD), ("Reserved", ctypes.c_size_t)]

    class INSTALL_PARAMS(ctypes.Structure):                # SP_DEVINSTALL_PARAMS_W
        _fields_ = [("cbSize", wintypes.DWORD), ("Flags", wintypes.DWORD),
                    ("FlagsEx", wintypes.DWORD), ("hwndParent", wintypes.HWND),
                    ("InstallMsgHandler", ctypes.c_void_p),
                    ("InstallMsgHandlerContext", ctypes.c_void_p),
                    ("FileQueue", ctypes.c_void_p), ("ClassInstallReserved", ctypes.c_size_t),
                    ("Reserved", wintypes.DWORD), ("DriverPath", wintypes.WCHAR * 260)]

    class DRVINFO(ctypes.Structure):                       # SP_DRVINFO_DATA_V2_W
        _fields_ = [("cbSize", wintypes.DWORD), ("DriverType", wintypes.DWORD),
                    ("Reserved", ctypes.c_size_t), ("Description", wintypes.WCHAR * 256),
                    ("MfgName", wintypes.WCHAR * 256), ("ProviderName", wintypes.WCHAR * 256),
                    ("DriverDate", wintypes.FILETIME), ("DriverVersion", ctypes.c_ulonglong)]

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    newdev = ctypes.WinDLL("newdev", use_last_error=True)
    cfgmgr = ctypes.WinDLL("cfgmgr32")
    P = ctypes.POINTER
    HDEVINFO = ctypes.c_void_p
    for function, restype, argtypes in (
        (setupapi.SetupDiGetClassDevsW, HDEVINFO,
         [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]),
        (setupapi.SetupDiDestroyDeviceInfoList, wintypes.BOOL, [HDEVINFO]),
        (setupapi.SetupDiEnumDeviceInfo, wintypes.BOOL,
         [HDEVINFO, wintypes.DWORD, P(DEVINFO)]),
        (setupapi.SetupDiGetDeviceInstanceIdW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), wintypes.LPWSTR, wintypes.DWORD, P(wintypes.DWORD)]),
        (setupapi.SetupDiGetDeviceRegistryPropertyW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), wintypes.DWORD, P(wintypes.DWORD), ctypes.c_void_p,
          wintypes.DWORD, P(wintypes.DWORD)]),
        (setupapi.SetupDiSetDeviceRegistryPropertyW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]),
        (setupapi.SetupDiGetDeviceInstallParamsW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), P(INSTALL_PARAMS)]),
        (setupapi.SetupDiSetDeviceInstallParamsW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), P(INSTALL_PARAMS)]),
        (setupapi.SetupDiBuildDriverInfoList, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), wintypes.DWORD]),
        (setupapi.SetupDiEnumDriverInfoW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), wintypes.DWORD, wintypes.DWORD, P(DRVINFO)]),
        (setupapi.SetupDiSetSelectedDriverW, wintypes.BOOL,
         [HDEVINFO, P(DEVINFO), P(DRVINFO)]),
        (setupapi.SetupDiCallClassInstaller, wintypes.BOOL,
         [wintypes.DWORD, HDEVINFO, P(DEVINFO)]),
        (newdev.DiInstallDevice, wintypes.BOOL,
         [wintypes.HWND, HDEVINFO, P(DEVINFO), P(DRVINFO), wintypes.DWORD,
          P(wintypes.BOOL)]),
        (cfgmgr.CM_Locate_DevNodeW, wintypes.DWORD,
         [P(wintypes.DWORD), wintypes.LPCWSTR, wintypes.ULONG]),
        (cfgmgr.CM_Reenumerate_DevNode, wintypes.DWORD, [wintypes.DWORD, wintypes.ULONG]),
        (cfgmgr.CM_Get_DevNode_Status, wintypes.DWORD,
         [P(wintypes.ULONG), P(wintypes.ULONG), wintypes.DWORD, wintypes.ULONG]),
    ):
        function.restype = restype
        function.argtypes = argtypes

    class Api:
        pass
    api = Api()
    api.ctypes, api.wintypes = ctypes, wintypes
    api.GUID, api.DEVINFO, api.INSTALL_PARAMS, api.DRVINFO = (
        GUID, DEVINFO, INSTALL_PARAMS, DRVINFO)
    api.setupapi, api.newdev, api.cfgmgr = setupapi, newdev, cfgmgr
    return api


DIGCF_PRESENT, DIGCF_ALLCLASSES = 0x2, 0x4
SPDRP_SERVICE, SPDRP_CLASSGUID = 0x4, 0x8
SPDIT_CLASSDRIVER = 1
DI_ENUMSINGLEINF = 0x10000
DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x800
DIF_REMOVE = 0x5
INVALID_HANDLE = 2 ** (8 * __import__("struct").calcsize("P")) - 1


class DriverError(RuntimeError):
    pass


def _failed(step: str, ctypes) -> DriverError:
    return DriverError(f"Windows could not {step} (error {ctypes.get_last_error()}).")


def _each_remote(api):
    """Yield `(device_set, devinfo, instance_id)` for each remote plugged in."""
    ctypes = api.ctypes
    handle = api.setupapi.SetupDiGetClassDevsW(None, "USB", None,
                                               DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not handle or handle == INVALID_HANDLE:
        raise _failed("list the USB devices", ctypes)
    try:
        index = 0
        while True:
            dev = api.DEVINFO()
            dev.cbSize = ctypes.sizeof(dev)
            if not api.setupapi.SetupDiEnumDeviceInfo(handle, index, ctypes.byref(dev)):
                return
            index += 1
            buffer = ctypes.create_unicode_buffer(512)
            if not api.setupapi.SetupDiGetDeviceInstanceIdW(
                    handle, ctypes.byref(dev), buffer, 512, None):
                continue
            if any(ident in buffer.value.upper() for ident in REMOTE_IDS):
                yield handle, dev, buffer.value
    finally:
        api.setupapi.SetupDiDestroyDeviceInfoList(handle)


def _service(api, handle, dev) -> str:
    ctypes = api.ctypes
    buffer = ctypes.create_unicode_buffer(256)
    if api.setupapi.SetupDiGetDeviceRegistryPropertyW(
            handle, ctypes.byref(dev), SPDRP_SERVICE, None, buffer,
            ctypes.sizeof(buffer), None):
        return buffer.value
    return ""


def _started(api, dev) -> bool:
    status, problem = api.wintypes.ULONG(), api.wintypes.ULONG()
    if api.cfgmgr.CM_Get_DevNode_Status(api.ctypes.byref(status), api.ctypes.byref(problem),
                                        dev.DevInst, 0):
        return False
    return bool(status.value & 0x8) and not problem.value      # DN_STARTED, no problem


def remotes() -> list[dict]:
    """Each remote plugged in: `{"id", "service", "started"}`. No elevation needed."""
    if not applicable():
        return []
    api = _api()
    return [{"id": ident, "service": _service(api, handle, dev),
             "started": _started(api, dev)}
            for handle, dev, ident in _each_remote(api)]


def needs_switch(found=None) -> bool:
    """Whether a remote is plugged in that is not on WinUSB yet."""
    found = remotes() if found is None else found
    return any(remote["service"].upper() != WINUSB for remote in found)


def describe(remote: dict) -> str:
    """How the remote is connected, in words for the user."""
    service = remote["service"].upper()
    if service == WINUSB:
        return "direct access"
    if "USBLAN" in service:
        return "Logitech's driver"
    return "another driver" if service else "no driver"


def _bind(api, handle, dev, ident) -> None:
    ctypes = api.ctypes
    # Device Manager's list is per class, and a remote with no driver has no class.
    klass = (_USB_DEVICE_CLASS + "\0").encode("utf-16-le")
    if not api.setupapi.SetupDiSetDeviceRegistryPropertyW(
            handle, ctypes.byref(dev), SPDRP_CLASSGUID, klass, len(klass)):
        raise _failed("prepare the remote", ctypes)
    import uuid
    guid = uuid.UUID(_USB_DEVICE_CLASS)
    dev.ClassGuid = api.GUID.from_buffer_copy(guid.bytes_le)

    params = api.INSTALL_PARAMS()
    params.cbSize = ctypes.sizeof(params)
    if not api.setupapi.SetupDiGetDeviceInstallParamsW(handle, ctypes.byref(dev),
                                                       ctypes.byref(params)):
        raise _failed("prepare the remote", ctypes)
    params.Flags |= DI_ENUMSINGLEINF
    params.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS
    params.DriverPath = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "INF",
                                     "winusb.inf")
    if not api.setupapi.SetupDiSetDeviceInstallParamsW(handle, ctypes.byref(dev),
                                                       ctypes.byref(params)):
        raise _failed("prepare the remote", ctypes)
    if not api.setupapi.SetupDiBuildDriverInfoList(handle, ctypes.byref(dev),
                                                   SPDIT_CLASSDRIVER):
        raise _failed("find its own USB driver", ctypes)

    index = 0
    while True:
        driver = api.DRVINFO()
        driver.cbSize = ctypes.sizeof(driver)
        if not api.setupapi.SetupDiEnumDriverInfoW(handle, ctypes.byref(dev),
                                                   SPDIT_CLASSDRIVER, index,
                                                   ctypes.byref(driver)):
            raise DriverError("Windows' own USB driver was not found on this PC")
        index += 1
        if driver.Description == _WINUSB_MODEL:
            break
    if not api.setupapi.SetupDiSetSelectedDriverW(handle, ctypes.byref(dev),
                                                  ctypes.byref(driver)):
        raise _failed("switch the remote", ctypes)
    reboot = api.wintypes.BOOL()
    if not api.newdev.DiInstallDevice(None, handle, ctypes.byref(dev), ctypes.byref(driver),
                                      0, ctypes.byref(reboot)):
        raise _failed("switch the remote", ctypes)


def _remove(api, handle, dev, ident) -> None:
    if not api.setupapi.SetupDiCallClassInstaller(DIF_REMOVE, handle, api.ctypes.byref(dev)):
        raise _failed("switch the remote back", api.ctypes)


def _rescan(api) -> None:
    root = api.wintypes.DWORD()
    if not api.cfgmgr.CM_Locate_DevNodeW(api.ctypes.byref(root), None, 0):
        api.cfgmgr.CM_Reenumerate_DevNode(root.value, 0)


def _settle(want_winusb: bool, seconds: float = 15.0) -> list[dict]:
    """Wait for the remotes to restart on the driver asked for."""
    deadline = time.monotonic() + seconds
    while True:
        found = remotes()
        ready = found and all(
            remote["started"] and (remote["service"].upper() == WINUSB) == want_winusb
            for remote in found)
        if ready or time.monotonic() > deadline:
            return found
        time.sleep(0.5)


def switch(action: str) -> str:
    """`install` or `restore` for each remote plugged in. Needs an administrator."""
    if not applicable():
        raise DriverError("Only Windows has a driver to switch.")
    api = _api()
    done = []
    for handle, dev, ident in _each_remote(api):
        on_winusb = _service(api, handle, dev).upper() == WINUSB
        if action == INSTALL and not on_winusb:
            _bind(api, handle, dev, ident)
            done.append(ident)
        elif action == RESTORE and on_winusb:
            _remove(api, handle, dev, ident)
            done.append(ident)
    if action == RESTORE and done:
        _rescan(api)
    if not done:
        return ("Nothing needed changing." if remotes()
                else "No Harmony 900, 1000 or 1100 is plugged in.")
    found = _settle(want_winusb=action == INSTALL)
    now = " and ".join(sorted({describe(remote) for remote in found})) or "not plugged in"
    return f"The remote now uses {now}."


# --- elevation --------------------------------------------------------------------------

def _relaunch_command() -> tuple[str, str]:
    """This program as `(executable, parameters)` for ShellExecute."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # An elevated process does not inherit PYTHONPATH.
    code = (f"import sys; sys.path.insert(0, {source!r}); "
            f"from afterglow.windows_driver import main; raise SystemExit(main())")
    return sys.executable, f'-c "{code}"'


def run_elevated(action: str) -> tuple[bool, str]:
    """Do `action` elevated. `(ok, message)`; `(False, CANCELLED)` if declined."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    fd, result_path = tempfile.mkstemp(prefix="afterglow-usb-driver-", suffix=".json")
    os.close(fd)
    executable, parameters = _relaunch_command()
    parameters = f'{parameters} --usb-driver {action} --result "{result_path}"'.strip()
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x400                    # NOCLOSEPROCESS | FLAG_NO_UI
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.nShow = 0                               # SW_HIDE
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == 1223:                    # ERROR_CANCELLED: the prompt said no
                return False, CANCELLED
            return False, f"Windows could not start the driver setup (error {error})."
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        kernel32.CloseHandle(info.hProcess)
        try:
            with open(result_path, encoding="utf-8") as stream:
                result = json.load(stream)
        except (OSError, ValueError):
            result = {"ok": False,
                      "message": f"The driver setup ended without a result (exit {code.value})."}
        return bool(result.get("ok")), str(result.get("message", ""))
    finally:
        try:
            os.remove(result_path)
        except OSError:
            pass


def main(argv=None) -> int:
    """The elevated half: `--usb-driver install|restore [--result FILE]`."""
    argv = sys.argv[1:] if argv is None else argv
    action = argv[argv.index("--usb-driver") + 1] if "--usb-driver" in argv else ""
    result_path = argv[argv.index("--result") + 1] if "--result" in argv else None
    if action not in (INSTALL, RESTORE):
        result = {"ok": False, "message": f"unknown action {action!r}"}
    else:
        try:
            result = {"ok": True, "message": switch(action)}
        except DriverError as exc:
            result = {"ok": False, "message": str(exc)}
        except Exception as exc:                                   # noqa: BLE001
            result = {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    if result_path:
        with open(result_path, "w", encoding="utf-8") as stream:
            json.dump(result, stream)
    else:
        print(result["message"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
