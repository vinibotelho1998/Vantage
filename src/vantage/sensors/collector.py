"""Coletor unico: funde LHM, NVML, psutil, WMI e ping num snapshot por ciclo.

Roda numa thread propria e publica um dicionario imutavel; a UI nunca toca em
nenhuma fonte de sensor diretamente.
"""
from __future__ import annotations

import os
import platform
import re
import threading
import time

import psutil

from .. import log
if os.name == "nt":
    from ..platform import gpumem
from ..core.series import Ema

_log = log.get("collector")

_IGNORED_FS = {"cdrom", ""}


def _nome_gpu(name: str) -> str:
    return " ".join(str(name or "").casefold().split())


def _mesma_gpu(lhm: dict, nvml: dict) -> bool:
    """Um nome so identifica a placa quando e unico nos dois inventarios completos."""
    if lhm.get("_gpu_type") != "GpuNvidia":
        return False
    name = _nome_gpu(lhm.get("gpu_name", ""))
    if not name or name != _nome_gpu(nvml.get("name", "")):
        return False
    nomes_nvml = nvml.get("names")
    nomes_lhm = lhm.get("gpu_list")
    if not isinstance(nomes_nvml, (list, tuple)) or not isinstance(nomes_lhm, (list, tuple)):
        return False
    return (sum(_nome_gpu(n) == name for n in nomes_nvml) == 1
            and sum(_nome_gpu(n) == name for n in nomes_lhm) == 1)


