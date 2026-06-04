"""Helpers win32 (ctypes) com prototypes corretos para x64 e multi-monitor."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

MONITOR_DEFAULTTONEAREST = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def _setup_prototypes() -> None:
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    if hasattr(user32, "GetWindowLongPtrW"):
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    shell32.IsUserAnAdmin.restype = wintypes.BOOL
    shell32.IsUserAnAdmin.argtypes = []


_setup_prototypes()


def _get_long(hwnd: int, idx: int) -> int:
    if hasattr(user32, "GetWindowLongPtrW"):
        return int(user32.GetWindowLongPtrW(hwnd, idx))
    return int(user32.GetWindowLongW(hwnd, idx))


def _set_long(hwnd: int, idx: int, value: int) -> int:
    if hasattr(user32, "SetWindowLongPtrW"):
        return int(user32.SetWindowLongPtrW(hwnd, idx, value))
    return int(user32.SetWindowLongW(hwnd, idx, value))


def keep_topmost(hwnd: int) -> None:
    if not hwnd:
        return
    user32.SetWindowPos(hwnd, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(executable: str, params: str) -> bool:
    try:
        rc = shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


def foreground_hwnd() -> int:
    return user32.GetForegroundWindow() or 0


def window_pid(hwnd: int) -> int:
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_pid() -> int:
    return window_pid(foreground_hwnd())


def _monitor_rect(hwnd: int) -> RECT | None:
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    return mi.rcMonitor


def is_foreground_fullscreen() -> tuple[bool, int]:
    hwnd = foreground_hwnd()
    if not hwnd:
        return False, 0
    rc = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return False, hwnd
    mon = _monitor_rect(hwnd)
    if mon is None:
        return False, hwnd
    covers = (rc.left <= mon.left and rc.top <= mon.top
              and rc.right >= mon.right and rc.bottom >= mon.bottom)
    return covers, hwnd


def set_clickthrough(hwnd: int, enabled: bool = True) -> None:
    if not hwnd:
        return
    style = _get_long(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    _set_long(hwnd, GWL_EXSTYLE, style)


def set_tool_window(hwnd: int) -> None:
    if not hwnd:
        return
    style = _get_long(hwnd, GWL_EXSTYLE)
    _set_long(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
