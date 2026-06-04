"""Leitura de sensores via LibreHardwareMonitorLib (.NET / pythonnet)."""
from __future__ import annotations

import os
import sys
import threading

from .. import log, paths

_log = log.get("lhm")

_CPU_TEMP_PRIORITY = (
    "Core (Tctl/Tdie)", "Tctl/Tdie", "Tdie",
    "CPU Package", "Package", "Core Max", "Core Average",
)

_GPU_DISCRETE_KW = ("rtx", "gtx", "rx ", " arc", "radeon pro", "quadro", "tesla", "geforce")
_GPU_INTEGRATED_KW = ("uhd graphics", "iris", "radeon(tm) graphics", "radeon graphics",
                      "hd graphics", "vega")


def _gpu_score(g: dict) -> tuple:
    name = g.get("name", "").lower()
    vram = g.get("vram_total", 0) or 0
    discrete = (g.get("type") == "GpuNvidia"
                or any(k in name for k in _GPU_DISCRETE_KW)
                or vram >= 3000)
    integrated = (any(k in name for k in _GPU_INTEGRATED_KW)
                  and not any(k in name for k in _GPU_DISCRETE_KW))
    rank = 1 if (discrete and not integrated) else 0
    return (rank, vram, g.get("usage", 0) or 0)