class Collector:
    def __init__(self, lhm, gpu, ping, update_interval: float = 1.0) -> None:
        self._lhm = lhm
        self._gpu = gpu
        self._ping = ping
        self._interval = update_interval
        self._data: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners: list = []

        self._ram_freq: int | None = None
        self._ram_info: dict | None = None
        self._sys_drive = (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/"
        self._prev_net = psutil.net_io_counters()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_time = time.monotonic()
        self._disk_cache: list[dict] = []
        self._disk_cache_at = float("-inf")
        self._disk_volume_devices: dict[str, str] = {}
        self._gpu_watts_ema = Ema(0.35)
        self._gpu_identity = None
        self._gpu_wmi: dict[str, dict] = {}
        self._game_ram = _GameMemory()
        self._game_vram = gpumem.ProcessVram() if os.name == "nt" else None
        """VRAM do mesmo processo; ver platform/gpumem.py."""
        self._static = _static_info()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="collector", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def set_interval(self, value: float) -> None:
        self._interval = max(0.2, float(value))

    def set_game_pid(self, pid: int | None) -> None:
        """Diz de qual processo medir a RAM. Zero (ou None) desliga a medida."""
        self._game_ram.follow(pid)
        if self._game_vram is not None:
            self._game_vram.follow(pid)

    def snapshot(self) -> dict:
        with self._lock:
            return self._data

    @property
    def static(self) -> dict:
        return dict(self._static)

    def _loop(self) -> None:
        # O WMI que esta thread consulta (frequencia da RAM, driver da GPU) e'
        # COM, e COM recusa thread que nao se apresentou a ele: sem isto as duas
        # consultas falhavam com "CoInitialize nao foi chamado", o erro ia para
        # o log de depuracao e o cache guardava a falha para sempre.
        com = os.name == "nt" and _entrar_no_com()
        try:
            psutil.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None, percpu=True)
            time.sleep(0.6)
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    data = self._collect()
                    with self._lock:
                        self._data = data
                except Exception:
                    _log.exception("erro no ciclo de coleta")
                elapsed = time.monotonic() - started
                self._stop.wait(max(0.05, self._interval - elapsed))
        finally:
            if com:
                _sair_do_com()

    def _collect(self) -> dict:
        now = time.monotonic()
        dt = max(now - self._prev_time, 0.001)

        cpu_pct = psutil.cpu_percent(interval=None)
        cores = psutil.cpu_percent(interval=None, percpu=True)
        lhm = self._lhm.read()

        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()

        net = psutil.net_io_counters()
        # O contador soma todas as interfaces: uma VPN que desliga tira os bytes
        # dela de uma vez e a diferenca sairia negativa, como no disco.
        dl = max(0.0, (net.bytes_recv - self._prev_net.bytes_recv) / dt)
        ul = max(0.0, (net.bytes_sent - self._prev_net.bytes_sent) / dt)
        self._prev_net = net

        dio = psutil.disk_io_counters()
        dr = dw = 0.0
        if dio and self._prev_disk:
            dr = max(0.0, (dio.read_bytes - self._prev_disk.read_bytes) / dt)
            dw = max(0.0, (dio.write_bytes - self._prev_disk.write_bytes) / dt)
        self._prev_disk = dio
        self._prev_time = now

        sys_disk = _safe_usage(self._sys_drive)
        gpu = self._collect_gpu(lhm)
        ping = self._ping.read()

        data = {
            "ts": time.time(),
            "lhm_ok": self._lhm.ready,
            "static": self._static,

            "cpu_name": lhm.get("cpu_name") or self._static.get("cpu_name", "CPU"),
            "cpu_pct": cpu_pct,
            "cpu_cores_pct": cores,
            "cpu_mhz": lhm.get("cpu_mhz_max") or lhm.get("cpu_mhz_avg"),
            "cpu_mhz_avg": lhm.get("cpu_mhz_avg"),
            "cpu_core_clocks": lhm.get("cpu_core_clocks"),
            "cpu_core_temps": lhm.get("cpu_core_temps"),
            "cpu_core_loads": lhm.get("cpu_core_loads") or cores,
            "cpu_temp": lhm.get("cpu_temp"),
            # As duas leituras que o overlay poe lado a lado. Elas eram lidas no
            # LHM e nunca copiadas para ca': o painel caia no cpu_temp para os
            # dois lados e a celula dupla nunca aparecia em maquina nenhuma.
            "cpu_temp_cores": lhm.get("cpu_temp_cores"),
            "cpu_temp_package": lhm.get("cpu_temp_package"),
            "cpu_watts": lhm.get("cpu_watts"),
            "cpu_watts_cores": lhm.get("cpu_watts_cores"),
            "cpu_volts": lhm.get("cpu_volts"),
            "cpu_volts_src": lhm.get("cpu_volts_src"),
            "cpu_volts_rail": lhm.get("cpu_volts_rail"),
            "cpu_vid": lhm.get("cpu_vid"),
            "cpu_fan": lhm.get("cpu_fan"),
            "fans": lhm.get("fans"),
            "board_name": lhm.get("board_name"),
            "board_temp": lhm.get("board_temp"),

            "uptime": time.time() - psutil.boot_time(),
            "processes": len(psutil.pids()),

            "ram_used": ram.used / 1024 ** 3,
            "ram_total": ram.total / 1024 ** 3,
            "ram_avail": ram.available / 1024 ** 3,
            "ram_pct": ram.percent,
            "ram_cached": getattr(ram, "cached", max(0.0, ram.total - ram.used - ram.available)) / 1024 ** 3,
            "ram_freq": self._ram_freq_mhz() if os.name == "nt" else None,
            "ram_info": self._ram_info,
            "ram_temp": lhm.get("ram_temp"),
            "ram_modules": lhm.get("ram_modules"),
            "swap_used": swap.used / 1024 ** 3,
            "swap_total": swap.total / 1024 ** 3,
            "swap_pct": swap.percent,

            "disk_used": sys_disk[0], "disk_total": sys_disk[1], "disk_pct": sys_disk[2],
            "disk_r": dr, "disk_w": dw,
            "disks": self._disks(lhm),
            "nvme_temp": lhm.get("nvme_temp"),

            "net_dl": dl, "net_ul": ul,
            "net_total_dl": net.bytes_recv, "net_total_ul": net.bytes_sent,
            "ping_ms": ping.get("ms"), "ping_jitter": ping.get("jitter"),
            "packet_loss": ping.get("loss"),
            "ping_best": ping.get("best"), "ping_worst": ping.get("worst"),

            "gpu": gpu,
            "battery": _battery(),
        }
        # Sem jogo, as chaves nao existem: o card some inteiro em vez de mostrar
        # um zero que se parece com "o jogo nao usa RAM".
        data.update(self._game_ram.read() or {})
        # So' publica com o jogo identificado: sem pid, o numero seria de
        # ninguem, e a linha do overlay apareceria zerada sem explicacao.
        if data.get("game_pid") and self._game_vram is not None:
            vram_jogo = self._game_vram.read_mb()
            if vram_jogo is not None:
                data["game_vram"] = vram_jogo
        return data

    def _collect_gpu(self, lhm: dict) -> dict | None:
        nvml = self._gpu.read_nvml()
        identity = getattr(self._gpu, "identity", {})
        usar_nvml = (not lhm.get("gpu_ok") or _mesma_gpu(lhm, identity))
        if not usar_nvml:
            nvml = None
        if not lhm.get("gpu_ok") and not nvml:
            self._gpu_watts_ema.reset()
            self._gpu_identity = None
            return None

        gpu: dict = {}
        if lhm.get("gpu_ok"):
            # Toda leitura ausente sai como None, nunca como 0 nem como 1. Zero e'
            # uma medida ("a placa esta' parada") e 1 MiB de VRAM total e' truthy:
            # os dois derrotam as guardas de "esta maquina nao publica isso" la' na
            # frente e viram "0.0/0.0GB" e "Livre 1 MB" numa iGPU, que nomeia os
            # sensores de memoria de outro jeito e nunca casa com estas chaves.
            gpu = {
                "name": lhm.get("gpu_name", "GPU"),
                "usage": lhm.get("gpu_usage"),
                "temp": lhm.get("gpu_temp"),
                "temp_hotspot": lhm.get("gpu_temp_hotspot"),
                "temp_vram": lhm.get("gpu_temp_vram"),
                "fan_rpm": lhm.get("gpu_fan_rpm"),
                "fan_pct": lhm.get("gpu_fan_pct"),
                "freq": lhm.get("gpu_freq"),
                "mem_freq": lhm.get("gpu_mem_freq"),
                "mem_ctrl": lhm.get("gpu_mem_ctrl"),
                "vram_volts": lhm.get("gpu", {}).get("vram_volts")
                if isinstance(lhm.get("gpu"), dict) else None,
                "video_engine": lhm.get("gpu_video_engine"),
                "volts": lhm.get("gpu_volts"),
                "vram_used": lhm.get("gpu_vram_used"),
                "vram_total": lhm.get("gpu_vram_total"),
            }
        if nvml:
            for key, value in nvml.items():
                if value is not None and gpu.get(key) is None:
                    gpu[key] = value
            gpu.setdefault("throttle", nvml.get("throttle") or [])

        nome = _nome_gpu(gpu.get("name", ""))
        nomes_lhm = [_nome_gpu(n) for n in (lhm.get("gpu_list") or [])]
        ambiguo = lhm.get("gpu_ok") and nomes_lhm.count(nome) > 1
        nvml_id = identity.get("uuid") or identity.get("pci_bus_id") or nome
        chave = ("lhm", lhm.get("_gpu_type"), nome, nvml_id if usar_nvml else None) if lhm.get("gpu_ok") else (
            "nvml", nvml_id)
        if chave != self._gpu_identity or ambiguo:
            self._gpu_watts_ema.reset()
            reiniciar = getattr(self._gpu, "reset_estimate", None)
            if reiniciar is not None:
                reiniciar()
            self._gpu_identity = chave

        real_w = lhm.get("gpu_watts") if lhm.get("gpu_ok") else None
        if real_w is None and nvml:
            real_w = nvml.get("watts")
        if real_w is None and usar_nvml:
            real_w = self._gpu.watts_smi()
        estimated = False
        if real_w is None and usar_nvml:
            real_w = self._gpu.watts_estimate(gpu.get("usage"), gpu.get("freq"))
            estimated = real_w is not None
        if real_w is None:
            self._gpu_watts_ema.reset()
        smoothed = self._gpu_watts_ema.push(real_w)
        gpu["watts"] = None if smoothed is None else round(smoothed, 1)
        gpu["watts_estimated"] = estimated
        static = dict(self._gpu.static) if usar_nvml else {}
        gpu["power_limit"] = static.get("power_limit")
        # motivos de throttle so existem via NVML; em AMD/Intel nao ha o que reportar
        gpu["throttle_supported"] = bool(usar_nvml and self._gpu.nvml_ok)

        vram = self._gpu.vram() if usar_nvml else None
        if vram:
            for key, value in zip(("vram_used", "vram_total"), vram):
                if gpu.get(key) is None:
                    gpu[key] = value
        usado, total = gpu.get("vram_used"), gpu.get("vram_total")
        gpu["vram_pct"] = (100.0 * usado / total
                           if usado is not None and total else None)
        gpu.setdefault("throttle", [])
        gpu.setdefault("name", "GPU")
        wmi_info = self._gpu_wmi_info(gpu.get("name", "")) if os.name == "nt" else {}
        for key, value in wmi_info.items():
            static.setdefault(key, value)
        gpu["static"] = static
        gpu["others"] = [n for n in (lhm.get("gpu_list") or []) if n != gpu.get("name")]
        return gpu

    def _gpu_wmi_info(self, name: str) -> dict:
        """Driver e modo de video via WMI: funciona em AMD e Intel, onde nao ha NVML."""
        nome = _nome_gpu(name)
        if not nome:
            return {}
        if nome in self._gpu_wmi:
            return dict(self._gpu_wmi[nome])
        found: dict = {}
        try:
            import wmi
            candidatos = [c for c in wmi.WMI().Win32_VideoController()
                          if _nome_gpu(c.Name or "") == nome]
            if len(candidatos) == 1:
                c = candidatos[0]
                entry = {
                    "driver": (c.DriverVersion or "").strip(),
                    "adapter": c.Name.strip(),
                    "video_mode": _video_mode(c.VideoModeDescription),
                    "refresh": c.CurrentRefreshRate,
                }
                found = entry
        except Exception as e:
            _log.debug("Win32_VideoController falhou: %s", e)
        self._gpu_wmi[nome] = found
        return dict(found)

    def _disks(self, lhm: dict) -> list[dict]:
        now = time.monotonic()
        if now - self._disk_cache_at >= 20.0:
            self._disk_cache = _partitions()
            self._disk_volume_devices = _disk_volume_devices() if os.name == "nt" else {}
            self._disk_cache_at = now
        sensors: dict[str, list[dict]] = {}
        for disk in lhm.get("disks_lhm") or []:
            device = _physical_disk_device(disk.get("physical_device"))
            if device:
                sensors.setdefault(device, []).append(disk)
        out = []
        for part in self._disk_cache:
            used, total, pct = _safe_usage(part["mount"])
            entry = dict(part)
            entry.update({"used": used, "total": total, "pct": pct,
                          "temp": None, "life": None, "model": None})
            volume = _logical_disk_device(part["mount"])
            # Uma pasta montada pode pertencer a outro disco, apesar de usar C:.
            if volume and volume == _logical_disk_device(part["device"]):
                physical = self._disk_volume_devices.get(volume)
                matches = sensors.get(physical, [])
                # Identidade ausente ou duplicada nunca e' resolvida por ordem/nome.
                if len(matches) == 1:
                    sensor = matches[0]
                    entry.update(temp=sensor.get("temp"), life=sensor.get("life"),
                                 model=sensor.get("name"))
            out.append(entry)
        return out

    def _ram_freq_mhz(self) -> int | None:
        if self._ram_freq is not None:
            return self._ram_freq
        try:
            import wmi
            mems = list(wmi.WMI().Win32_PhysicalMemory())
            if mems:
                spd = mems[0].ConfiguredClockSpeed or mems[0].Speed
                self._ram_freq = int(spd) if spd else 0
                self._ram_info = {
                    "modules": len(mems),
                    "manufacturer": (mems[0].Manufacturer or "").strip(),
                    "part": (mems[0].PartNumber or "").strip(),
                    "type": _ram_type(getattr(mems[0], "SMBIOSMemoryType", None)),
                }
        except Exception as e:
            _log.debug("ram freq via WMI falhou: %s", e)
            self._ram_freq = 0
        return self._ram_freq or None


