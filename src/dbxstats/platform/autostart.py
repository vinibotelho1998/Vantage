"""Inicializacao automatica com o Windows (HKCU Run)."""
from __future__ import annotations

import sys

from .. import log, paths

_log = log.get("autostart")
_RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_VALUE = "DBX Stats"


def _command() -> str:
    if paths.is_frozen():
        return f'"{sys.executable}"'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" -m dbxstats'


def set_enabled(enable: bool) -> None:
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            if enable:
                winreg.SetValueEx(key, _VALUE, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, _VALUE)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        _log.warning("autostart falhou: %s", e)
