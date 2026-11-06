"""Telemetria Linux sem elevação: hwmon, DRM e CPUFreq."""
import re
from pathlib import Path

import psutil
from .lhm import SensorNode


def _text(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _number(path, scale=1):
    try:
        return int(_text(path)) / scale
    except ValueError:
        return None


class LinuxSensors:
    def __init__(self):
        self._nodes = []
        self.cpu = next((line.split(":", 1)[1].strip() for line in _text(Path("/proc/cpuinfo")).splitlines()
                         if line.startswith("model name")), "")
        self.cards = sorted(d / "device" for d in Path("/sys/class/drm").glob("card[0-9]*")
                            if re.fullmatch(r"card\d+", d.name) and (d / "device").exists())
        self.board = _text(Path("/sys/class/dmi/id/board_name"))
        self.gpu = next((c for c in self.cards if (c / "gpu_busy_percent").exists()), None)
        if self.gpu:
            self.gpu_name = _text(self.gpu / "product_name") or self._gpu_name(self.gpu)

    @staticmethod
    def _gpu_name(device):
        import subprocess
        try:
            result = subprocess.run(["lspci", "-s", device.resolve().name], capture_output=True,
                                    text=True, timeout=2, check=True)
            text = result.stdout.partition(": ")[2].strip()
            if text:
                return text
        except (OSError, subprocess.SubprocessError):
            pass
        return f"{(device / 'driver').resolve().name} · {_text(device / 'device')}"

    @property
    def ready(self):
        return bool(self._nodes)

    @property
    def error(self):
        return "" if self.ready else "O kernel ainda não publicou sensores hwmon legíveis."

    def start(self):
        pass

    def close(self):
        pass

    def tree(self):
        return self._nodes.copy()

    def read(self):
        nodes = []
        result = {"cpu_name": self.cpu, "board_name": self.board}
        try:
            clocks = psutil.cpu_freq(percpu=True) or []
        except (OSError, NotImplementedError):
            clocks = []
        if clocks:
            result.update(cpu_core_clocks=[f.current for f in clocks], cpu_mhz_max=max(f.current for f in clocks),
                          cpu_mhz_avg=sum(f.current for f in clocks) / len(clocks))
        cpu_temps = []
        for hw in Path("/sys/class/hwmon").glob("hwmon*"):
            chip = _text(hw / "name")
            cpu = chip in ("k10temp", "coretemp", "zenpower", "cpu_thermal")
            parent = (hw / "device").resolve()
            gpu = self.gpu is not None and parent == self.gpu.resolve()
            # hwmonN muda entre boots e duas unidades NVMe podem ter o mesmo modelo.
            identity = parent if (hw / "device").exists() else hw.resolve().parent.parent
            title = chip
            if chip == "nvme":
                title = f"{_text(parent / 'model') or chip} ({parent.name})"
            for prefix, kind, unit, scale in (("temp", "Temperature", "°C", 1000), ("fan", "Fan", "RPM", 1),
                                               ("power", "Power", "W", 1000000), ("in", "Voltage", "V", 1000),
                                               ("freq", "Clock", "MHz", 1000000)):
                for entry in hw.glob(prefix + "*_input"):
                    value = _number(entry, scale)
                    if value is None or (prefix == "temp" and not -10 < value < 160):
                        continue
                    name = entry.name.removesuffix("_input")
                    label = _text(hw / (name + "_label")) or name
                    hw_type = "Cpu" if cpu else ("GpuAmd" if gpu else ("Storage" if chip == "nvme" else "Hardware"))
                    key = f"{identity}/{chip}/{name}"
                    nodes.append(SensorNode(key, title, hw_type, label, kind, unit, value))
                    if cpu and prefix == "temp":
                        cpu_temps.append((label, value))
                    if gpu and prefix == "temp":
                        field = {"edge": "gpu_temp", "junction": "gpu_temp_hotspot", "mem": "gpu_temp_vram"}.get(label)
                        if field:
                            result[field] = value
                    if gpu and prefix == "freq":
                        field = {"sclk": "gpu_freq", "mclk": "gpu_mem_freq"}.get(label)
                        if field:
                            result[field] = value
                    if gpu and prefix == "fan":
                        result["gpu_fan_rpm"] = value
                    if chip == "nvme" and prefix == "temp" and (label == "Composite" or name == "temp1"):
                        result["nvme_temp"] = max(result.get("nvme_temp", value), value)
        if cpu_temps:
            packages = [v for n, v in cpu_temps if n.startswith(("Package", "Tctl", "Tdie"))]
            result["cpu_temp"] = max(packages or [v for _, v in cpu_temps])
            if packages:
                result["cpu_temp_package"] = max(packages)
        if self.gpu:
            gpu = self.gpu
            result.update(gpu_ok=True, gpu_name=self.gpu_name, gpu_list=[self.gpu_name],
                          gpu_usage=_number(gpu / "gpu_busy_percent"),
                          gpu_vram_used=_number(gpu / "mem_info_vram_used", 2**20),
                          gpu_vram_total=_number(gpu / "mem_info_vram_total", 2**20))
            for power in gpu.glob("hwmon/hwmon*/power1_average"):
                result["gpu_watts"] = _number(power, 1000000)
        self._nodes = nodes
        return result
