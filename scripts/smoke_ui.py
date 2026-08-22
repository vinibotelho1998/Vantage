"""Smoke test da UI: monta a janela, alimenta dados sinteticos e pinta cada tela.

Roda sem display (QT_QPA_PLATFORM=offscreen) e falha com traceback se qualquer
view quebrar ao receber um snapshot completo, vazio ou parcial.
"""
from __future__ import annotations

import math
import os
import random
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Dados isolados: script de desenvolvimento nunca pode gravar por cima do
# settings.json de verdade (ja' apagou atalhos de jogo uma vez).
os.environ.setdefault("DBXSTATS_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "dbxstats-dev"))
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dbxstats.core import frames as fr  # noqa: E402
from dbxstats.core.frames import FrameStream  # noqa: E402
from dbxstats.core.series import Accumulator, History  # noqa: E402


def fake_snapshot(i: int) -> dict:
    load = 45 + 35 * math.sin(i / 7.0)
    return {
        "ts": i, "lhm_ok": True,
        "static": {"cpu_name": "Ryzen 7 7800X3D", "cores": 8, "threads": 16,
                   "os": "Windows 11", "cpu_base_mhz": 4200},
        "cpu_name": "Ryzen 7 7800X3D", "cpu_pct": load,
        "cpu_cores_pct": [random.uniform(5, 95) for _ in range(16)],
        "cpu_core_loads": [random.uniform(5, 95) for _ in range(16)],
        "cpu_core_clocks": [4800 + random.uniform(-200, 200) for _ in range(16)],
        "cpu_core_temps": [60 + random.uniform(0, 15) for _ in range(8)],
        "cpu_mhz": 4800, "cpu_mhz_avg": 4600, "cpu_temp": 62 + load / 8,
        "cpu_temp_cores": 58 + load / 9, "cpu_temp_package": 62 + load / 8,
        "cpu_watts": 45 + load / 2, "cpu_watts_cores": 30, "cpu_volts": 1.21,
        "cpu_volts_src": "rail", "cpu_volts_rail": "Voltage #1", "cpu_vid": 1.19,
        "cpu_fan": 1200, "fans": [1200, 900], "board_name": "B650 Tomahawk",
        "uptime": 3600 * 5 + i, "processes": 260,
        "ram_used": 18.4, "ram_total": 32.0, "ram_avail": 13.6, "ram_pct": 57.5,
        "ram_cached": 4.2, "ram_freq": 6000,
        "ram_info": {"modules": 2, "manufacturer": "G.Skill", "part": "F5-6000", "type": "DDR5"},
        "ram_temp": 41.5,
        "ram_modules": [{"slot": "DIMM #1", "temp": 41.5, "high": 55.0, "critical": 85.0,
                         "model": "G.Skill F5-6000 (#1)"},
                        {"slot": "DIMM #3", "temp": 39.0, "high": 55.0, "critical": 85.0,
                         "model": "G.Skill F5-6000 (#3)"}],
        "game_pid": 4242, "game_name": "game.exe",
        "game_ram_private": 9400.0, "game_ram_wset": 8100.0,
        "game_vram": 7100.0,
        "swap_used": 2.1, "swap_total": 8.0, "swap_pct": 26.0,
        "disk_used": 780.0, "disk_total": 1863.0, "disk_pct": 42.0,
        "disk_r": 1.4e7, "disk_w": 4.2e6,
        "disks": [{"mount": "C:\\", "device": "C:", "fstype": "NTFS", "used": 780.0,
                   "total": 1863.0, "pct": 42.0, "temp": 44.0, "life": 98.0,
                   "model": "Samsung 990 Pro"},
                  {"mount": "D:\\", "device": "D:", "fstype": "NTFS", "used": 1200.0,
                   "total": 4000.0, "pct": 30.0}],
        "nvme_temp": 44,
        "net_dl": 2.4e6, "net_ul": 3.1e5, "net_total_dl": 8.2e10, "net_total_ul": 4.1e9,
        "ping_ms": 18.4, "ping_jitter": 1.7, "packet_loss": 0.0,
        "ping_best": 15.0, "ping_worst": 44.0,
        "battery": None,
        "gpu": {
            "name": "NVIDIA GeForce RTX 4070", "usage": min(99, load + 15), "temp": 66,
            "temp_hotspot": 78, "temp_vram": 70, "fan_rpm": 1500, "fan_pct": 45,
            "freq": 2745, "mem_freq": 10501, "mem_ctrl": 42, "video_engine": 0,
            "volts": 1.05, "vram_used": 7400, "vram_total": 12282, "vram_pct": 60.2,
            "watts": 180.0, "watts_estimated": False, "power_limit": 220.0,
            "encoder": 0, "decoder": 0, "pcie_tx": 12000, "pcie_rx": 24000,
            "throttle": [], "others": [],
            "static": {"driver": "566.36", "vbios": "95.04.2f", "pcie_gen": 4,
                       "pcie_width": 16, "power_limit": 220.0, "temp_slowdown": 88},
        },
    }


def fake_stream(pid: int = 4242) -> FrameStream:
    samples = []
    t = 0.0
    for i in range(2500):
        ms = 6.9 + random.gauss(0, 0.6) + (18.0 if i % 400 == 0 else 0.0)
        ms = max(1.5, ms)
        t += ms / 1000.0
        samples.append((t, ms, ms * 0.55, ms * 0.93, ms * 0.95, 12.0, ms, float("nan")))
    metrics = fr.compute(samples, 1.0)
    return FrameStream(pid=pid, app="game.exe", present_mode="Hardware: Independent Flip",
                       sync_interval=0, last_seen=0.0, metrics=metrics), samples


class StubApp:
    """Controlador falso: mesma superficie usada pelas views, sem threads."""

    def __init__(self, qt) -> None:
        from dbxstats.config import Settings
        from dbxstats.sensors.lhm import SensorNode
        self.qt = qt
        self.settings = Settings()
        self.stats = Accumulator()
        self.history = History(300)
        self.bench_history = [{"time": "01/01 10:00", "game": "game.exe", "avg": 144.0,
                               "low1": 110.0, "low01": 92.0, "smooth": 84.0}]
        self._stream, self._samples = fake_stream()
        self._data = fake_snapshot(0)
        self.fps = _StubFps(self._stream, self._samples)
        self.lhm = _StubLhm([
            SensorNode("CPU/Temperature/Core", "AMD Ryzen", "Cpu", "Core",
                       "Temperature", "°C", 62.0),
            SensorNode("CPU/Load/Total", "AMD Ryzen", "Cpu", "CPU Total",
                       "Load", "%", 41.0),
        ])
        self.procs = _StubProcs()
        self.ping = _StubPing()
        self._bench_result = {
            "_rev": 1, "game": "game.exe", "metrics": self._stream.metrics,
            "frametimes": [s[1] for s in self._samples], "samples": self._samples,
            "system": {"cpu": (55.0, 88.0), "gpu": (92.0, 99.0)}}

    def active_stream(self):
        return self._stream

    def last_data(self):
        return self._data

    def fps_hint(self):
        return "nenhum jogo apresentando quadros"

    def clear_stats(self):
        pass

    def restart_capture(self):
        pass

    def set_fps_pin(self, name):
        pass

    def set_fps_window(self, seconds):
        pass

    def save_settings(self):
        pass

    def open_settings(self, tab=0):
        pass

    def toggle_overlay(self):
        pass

    def notify(self, *_a):
        pass

    def notify_tray_hint(self):
        pass

    def benchmark_active(self):
        return False

    def benchmark_state(self):
        return {"active": False, "elapsed": 0.0, "total": 60.0, "frames": 0, "game": ""}

    def benchmark_last(self):
        return self._bench_result

    def benchmark_export(self):
        return None

    def benchmark_start(self, _s):
        pass

    def benchmark_stop(self):
        pass

    def show_view(self, _k):
        pass

    def quit(self):
        pass


class _StubFps:
    def __init__(self, stream, samples):
        self._stream = stream
        self._samples = samples
        self.status = "capturando"
        self.restarts = 0
        self.running = True

    def snapshot(self):
        return {self._stream.pid: self._stream}

    def apps(self):
        return [(self._stream.pid, "game.exe", 144.0)]

    def frametimes(self, _pid, seconds=None):
        return [s[1] for s in self._samples]

    def samples(self, _pid):
        return self._samples


class _StubLhm:
    def __init__(self, nodes):
        self._nodes = nodes

    def tree(self):
        return self._nodes


class _StubPing:
    target_label = "game.exe"
    following_game = True


class _StubProcs:
    def snapshot(self):
        from dbxstats.sensors.procs import ProcInfo
        return [ProcInfo(i, f"proc{i}.exe", 12.0 - i, 300.0, 24, i == 0) for i in range(12)]

    def totals(self):
        return 260, 3400


def main() -> int:
    from dbxstats import theme
    from dbxstats.ui import style
    from dbxstats.ui.main_window import VIEW_CLASSES

    qt = QApplication(sys.argv)
    qt.setStyleSheet(style.build_qss("cyan"))
    app = StubApp(qt)

    for i in range(40):
        d = fake_snapshot(i)
        gpu = d["gpu"]
        for key, value in (("cpu_pct", d["cpu_pct"]), ("cpu_temp", d["cpu_temp"]),
                           ("cpu_watts", d["cpu_watts"]), ("cpu_mhz", d["cpu_mhz"]),
                           ("gpu_pct", gpu["usage"]), ("gpu_temp", gpu["temp"]),
                           ("gpu_watts", gpu["watts"]), ("gpu_mhz", gpu["freq"]),
                           ("gpu_mem_mhz", gpu["mem_freq"]), ("vram_pct", gpu["vram_pct"]),
                           ("ram_pct", d["ram_pct"]), ("swap_pct", d["swap_pct"]),
                           ("disk_r", d["disk_r"]), ("disk_w", d["disk_w"]),
                           ("net_dl", d["net_dl"]), ("net_ul", d["net_ul"]),
                           ("ping_ms", d["ping_ms"]), ("packet_loss", 0.0),
                           ("fps", 144.0), ("fps_low1", 110.0)):
            app.history.push(key, value)
            app.stats.update(key, value)
    app.stats.update("CPU/Temperature/Core", 62.0)
    app.stats.update("CPU/Load/Total", 41.0)

    failures = []
    for cls in VIEW_CLASSES:
        view = cls(app)
        view.resize(1600, 900)
        for payload in (app.last_data(), {}, {"cpu_pct": 10.0}):
            try:
                view.on_settings_changed()
                view.on_system(payload)
                view.on_fps()
            except Exception as e:  # noqa: BLE001
                import traceback
                failures.append(f"{cls.key}: {e}\n{traceback.format_exc()}")
        try:
            pix = QPixmap(view.size())
            view.render(pix)
        except Exception as e:  # noqa: BLE001
            import traceback
            failures.append(f"{cls.key} render: {e}\n{traceback.format_exc()}")
        print(f"  view {cls.key:<11} ok")

    # sem jogo em foco
    app._stream = None
    for cls in VIEW_CLASSES:
        view = cls(app)
        try:
            view.on_system(app.last_data())
            view.on_fps()
        except Exception as e:  # noqa: BLE001
            import traceback
            failures.append(f"{cls.key} (sem jogo): {e}\n{traceback.format_exc()}")
    print("  cenario sem jogo ok")

    # popup de confirmar telas: conta pra tras e reverte sozinho no fim
    from dbxstats.ui.confirm import ConfirmRevertDialog
    try:
        dlg = ConfirmRevertDialog("1920x1080 @ 180 Hz", 3)
        pix = QPixmap(dlg.sizeHint())
        dlg.render(pix)
        dlg._tick()
        dlg._tick()
        dlg._tick()
        if dlg._kept:
            failures.append("confirm: devia ter revertido sozinho ao fim do relogio")
        dlg2 = ConfirmRevertDialog("teste", 5)
        dlg2._keep()
        if not dlg2._kept:
            failures.append("confirm: botao Manter nao marcou a escolha")
        print("  popup de telas  ok")
    except Exception as e:  # noqa: BLE001
        import traceback
        failures.append(f"confirm: {e}\n{traceback.format_exc()}")

    theme.set_scale(1.0)
    if failures:
        print("\nFALHAS:\n" + "\n\n".join(failures))
        return 1
    print("\nsmoke UI: tudo certo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
