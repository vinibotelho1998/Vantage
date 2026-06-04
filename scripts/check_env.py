"""Verifica que a stack de runtime importa e expoe a API esperada."""
from __future__ import annotations

import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def check_imports() -> list[str]:
    failures: list[str] = []
    mods = {
        "psutil": "psutil", "wmi": "wmi", "pynvml": "pynvml",
        "pystray": "pystray", "PIL": "pillow", "clr": "pythonnet",
        "PySide6": "PySide6", "win32api": "pywin32",
    }
    for mod, dist in mods.items():
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "?")
            _ok(f"import {mod:10} ({dist}) v{ver}")
        except Exception as e:
            _fail(f"import {mod:10} ({dist}): {e}")
            failures.append(mod)
    return failures


def check_pynvml_api() -> list[str]:
    needed = [
        "nvmlInit", "nvmlDeviceGetHandleByIndex", "nvmlDeviceGetName",
        "nvmlDeviceGetUtilizationRates", "nvmlDeviceGetTemperature",
        "nvmlDeviceGetMemoryInfo", "nvmlDeviceGetClockInfo",
        "nvmlDeviceGetPowerUsage", "nvmlDeviceGetEnforcedPowerLimit",
        "nvmlDeviceGetMaxClockInfo", "NVML_TEMPERATURE_GPU",
        "NVML_CLOCK_GRAPHICS", "NVML_CLOCK_MEM",
    ]
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import pynvml
    except Exception as e:
        _fail(f"pynvml import: {e}")
        return ["pynvml"]
    missing = [n for n in needed if not hasattr(pynvml, n)]
    if missing:
        _fail(f"pynvml sem simbolos: {missing}")
        return missing
    _ok("pynvml API classica completa")
    return []


def check_pyside() -> list[str]:
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtGui, QtWidgets
        QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        QtGui.QColor("#0D1117")
        for cls in ("QPropertyAnimation", "QEasingCurve"):
            if not hasattr(QtCore, cls):
                _fail(f"PySide6 QtCore sem {cls}")
                return [cls]
        _ok(f"PySide6 Qt {QtCore.qVersion()} (QApplication + animacao)")
        return []
    except Exception as e:
        _fail(f"PySide6: {e}")
        return ["PySide6"]


def check_lhm() -> list[str]:
    lhm_dir = None
    for cand in (os.path.join(ROOT, "vendor", "lhm"), os.path.join(ROOT, "lhm")):
        if os.path.isdir(cand):
            lhm_dir = cand
            break
    if lhm_dir is None:
        _warn("pasta lhm/ nao encontrada")
        return []
    sys.path.insert(0, lhm_dir)
    try:
        import clr
        clr.AddReference(os.path.join(lhm_dir, "LibreHardwareMonitorLib"))
        from LibreHardwareMonitor.Hardware import Computer  # noqa: F401
        _ok(f"LibreHardwareMonitorLib carregada de {lhm_dir}")
        return []
    except Exception as e:
        _fail(f"LibreHardwareMonitorLib: {e}")
        return ["lhm"]


def main() -> int:
    print(f"Python {sys.version}")
    print(f"Projeto: {ROOT}\n")
    failures: list[str] = []
    failures += check_imports()
    failures += check_pynvml_api()
    failures += check_pyside()
    failures += check_lhm()
    print()
    if failures:
        _fail(f"Ambiente incompleto: {sorted(set(failures))}")
        return 1
    _ok("Ambiente completo e compativel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