class _GameMemory:
    """RAM do processo do jogo, com o handle preso entre os ciclos.

    Duas medidas, porque uma so' mente: o working set e' o que esta' residente
    AGORA, e o Windows o poda quando a janela perde o foco: medindo o
    RadeonSoftware o working set marcou 50 MB enquanto o processo mantinha
    1150 MB comprometidos, 23x de diferenca. Num jogo em alt-tab isso viraria um
    grafico despencando sem que o jogo tivesse liberado nada. Private bytes e' o
    que o processo pediu para si e nao colapsa com poda; e' o numero de manchete,
    e o working set fica como pressao real sobre a RAM fisica.

    O uss (memory_full_info) seria mais correto ainda em teoria e esta' fora de
    proposito na pratica: exige elevacao, custa 1,7-2,8 ms por leitura e chegou a
    140 ms num processo de 13,5 GB, inviavel num laco de 1 Hz. O handle fica
    preso porque um process_iter completo custa 72,7 ms, contra 0,005 ms de um
    memory_info() no objeto ja' aberto.
    """

    def __init__(self) -> None:
        self._wanted = 0
        """Escrito pela thread da UI, lido pela do coletor: so' um int."""
        self._pid = 0
        self._proc: psutil.Process | None = None
        self._name = ""

    def follow(self, pid: int | None) -> None:
        self._wanted = int(pid or 0)

    def read(self) -> dict | None:
        pid = self._wanted
        if pid != self._pid:
            self._pid, self._proc, self._name = pid, None, ""
        if not pid:
            return None
        try:
            if self._proc is None:
                self._proc = psutil.Process(pid)
                self._name = self._proc.name()
            mem = self._proc.memory_info()
        except (psutil.Error, OSError):
            # Jogo fechou (ou o Windows negou): descarta o handle e nao publica
            # nada. A proxima leitura tenta de novo se o pid continuar de pe'.
            self._proc = None
            return None
        dados = {
            "game_pid": pid,
            "game_name": self._name,
            "game_ram_wset": round(mem.rss / 1024 ** 2, 1),
        }
        private = getattr(mem, "private", None)
        if private:
            dados["game_ram_private"] = round(private / 1024 ** 2, 1)
        return dados


