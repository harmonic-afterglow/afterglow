/*
 * afterglow-winusb: put a Harmony 900/1000/1100 on WinUSB on Windows 7, and take it off.
 *
 *     afterglow-winusb install <inf file> <hardware id>
 *     afterglow-winusb remove <hardware id>
 *
 * Windows 8 and later have a generic WinUSB entry in winusb.inf that Afterglow selects
 * itself (afterglow/windows_driver.py). Windows 7 has none, so Afterglow writes a small
 * INF of its own that points the remote at Windows' WinUSB driver, and this installs it.
 *
 * It is a separate native program, in a 32- and a 64-bit build, because Windows refuses
 * device installation from a 32-bit process on 64-bit Windows (ERROR_IN_WOW64), and the
 * Windows 7 build of Afterglow is 32-bit. Afterglow runs the one matching the system,
 * already elevated.
 *
 * The INF is not signed, so Windows asks once whether to install it anyway.
 *
 * Exit status 0 on success; otherwise a message on stdout says what Windows refused.
 */
#define _WIN32_WINNT 0x0601
#define WINVER 0x0601
#include <windows.h>
#include <setupapi.h>
#include <newdev.h>
#include <cfgmgr32.h>
#include <stdio.h>
#include <wchar.h>

/* Every INF Afterglow writes carries this line; only those are ever deleted. */
#define MARKER L"; Afterglow WinUSB driver for Logitech Harmony remotes"

#ifndef SUOI_FORCEDELETE
#define SUOI_FORCEDELETE 0x0001
#endif

static int failed(const wchar_t *what) {
    DWORD error = GetLastError();
    wprintf(L"Windows could not %ls (error 0x%08lX).\n", what, (unsigned long)error);
    return 1;
}

/* Whether `wanted` is one of the device's hardware IDs, ignoring case. */
static BOOL has_id(HDEVINFO set, SP_DEVINFO_DATA *dev, const wchar_t *wanted) {
    wchar_t ids[2048];
    if (!SetupDiGetDeviceRegistryPropertyW(set, dev, SPDRP_HARDWAREID, NULL, (BYTE *)ids,
                                           sizeof(ids) - sizeof(wchar_t), NULL))
        return FALSE;
    ids[sizeof(ids) / sizeof(wchar_t) - 1] = 0;
    for (wchar_t *id = ids; *id; id += wcslen(id) + 1)
        if (_wcsicmp(id, wanted) == 0)
            return TRUE;
    return FALSE;
}

/* Whether the file at `path` is one of ours, by its marker line. */
static BOOL is_ours(const wchar_t *path) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0,
                              NULL);
    if (file == INVALID_HANDLE_VALUE)
        return FALSE;
    char raw[8192];
    DWORD got = 0;
    BOOL ok = ReadFile(file, raw, sizeof(raw) - 2, &got, NULL);
    CloseHandle(file);
    if (!ok)
        return FALSE;
    raw[got] = raw[got + 1] = 0;
    /* Written as UTF-16 with a byte order mark; Windows keeps it that way. */
    if (got >= 2 && (unsigned char)raw[0] == 0xFF && (unsigned char)raw[1] == 0xFE)
        return wcsstr((const wchar_t *)(raw + 2), MARKER) != NULL;
    char narrow[128];
    WideCharToMultiByte(CP_ACP, 0, MARKER, -1, narrow, sizeof(narrow), NULL, NULL);
    return strstr(raw, narrow) != NULL;
}

static int install(const wchar_t *inf, const wchar_t *hardware_id) {
    BOOL reboot = FALSE;
    /* Forced: Logitech's driver is signed and so outranks ours, and without the flag
     * Windows would keep it and report success. */
    if (!UpdateDriverForPlugAndPlayDevicesW(NULL, hardware_id, inf, INSTALLFLAG_FORCE,
                                            &reboot)) {
        DWORD error = GetLastError();
        if (error == ERROR_NO_SUCH_DEVINST) {
            wprintf(L"No Harmony 900, 1000 or 1100 is plugged in.\n");
            return 1;
        }
        if (error == ERROR_CANCELLED || error == ERROR_AUTHENTICODE_PUBLISHER_NOT_TRUSTED
            || error == (DWORD)TRUST_E_SUBJECT_NOT_TRUSTED) {
            wprintf(L"Windows was told not to install the driver.\n");
            return 2;
        }
        SetLastError(error);
        return failed(L"install the WinUSB driver");
    }
    wprintf(reboot ? L"Installed; Windows wants a restart.\n" : L"Installed.\n");
    return 0;
}

static int remove_ours(const wchar_t *hardware_id) {
    int removed = 0;
    HDEVINFO set = SetupDiGetClassDevsW(NULL, L"USB", NULL, DIGCF_ALLCLASSES);
    if (set == INVALID_HANDLE_VALUE)
        return failed(L"list the USB devices");
    SP_DEVINFO_DATA dev;
    dev.cbSize = sizeof(dev);
    for (DWORD index = 0; SetupDiEnumDeviceInfo(set, index, &dev); index++) {
        if (!has_id(set, &dev, hardware_id))
            continue;
        if (!SetupDiCallClassInstaller(DIF_REMOVE, set, &dev)) {
            SetupDiDestroyDeviceInfoList(set);
            return failed(L"remove the remote's driver");
        }
        removed++;
    }
    SetupDiDestroyDeviceInfoList(set);

    /* Then our INF itself, or the next scan would choose it again. Only files with our
     * marker line are touched. */
    wchar_t pattern[MAX_PATH], path[MAX_PATH];
    UINT length = GetWindowsDirectoryW(pattern, MAX_PATH);
    if (!length || length > MAX_PATH - 20)
        return failed(L"find the Windows folder");
    wcscat(pattern, L"\\INF\\oem*.inf");
    WIN32_FIND_DATAW found;
    HANDLE search = FindFirstFileW(pattern, &found);
    if (search != INVALID_HANDLE_VALUE) {
        do {
            GetWindowsDirectoryW(path, MAX_PATH);
            wcscat(path, L"\\INF\\");
            wcscat(path, found.cFileName);
            if (is_ours(path) && !SetupUninstallOEMInfW(found.cFileName, SUOI_FORCEDELETE,
                                                       NULL))
                wprintf(L"Could not delete %ls (error 0x%08lX).\n", found.cFileName,
                        (unsigned long)GetLastError());
        } while (FindNextFileW(search, &found));
        FindClose(search);
    }

    DEVINST root;
    if (CM_Locate_DevNodeW(&root, NULL, CM_LOCATE_DEVNODE_NORMAL) == CR_SUCCESS)
        CM_Reenumerate_DevNode(root, CM_REENUMERATE_SYNCHRONOUS);
    wprintf(L"Removed from %d device(s).\n", removed);
    return 0;
}

int wmain(int argc, wchar_t **argv) {
    if (argc == 4 && wcscmp(argv[1], L"install") == 0)
        return install(argv[2], argv[3]);
    if (argc == 3 && wcscmp(argv[1], L"remove") == 0)
        return remove_ours(argv[2]);
    wprintf(L"usage: afterglow-winusb install <inf> <hardware id>\n"
            L"       afterglow-winusb remove <hardware id>\n");
    return 64;
}
