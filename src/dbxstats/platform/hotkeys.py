"""Atalhos globais via RegisterHotKey (win32) + filtro de eventos nativo do Qt."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


class HotkeyManager(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()
        self._callbacks: dict[int, callable] = {}
        self._next_id = 1

    def register(self, mods: int, vk: int, callback) -> bool:
        hid = self._next_id
        if not user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
            return False
        self._callbacks[hid] = callback
        self._next_id += 1
        return True

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                cb = self._callbacks.get(int(msg.wParam))
                if cb is not None:
                    cb()
        return False, 0

    def unregister_all(self) -> None:
        for hid in self._callbacks:
            user32.UnregisterHotKey(None, hid)
        self._callbacks.clear()