class LhmReader:
    def __init__(self) -> None:
        self._computer = None
        self._ready = False
        self._error = ""
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> str:
        return self._error

    def start(self) -> None:
        threading.Thread(target=self._init, name="lhm-init", daemon=True).start()

    def _init(self) -> None:
        try:
            lhm_dir = str(paths.lhm_dir())
            if lhm_dir not in sys.path:
                sys.path.insert(0, lhm_dir)
            import clr
            clr.AddReference(os.path.join(lhm_dir, "LibreHardwareMonitorLib"))
            from LibreHardwareMonitor.Hardware import Computer

            c = Computer()
            c.IsCpuEnabled = True
            c.IsGpuEnabled = True
            c.IsMemoryEnabled = True
            c.IsStorageEnabled = True
            c.IsMotherboardEnabled = True
            c.IsNetworkEnabled = False
            c.Open()
            with self._lock:
                self._computer = c
                self._ready = True
            _log.info("LHM aberto (%s)", lhm_dir)
        except Exception as e:
            self._error = str(e)
            _log.exception("falha inicializando LHM")

    def read(self) -> dict:
        if not self._ready:
            return {}
        result: dict = {}
        gpus: list[dict] = []
        try:
            with self._lock:
                if self._computer is None:
                    return {}
                hw_list = list(self._computer.Hardware)
            for hw in hw_list:
                hw.Update()
                self._dispatch(hw, result, gpus)
            self._pick_gpu(result, gpus)
        except Exception as e:
            _log.debug("erro lendo LHM: %s", e)
        return result

    def close(self) -> None:
        with self._lock:
            if self._computer is not None:
                try:
                    self._computer.Close()
                except Exception:
                    pass
                self._computer = None
                self._ready = False

    def _dispatch(self, hw, result: dict, gpus: list) -> None:
        hw_type = str(hw.HardwareType)
        if hw_type == "Cpu":
            self._read_cpu(hw, result)
        elif hw_type in ("GpuNvidia", "GpuAmd", "GpuIntel"):
            self._read_gpu(hw, hw_type, gpus)
        elif hw_type == "Memory":
            self._read_memory(hw, result)
        elif hw_type == "Motherboard":
            self._read_motherboard(hw, result)
        elif hw_type == "Storage":
            self._read_storage(hw, result)

    def _read_cpu(self, hw, result: dict) -> None:
        temps_by_name: dict[str, float] = {}
        core_temps: list[float] = []
        core_clocks: list[float] = []
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature":
                temps_by_name[name] = f
                if ("CCD" not in name and "Core" in name and "Max" not in name
                        and "Average" not in name and "Tctl" not in name):
                    core_temps.append(f)
            elif st == "Clock":
                if "Average)" in name and "Effective" not in name:
                    result["cpu_mhz_avg"] = int(f)
                elif "Core #" in name and "Effective" not in name:
                    core_clocks.append(f)
            elif st == "Load" and name == "CPU Total":
                result["cpu_pct_lhm"] = round(f, 1)
            elif st == "Power" and name in ("Package", "CPU Package") and f > 0:
                result["cpu_watts"] = round(f, 1)
            elif st == "Fan" and f > 0:
                result.setdefault("cpu_fan", int(f))

        temp = None
        for key in _CPU_TEMP_PRIORITY:
            match = next((v for nm, v in temps_by_name.items() if key in nm and v > 0), None)
            if match is not None:
                temp = match
                break
        if temp is None and core_temps:
            valid = [t for t in core_temps if t > 0]
            temp = max(valid) if valid else None
        if temp is not None and temp > 0:
            result["cpu_temp"] = round(temp, 1)
        if core_clocks:
            result["cpu_mhz_max"] = int(max(core_clocks))

    def _read_gpu(self, hw, hw_type: str, gpus: list) -> None:
        g: dict = {"name": str(hw.Name), "type": hw_type}
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature" and name == "GPU Core" and f > 0:
                g["temp"] = int(f)
            elif st == "Power" and f > 0 and "watts" not in g:
                g["watts"] = round(f, 1)
            elif st == "Clock" and name == "GPU Core":
                g["freq"] = int(f)
            elif st == "Clock" and "GPU Memory" in name:
                g["mem_freq"] = int(f)
            elif st == "Load" and name == "GPU Core":
                g["usage"] = int(f)
            elif st == "SmallData" and "GPU Memory Used" in name:
                g["vram_used"] = int(f)
            elif st == "SmallData" and "GPU Memory Total" in name:
                g["vram_total"] = int(f)
            elif st == "Fan" and "GPU Fan" in name:
                g["fan_rpm"] = int(f)
            elif st == "Control" and "GPU Fan" in name:
                g["fan_pct"] = int(f)
        gpus.append(g)

    def _pick_gpu(self, result: dict, gpus: list) -> None:
        if not gpus:
            return
        best = max(gpus, key=_gpu_score)
        result["gpu_ok"] = True
        result["gpu_name"] = best.get("name", "GPU")
        result["_gpu_type"] = best.get("type")
        for key in ("temp", "freq", "mem_freq", "usage",
                    "vram_used", "vram_total", "fan_rpm", "fan_pct", "watts"):
            if key in best:
                result["gpu_" + key] = best[key]

    def _read_memory(self, hw, result: dict) -> None:
        if str(hw.Name) != "Total Memory":
            return
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Data" and "Used" in name:
                result["ram_used_lhm"] = round(f, 2)
            elif st == "Data" and "Available" in name:
                result["ram_avail_lhm"] = round(f, 2)
            elif st == "Load" and "Memory" in name:
                result["ram_pct_lhm"] = round(f, 1)

    def _read_motherboard(self, hw, result: dict) -> None:
        for sub in hw.SubHardware:
            sub.Update()
            fan_idx = 0
            for s in sub.Sensors:
                if str(s.SensorType) != "Fan" or s.Value is None:
                    continue
                f = float(s.Value)
                nl = str(s.Name).lower()
                if "cpu" in nl and f > 0:
                    result["cpu_fan"] = int(f)
                elif fan_idx == 0 and not result.get("cpu_fan") and f > 0:
                    result["cpu_fan"] = int(f)
                fan_idx += 1

    def _read_storage(self, hw, result: dict) -> None:
        if result.get("disk_ok"):
            return
        result["disk_ok"] = True
        result["disk_name"] = str(hw.Name)
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature" and ("Composite" in name or name == "Temperature") and f > 0:
                result["nvme_temp"] = int(f)
            elif st == "Data" and "Total Space" in name:
                result["disk_total_lhm"] = round(f, 1)
            elif st == "Data" and "Free Space" in name:
                result["disk_free_lhm"] = round(f, 1)
            elif st == "Load" and "Used Space" in name:
                result["disk_pct_lhm"] = round(f, 1)
