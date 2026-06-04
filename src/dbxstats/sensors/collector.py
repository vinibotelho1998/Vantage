"""Coletor unico: funde LHM, NVML, psutil, WMI e ping num snapshot por ciclo."""
from __future__ import annotations

import os
import threading
import time

import psutil

from .. import log

_log = log.get("collector")


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
        self._ram_freq: int | None = None
        self._sys_drive = os.environ.get("SystemDrive", "C:") + "\\"
        self._prev_net = psutil.net_io_counters()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_time = time.monotonic()

    def set_interval(self, value: float) -> None:
        self._interval = value

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        psutil.cpu_percent(interval=None)
        time.sleep(0.8)
        while not self._stop.is_set():
            try:
                d = self._collect()
                with self._lock:
                    self._data = d
            except Exception:
                _log.exception("erro no ciclo de coleta")
            self._stop.wait(max(0.1, self._interval))

    def _ram_freq_mhz(self) -> int | None:
        if self._ram_freq:
            return self._ram_freq
        try:
            import wmi
            mems = list(wmi.WMI().Win32_PhysicalMemory())
            if mems:
                spd = mems[0].ConfiguredClockSpeed or mems[0].Speed
                if spd:
                    self._ram_freq = int(spd)
        except Exception as e:
            _log.debug("ram freq via WMI falhou: %s", e)
        return self._ram_freq

    def _collect(self) -> dict:
        now = time.monotonic()
        dt = max(now - self._prev_time, 0.001)

        cpu_pct = psutil.cpu_percent(interval=None)
        lhm = self._lhm.read()
        cpu_mhz = lhm.get("cpu_mhz_max") or lhm.get("cpu_mhz_avg")

        ram = psutil.virtual_memory()

        net = psutil.net_io_counters()
        dl = (net.bytes_recv - self._prev_net.bytes_recv) / dt
        ul = (net.bytes_sent - self._prev_net.bytes_sent) / dt
        self._prev_net = net

        disk = psutil.disk_usage(self._sys_drive)
        dio = psutil.disk_io_counters()
        dr = dw = 0.0
        if dio and self._prev_disk:
            dr = (dio.read_bytes - self._prev_disk.read_bytes) / dt
            dw = (dio.write_bytes - self._prev_disk.write_bytes) / dt
        self._prev_disk = dio
        self._prev_time = now

        gpu = self._collect_gpu(lhm)
        ping_ms, loss = self._ping.read()

        uptime_s = int(time.monotonic())
        h, rem = divmod(uptime_s, 3600)
        m, s = divmod(rem, 60)
        uptime = f"{h:02d}:{m:02d}:{s:02d}" if h < 24 else f"{h // 24}d {h % 24:02d}:{m:02d}"

        return {
            "lhm_ok": self._lhm.ready,
            "cpu_pct": cpu_pct,
            "cpu_mhz": cpu_mhz,
            "cpu_temp": lhm.get("cpu_temp"),
            "cpu_watts": lhm.get("cpu_watts"),
            "cpu_fan": lhm.get("cpu_fan"),
            "uptime": uptime,
            "ram_used": ram.used / 1024 ** 3,
            "ram_total": ram.total / 1024 ** 3,
            "ram_avail": ram.available / 1024 ** 3,
            "ram_pct": ram.percent,
            "ram_freq": self._ram_freq_mhz(),
            "disk_used": disk.used / 1024 ** 3,
            "disk_total": disk.total / 1024 ** 3,
            "disk_pct": disk.percent,
            "disk_r": dr, "disk_w": dw,
            "nvme_temp": lhm.get("nvme_temp"),
            "net_dl": dl, "net_ul": ul,
            "ping_ms": ping_ms, "packet_loss": loss,
            "gpu": gpu,
        }

    def _collect_gpu(self, lhm: dict) -> dict | None:
        nsmi_w = self._gpu.watts_smi()
        if lhm.get("gpu_ok"):
            lhm_w = lhm.get("gpu_watts")
            nvml_w = self._gpu.watts_nvml()
            real_w = lhm_w if lhm_w is not None else (nvml_w if nvml_w is not None else nsmi_w)
            est_w = None if real_w is not None else self._gpu.watts_estimate(
                lhm.get("gpu_usage"), lhm.get("gpu_freq"))
            gpu = {
                "name": lhm.get("gpu_name", "GPU"),
                "usage": lhm.get("gpu_usage", 0),
                "temp": lhm.get("gpu_temp", 0),
                "fan_rpm": lhm.get("gpu_fan_rpm"),
                "fan_pct": lhm.get("gpu_fan_pct"),
                "watts": real_w if real_w is not None else est_w,
                "watts_estimated": (real_w is None and est_w is not None),
                "freq": lhm.get("gpu_freq", 0),
                "mem_freq": lhm.get("gpu_mem_freq", 0),
                "vram_used": lhm.get("gpu_vram_used", 0),
                "vram_total": lhm.get("gpu_vram_total", 1),
            }
            vram = self._gpu.vram()
            if vram:
                gpu["vram_used"], gpu["vram_total"] = vram
            return gpu

        gpu = self._gpu.read_nvml()
        if gpu:
            if gpu.get("watts") is None:
                gpu["watts"] = nsmi_w
            if gpu.get("watts") is None:
                gpu["watts"] = self._gpu.watts_estimate(gpu.get("usage"), gpu.get("freq"))
                gpu["watts_estimated"] = gpu.get("watts") is not None
            else:
                gpu["watts_estimated"] = False
        return gpu