def _entrar_no_com() -> bool:
    """Apresenta a thread atual ao COM, no modelo livre.

    Livre, e nao apartamento: esta thread nao roda laco de mensagens, e e' o
    mesmo modelo que o .NET assume quando o LibreHardwareMonitor e' chamado
    daqui. Falhar nao derruba nada: so' as consultas WMI ficam sem resposta.
    """
    try:
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        return True
    except Exception as e:                                   # noqa: BLE001
        _log.debug("COM indisponivel na thread do coletor: %s", e)
        return False


def _sair_do_com() -> None:
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:                                        # noqa: BLE001
        pass


def _safe_usage(mount: str) -> tuple[float, float, float]:
    try:
        u = psutil.disk_usage(mount)
        return u.used / 1024 ** 3, u.total / 1024 ** 3, u.percent
    except OSError:
        return 0.0, 0.0, 0.0


def _partitions() -> list[dict]:
    out = []
    for p in psutil.disk_partitions(all=False):
        if p.fstype.lower() in _IGNORED_FS:
            continue
        out.append({"mount": p.mountpoint, "device": p.device, "fstype": p.fstype})
    return out


def _physical_disk_device(value) -> str | None:
    device = str(value or "").strip().upper()
    return device if re.fullmatch(r"\\\\\.\\PHYSICALDRIVE[0-9]+", device) else None


