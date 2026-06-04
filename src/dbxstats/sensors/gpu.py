"""GPU NVIDIA via NVML, com nvidia-smi e estimativa como fallback de potencia."""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

from .. import log

_log = log.get("gpu")


class GpuReader:
    def __init__(self) -> None:
        self._pynvml = None
        self._hdl = None
        self._ok = False
        self._name: str | None = None
        self._watts_est: float | None = None
        self._smi_watts: float | None = None
        self._smi_lock = threading.Lock()
        self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import pynvml
            pynvml.nvmlInit()
            self._hdl = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._pynvml = pynvml
            self._ok = True
            _log.info("NVML inicializado")
        except Exception as e:
            _log.info("NVML indisponivel: %s", e)

    @property
    def nvml_ok(self) -> bool:
        return self._ok

    def start_smi(self) -> None:
        threading.Thread(target=self._smi_loop, name="nvidia-smi", daemon=True).start()

    def read_nvml(self) -> dict | None:
        if not self._ok:
            return None
        p = self._pynvml
        try:
            if not self._name:
                n = p.nvmlDeviceGetName(self._hdl)
                self._name = n.decode() if isinstance(n, bytes) else n
            util = p.nvmlDeviceGetUtilizationRates(self._hdl)
            temp = p.nvmlDeviceGetTemperature(self._hdl, p.NVML_TEMPERATURE_GPU)
            mem = p.nvmlDeviceGetMemoryInfo(self._hdl)
            freq = p.nvmlDeviceGetClockInfo(self._hdl, p.NVML_CLOCK_GRAPHICS)
            mfreq = p.nvmlDeviceGetClockInfo(self._hdl, p.NVML_CLOCK_MEM)
            try:
                watts = p.nvmlDeviceGetPowerUsage(self._hdl) / 1000.0
            except Exception:
                watts = None
            return {
                "name": self._name, "usage": util.gpu, "temp": temp,
                "vram_used": mem.used // 1024 ** 2, "vram_total": mem.total // 1024 ** 2,
                "freq": freq, "mem_freq": mfreq, "watts": watts,
            }
        except Exception as e:
            _log.debug("erro NVML: %s", e)
            return None

    def vram(self) -> tuple[int, int] | None:
        if not self._ok:
            return None
        try:
            mem = self._pynvml.nvmlDeviceGetMemoryInfo(self._hdl)
            return mem.used // 1024 ** 2, mem.total // 1024 ** 2
        except Exception:
            return None

    def watts_nvml(self) -> float | None:
        if not self._ok:
            return None
        try:
            return round(self._pynvml.nvmlDeviceGetPowerUsage(self._hdl) / 1000.0, 1)
        except Exception:
            return None

    def watts_smi(self) -> float | None:
        with self._smi_lock:
            return self._smi_watts

    def watts_estimate(self, usage=None, freq=None) -> float | None:
        if not self._ok:
            return None
        p = self._pynvml
        try:
            limit = p.nvmlDeviceGetEnforcedPowerLimit(self._hdl) / 1000.0
            if usage is None:
                usage = float(p.nvmlDeviceGetUtilizationRates(self._hdl).gpu)
            if freq is None:
                freq = float(p.nvmlDeviceGetClockInfo(self._hdl, p.NVML_CLOCK_GRAPHICS))
            max_clk = float(p.nvmlDeviceGetMaxClockInfo(self._hdl, p.NVML_CLOCK_GRAPHICS))
            util_r = max(0.0, min(1.0, float(usage) / 100.0))
            clk_r = max(0.0, min(1.0, (float(freq) / max_clk) if max_clk > 0 else util_r))
            idle = max(8.0, limit * 0.08)
            load = 0.70 * util_r + 0.30 * clk_r
            est = idle + (limit - idle) * (load ** 0.9)
            if self._watts_est is None:
                self._watts_est = est
            else:
                self._watts_est = (self._watts_est * 0.70) + (est * 0.30)
            return round(self._watts_est, 1)
        except Exception:
            return None

    def _smi_loop(self) -> None:
        candidates = [
            shutil.which("nvidia-smi"),
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]
        nsmi = next((p for p in candidates if p and os.path.exists(p)), None)
        if not nsmi:
            _log.info("nvidia-smi nao encontrado; fallback de watts desativado")
            return
        while True:
            try:
                out = subprocess.check_output(
                    [nsmi, "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                    timeout=2, creationflags=subprocess.CREATE_NO_WINDOW,
                    stderr=subprocess.DEVNULL)
                v = _parse_smi_watts(out.decode(errors="ignore"))
                if v is not None:
                    with self._smi_lock:
                        self._smi_watts = round(v, 1)
            except Exception as e:
                _log.debug("nvidia-smi: %s", e)
            time.sleep(1)


def _parse_smi_watts(text: str) -> float | None:
    for raw in text.splitlines():
        tok = raw.strip().replace(" W", "").replace(",", ".")
        if tok.lower() in ("n/a", "[n/a]", "[not supported]", ""):
            continue
        try:
            return float(tok)
        except ValueError:
            continue
    return None
