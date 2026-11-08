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


# Nome que o kernel da' ao chip (hwmon/name) para um titulo que a pessoa entende. O
# que nao esta' aqui aparece com o nome cru, como antes.
_CHIPS = (
    (re.compile(r"k10temp|zenpower"), "CPU AMD ({chip})"),
    (re.compile(r"coretemp"), "CPU Intel ({chip})"),
    (re.compile(r"gigabyte_wmi|asus_wmi|asus-ec-sensors|msi_wmi"), "Placa-mãe ({chip})"),
    (re.compile(r"nct\d+|it8\d+|w83\d+|f718\d+"), "Super I/O da placa-mãe ({chip})"),
    (re.compile(r"acpitz"), "Zona térmica ACPI"),
    (re.compile(r"r8169|r8125|igc|e1000e|igb|ixgbe|atlantic|tg3"), "Ethernet ({chip})"),
    (re.compile(r"iwlwifi|mt79\d+|mt76\w*|ath\d+k|rtw\w+|brcmfmac"), "Wi-Fi ({chip})"),
    (re.compile(r"prom\d+_xhci|xhci"), "Controlador USB ({chip})"),
    (re.compile(r"spd5118|jc42|ee1004"), "Memória RAM ({chip})"),
    (re.compile(r"BAT\d|battery"), "Bateria ({chip})"),
    (re.compile(r"ucsi_.*"), "USB-C ({chip})"),
)
_NOMES_CANAL = {"temp": "Temperatura", "fan": "Ventoinha", "power": "Potência", "in": "Tensão", "freq": "Clock"}
_PCIE_GERACAO = {"2.5": 1, "5.0": 2, "8.0": 3, "16.0": 4, "32.0": 5, "64.0": 6}


def titulo_do_chip(chip):
    for padrao, modelo in _CHIPS:
        if padrao.match(chip):
            return modelo.format(chip=chip)
    return chip


def nome_do_canal(rotulo, canal):
    """'temp3' vira 'Temperatura 3'; um rotulo que o driver deu ao canal fica como esta'."""
    if rotulo != canal:
        return rotulo
    achado = re.fullmatch(r"([a-z]+)(\d+)", canal)
    if achado and achado.group(1) in _NOMES_CANAL:
        return f"{_NOMES_CANAL[achado.group(1)]} {achado.group(2)}"
    return rotulo


class LinuxSensors:
    def __init__(self, sys_root="/sys", proc_root="/proc"):
        self._nodes = []
        self._sys = Path(sys_root)
        self.cpu = next((line.split(":", 1)[1].strip() for line in _text(Path(proc_root) / "cpuinfo").splitlines()
                         if line.startswith("model name")), "")
        self.cards = sorted(d / "device" for d in (self._sys / "class/drm").glob("card[0-9]*")
                            if re.fullmatch(r"card\d+", d.name) and (d / "device").exists())
        self.board = _text(self._sys / "class/dmi/id/board_name")
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
                # "Advanced Micro Devices, Inc. [AMD/ATI] Navi 48 [Radeon RX 9070 XT] (rev c0)":
                # o ultimo grupo entre colchetes e' o nome de vitrine da placa.
                nome = re.search(r"\[([^\[\]]+)\](?:\s*\(rev [0-9a-f]+\))?\s*$", text)
                return nome.group(1) if nome else text
        except (OSError, subprocess.SubprocessError):
            pass
        return f"{(device / 'driver').resolve().name} · {_text(device / 'device')}"

    @staticmethod
    def _gpu_static(device):
        """Driver, VBIOS, PCIe e limites que o kernel publica em sysfs, sem root."""
        static = {}
        try:
            if (device / "driver").is_symlink():
                static["driver"] = (device / "driver").resolve().name
        except OSError:
            pass
        vbios = _text(device / "vbios_version")
        if vbios:
            static["vbios"] = vbios
        velocidade = _text(device / "current_link_speed").split(" ")[0]
        largura = _text(device / "current_link_width")
        if velocidade in _PCIE_GERACAO and largura.isdigit():
            static["pcie_gen"], static["pcie_width"] = _PCIE_GERACAO[velocidade], int(largura)
        for cap in sorted(device.glob("hwmon/hwmon*/power1_cap")):
            limite = _number(cap, 1000000)
            if limite:
                static["power_limit"] = limite
        for crit in sorted(device.glob("hwmon/hwmon*/temp1_crit")):
            limite = _number(crit, 1000)
            if limite:
                static["temp_slowdown"] = limite
        return static

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
        for hw in sorted((self._sys / "class/hwmon").glob("hwmon*")):
            chip = _text(hw / "name")
            cpu = chip in ("k10temp", "coretemp", "zenpower", "cpu_thermal")
            parent = (hw / "device").resolve()
            gpu = self.gpu is not None and parent == self.gpu.resolve()
            # hwmonN muda entre boots e duas unidades NVMe podem ter o mesmo modelo.
            identity = parent if (hw / "device").exists() else hw.resolve().parent.parent
            title = getattr(self, "gpu_name", chip) if gpu else titulo_do_chip(chip)
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
                    label = nome_do_canal(_text(hw / (name + "_label")) or name, name)
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
                        maximo = _number(hw / (name + "_max"))
                        if maximo:
                            result["gpu_fan_pct"] = min(100.0, 100.0 * value / maximo)
                    if gpu and prefix == "in" and label == "vddgfx":
                        result["gpu_volts"] = value
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
            busy = _number(gpu / "mem_busy_percent")
            if busy is not None:
                result["gpu_mem_ctrl"] = busy
            result["gpu_static"] = self._gpu_static(gpu)
        self._nodes = nodes
        return result
