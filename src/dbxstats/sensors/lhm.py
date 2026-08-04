"""Leitura de sensores via LibreHardwareMonitorLib (.NET / pythonnet).

Alem do dicionario curado usado pelos cards, expoe a arvore completa de sensores
(estilo HWMonitor) numa unica varredura por ciclo.
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass

from .. import log, paths

_log = log.get("lhm")

_CPU_TEMP_PRIORITY = (
    "CCD", "Core (Tctl/Tdie)", "Tctl/Tdie", "Tdie",
    "CPU Package", "Package", "Core Max", "Core Average",
)

_GPU_DISCRETE_KW = ("rtx", "gtx", "rx ", " arc", "radeon pro", "quadro", "tesla", "geforce")
_GPU_INTEGRATED_KW = ("uhd graphics", "iris", "radeon(tm) graphics", "radeon graphics",
                      "hd graphics", "vega")

UNITS = {
    "Voltage": "V", "Current": "A", "Power": "W", "Clock": "MHz",
    "Temperature": "°C", "Load": "%", "Frequency": "Hz", "Fan": "RPM",
    "Flow": "L/h", "Control": "%", "Level": "%", "Factor": "",
    "Data": "GB", "SmallData": "MB", "Throughput": "B/s", "TimeSpan": "s",
    "Energy": "mWh", "Noise": "dBA",
}

HW_LABELS = {
    "Cpu": "Processador", "GpuNvidia": "GPU NVIDIA", "GpuAmd": "GPU AMD",
    "GpuIntel": "GPU Intel", "Memory": "Memória", "Motherboard": "Placa-mãe",
    "SuperIO": "Controlador (Super I/O)", "Storage": "Armazenamento",
    "Network": "Rede", "Cooler": "Water cooler", "Psu": "Fonte", "Battery": "Bateria",
}


@dataclass(frozen=True)
class SensorNode:
    key: str
    hardware: str
    hw_type: str
    name: str
    kind: str
    unit: str
    value: float


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
        self._tree: list[SensorNode] = []
        self._tree_lock = threading.Lock()

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
            c.IsControllerEnabled = True
            c.IsPsuEnabled = True
            c.IsBatteryEnabled = True
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
        """Varre todo o hardware uma vez: devolve o dict curado e atualiza a arvore."""
        if not self._ready:
            return {}
        result: dict = {}
        gpus: list[dict] = []
        tree: list[SensorNode] = []
        try:
            with self._lock:
                if self._computer is None:
                    return {}
                hw_list = list(self._computer.Hardware)
            for hw in hw_list:
                hw.Update()
                self._dispatch(hw, result, gpus)
                self._collect_tree(hw, tree)
                for sub in hw.SubHardware:
                    self._collect_tree(sub, tree, parent=str(hw.Name))
            self._pick_gpu(result, gpus)
            result["gpu_list"] = [g.get("name", "GPU") for g in gpus]
            with self._tree_lock:
                self._tree = tree
        except Exception as e:
            _log.debug("erro lendo LHM: %s", e)
        return result

    def tree(self) -> list[SensorNode]:
        with self._tree_lock:
            return list(self._tree)

    def close(self) -> None:
        with self._lock:
            if self._computer is not None:
                try:
                    self._computer.Close()
                except Exception:
                    pass
                self._computer = None
                self._ready = False

    # ── arvore completa ──────────────────────────────────────────────────────
    def _collect_tree(self, hw, out: list[SensorNode], parent: str = "") -> None:
        hw_type = str(hw.HardwareType)
        hw_name = str(hw.Name)
        label = f"{parent} · {hw_name}" if parent else hw_name
        for s in hw.Sensors:
            value = s.Value
            if value is None:
                continue
            kind = str(s.SensorType)
            name = str(s.Name)
            out.append(SensorNode(
                key=f"{label}/{kind}/{name}", hardware=label, hw_type=hw_type,
                name=name, kind=kind, unit=UNITS.get(kind, ""), value=float(value)))

    # ── leitura curada ───────────────────────────────────────────────────────
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
        result.setdefault("cpu_name", str(hw.Name))
        temps_by_name: dict[str, float] = {}
        core_temps: list[float] = []
        core_clocks: list[float] = []
        core_loads: list[tuple[int, float]] = []
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
            elif st == "Load":
                if name == "CPU Total":
                    result["cpu_pct_lhm"] = round(f, 1)
                elif name.startswith("CPU Core #") and "Thread" not in name:
                    core_loads.append((_core_index(name), round(f, 1)))
            elif st == "Power":
                if name in ("Package", "CPU Package") and f > 0:
                    result["cpu_watts"] = round(f, 1)
                elif name in ("CPU Cores", "Cores") and f > 0:
                    result["cpu_watts_cores"] = round(f, 1)
            elif st == "Fan" and f > 0:
                result.setdefault("cpu_fan", int(f))
            elif st == "Voltage" and ("Core" in name or "VID" in name):
                result.setdefault("cpu_volts", round(f, 3))

        temp = None
        for key in _CPU_TEMP_PRIORITY:
            matches = [v for nm, v in temps_by_name.items() if key in nm and v > 0]
            if matches:
                temp = max(matches)
                break
        if temp is None and core_temps:
            valid = [t for t in core_temps if t > 0]
            temp = max(valid) if valid else None
        if temp is not None and temp > 0:
            result["cpu_temp"] = round(temp, 1)
        if core_clocks:
            result["cpu_mhz_max"] = int(max(core_clocks))
            result["cpu_core_clocks"] = [int(c) for c in core_clocks]
        if core_loads:
            result["cpu_core_loads"] = [v for _, v in sorted(core_loads)]
        if core_temps:
            result["cpu_core_temps"] = [round(t, 1) for t in core_temps]

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
            elif st == "Temperature" and "Hot Spot" in name and f > 0:
                g["temp_hotspot"] = int(f)
            elif st == "Temperature" and "Memory" in name and f > 0:
                g["temp_vram"] = int(f)
            elif st == "Power" and f > 0 and "watts" not in g:
                g["watts"] = round(f, 1)
            elif st == "Clock" and name == "GPU Core":
                g["freq"] = int(f)
            elif st == "Clock" and "GPU Memory" in name:
                g["mem_freq"] = int(f)
            elif st == "Load" and name == "GPU Core":
                g["usage"] = int(f)
            elif st == "Load" and "Memory Controller" in name:
                g["mem_ctrl"] = int(f)
            elif st == "Load" and "Video Engine" in name:
                g["video_engine"] = int(f)
            elif st == "SmallData" and "GPU Memory Used" in name:
                g["vram_used"] = int(f)
            elif st == "SmallData" and "GPU Memory Total" in name:
                g["vram_total"] = int(f)
            elif st == "Fan" and "GPU Fan" in name:
                g["fan_rpm"] = int(f)
            elif st == "Control" and "GPU Fan" in name:
                g["fan_pct"] = int(f)
            elif st == "Voltage" and "GPU Core" in name:
                g["volts"] = round(f, 3)
        gpus.append(g)

    def _pick_gpu(self, result: dict, gpus: list) -> None:
        if not gpus:
            return
        best = max(gpus, key=_gpu_score)
        result["gpu_ok"] = True
        result["gpu_name"] = best.get("name", "GPU")
        result["_gpu_type"] = best.get("type")
        for key in ("temp", "temp_hotspot", "temp_vram", "freq", "mem_freq", "usage",
                    "mem_ctrl", "video_engine", "vram_used", "vram_total",
                    "fan_rpm", "fan_pct", "watts", "volts"):
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
            if st == "Data" and "Virtual" in name and "Used" in name:
                result["swap_used_lhm"] = round(f, 2)
            elif st == "Data" and "Used" in name:
                result["ram_used_lhm"] = round(f, 2)
            elif st == "Data" and "Available" in name:
                result["ram_avail_lhm"] = round(f, 2)
            elif st == "Load" and "Virtual" in name:
                result["swap_pct_lhm"] = round(f, 1)
            elif st == "Load" and "Memory" in name:
                result["ram_pct_lhm"] = round(f, 1)

    def _read_motherboard(self, hw, result: dict) -> None:
        result.setdefault("board_name", str(hw.Name))
        fans: list[int] = []
        for sub in hw.SubHardware:
            sub.Update()
            for s in sub.Sensors:
                if s.Value is None:
                    continue
                st = str(s.SensorType)
                nl = str(s.Name).lower()
                f = float(s.Value)
                if st == "Fan" and f > 0:
                    fans.append(int(f))
                    if "cpu" in nl:
                        result["cpu_fan"] = int(f)
                elif st == "Temperature" and ("system" in nl or "motherboard" in nl) and f > 0:
                    result.setdefault("board_temp", round(f, 1))
        if fans:
            result["fans"] = fans
            result.setdefault("cpu_fan", fans[0])

    def _read_storage(self, hw, result: dict) -> None:
        disks = result.setdefault("disks_lhm", [])
        entry = {"name": str(hw.Name)}
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature" and ("Composite" in name or name == "Temperature") and f > 0:
                entry["temp"] = round(f, 1)
            elif st == "Data" and "Total Space" in name:
                entry["total"] = round(f, 1)
            elif st == "Load" and "Used Space" in name:
                entry["used_pct"] = round(f, 1)
            elif st == "Level" and "Remaining Life" in name:
                entry["life"] = round(f, 1)
            elif st == "Data" and "Host Writes" in name:
                entry["written"] = round(f, 1)
            elif st == "Throughput" and "Read" in name:
                entry["read"] = f
            elif st == "Throughput" and "Write" in name:
                entry["write"] = f
        disks.append(entry)
        if "temp" in entry and "nvme_temp" not in result:
            result["nvme_temp"] = entry["temp"]


def _core_index(name: str) -> int:
    try:
        return int(name.split("#")[1].split()[0])
    except (IndexError, ValueError):
        return 999