def _logical_disk_device(value) -> str | None:
    device = str(value or "").strip().upper()
    return device[:2] if re.fullmatch(r"[A-Z]:[\\/]?", device) else None


def _disk_volume_devices() -> dict[str, str]:
    """Relaciona volume -> disco fisico pelas duas associacoes do WMI.

    Um volume distribuido entre discos nao tem um unico sensor de temperatura.
    Falha parcial da consulta tambem invalida o mapa, para nao esconder extents.
    """
    volumes: dict[str, set[str | None]] = {}
    try:
        import wmi
        for disk in wmi.WMI().Win32_DiskDrive():
            device = _physical_disk_device(disk.DeviceID)
            for partition in disk.associators(wmi_association_class="Win32_DiskDriveToDiskPartition"):
                for logical in partition.associators(wmi_association_class="Win32_LogicalDiskToPartition"):
                    volume = _logical_disk_device(logical.DeviceID)
                    if volume:
                        volumes.setdefault(volume, set()).add(device)
    except Exception as exc:
        _log.debug("mapeamento de volumes via WMI falhou: %s", exc)
        return {}
    return {volume: next(iter(devices)) for volume, devices in volumes.items()
            if len(devices) == 1 and None not in devices}


def _battery() -> dict | None:
    try:
        b = psutil.sensors_battery()
    except Exception:
        return None
    if b is None:
        return None
    return {"pct": round(b.percent, 1), "plugged": bool(b.power_plugged),
            "secsleft": None if b.secsleft in (-1, -2) else b.secsleft}


def _video_mode(raw: str | None) -> str:
    """WMI devolve '1920 x 1080 x 4294967296 cores'; so a resolucao interessa."""
    parts = [p.strip() for p in (raw or "").split(" x ")]
    return f"{parts[0]} × {parts[1]}" if len(parts) >= 2 else (raw or "").strip()


def _ram_type(code) -> str:
    return {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5",
            35: "DDR5"}.get(code, "")


def _static_info() -> dict:
    info = {
        "cpu_name": platform.processor() or "CPU",
        "cores": psutil.cpu_count(logical=False) or 0,
        "threads": psutil.cpu_count(logical=True) or 0,
        "os": f"{platform.system()} {platform.release()}",
        "build": platform.version(),
        "hostname": platform.node(),
        "arch": platform.machine(),
    }
    try:
        freq = psutil.cpu_freq()
        if freq:
            info["cpu_base_mhz"] = int(freq.max or freq.current or 0)
    except Exception:
        pass
    try:
        import wmi
        cpu = next(iter(wmi.WMI().Win32_Processor()), None)
        if cpu is not None and cpu.Name:
            info["cpu_name"] = cpu.Name.strip()
    except Exception:
        pass
    return info
