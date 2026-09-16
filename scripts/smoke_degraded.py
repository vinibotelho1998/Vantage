"""Smoke do pior cenario: maquina sem sensores, sem GPU dedicada e sem FPS.

E' o que acontece num PC onde o LibreHardwareMonitor nao sobe, onde nao existe
NVML, ou onde o usuario abriu o app sem jogo nenhum. O app tem que continuar
util e honesto: nunca inventar numero, nunca quebrar, e dizer o que falta.

Falha com traceback se qualquer tela quebrar, e lista o que ficou sem dado para
a gente olhar se a tela ainda faz sentido assim.

    python scripts/smoke_degraded.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "vantage-dev"))
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from smoke_ui import StubApp  # noqa: E402

from vantage import theme  # noqa: E402
from vantage.ui.main_window import VIEW_CLASSES  # noqa: E402


class LhmMudo:
    """LibreHardwareMonitor que nao subiu, com a explicacao que o usuario ve."""

    error = ("O .NET Desktop Runtime nao esta instalado. "
             "Instale o .NET Desktop Runtime 8 (x64) e abra o app de novo.")

    def tree(self):
        return []

    def start(self):
        pass


class FpsParado:
    status = "nenhum jogo apresentando quadros"
    restarts = 0
    running = True

    def snapshot(self):
        return {}

    def apps(self):
        return []

    def frametimes(self, _pid, seconds=None):
        return []

    def samples(self, _pid):
        return []

    def stream(self, _pid):
        return None


class PingMudo:
    target_label = "8.8.8.8"
    following_game = False


def snapshot_pelado() -> dict:
    """O que o coletor entrega quando nada responde: chaves presentes, valores None."""
    return {
        "ts": 0, "lhm_ok": False,
        "cpu_name": "CPU", "cpu_pct": 12.0, "cpu_temp": None, "cpu_mhz": None,
        "cpu_watts": None, "cpu_fan": None, "cpu_volts": None,
        "cpu_core_loads": [], "cpu_core_clocks": [], "cpu_core_temps": [],
        "uptime": 900, "processes": 180,
        "ram_used": 7.8, "ram_total": 16.0, "ram_avail": 8.2, "ram_pct": 48.0,
        "ram_freq": None, "swap_used": 0.4, "swap_total": 4.0, "swap_pct": 10.0,
        "disk_used": 210.0, "disk_total": 480.0, "disk_pct": 43.0,
        "disk_r": 0.0, "disk_w": 0.0, "nvme_temp": None,
        "disks": [{"mount": "C:\\", "device": "C:", "fstype": "NTFS",
                   "used": 210.0, "total": 480.0, "pct": 43.0}],
        "net_dl": 0.0, "net_ul": 0.0, "net_total_dl": 0.0, "net_total_ul": 0.0,
        "ping_ms": None, "ping_jitter": None, "packet_loss": None,
        "battery": None, "fans": [],
        "gpu": None,          # sem GPU dedicada / sem leitura nenhuma
    }


def main() -> int:
    qt = QApplication(sys.argv)
    theme.set_scale(1.0)
    app = StubApp(qt)
    app.lhm = LhmMudo()
    app.fps = FpsParado()
    app.ping = PingMudo()
    app._stream = None
    app._data = snapshot_pelado()
    app._bench_result = None

    print("cenario: sem sensores, sem GPU, sem jogo\n")
    falhas: list[str] = []
    for cls in VIEW_CLASSES:
        try:
            view = cls(app)
            view.resize(1500, 850)
            view.on_settings_changed()
            view.on_system(app._data)
            view.on_fps()
            pix = QPixmap(view.size())
            view.render(pix)
            print(f"  {cls.key:<11} ok")
        except Exception as e:  # noqa: BLE001
            import traceback
            falhas.append(f"{cls.key}: {e}\n{traceback.format_exc()}")
            print(f"  {cls.key:<11} QUEBROU")

    # o overlay tambem precisa aguentar o vazio
    try:
        from vantage.ui.overlay import GameOverlay
        ov = GameOverlay(app)
        ov.refresh()
        pix = QPixmap(ov.sizeHint())
        ov.render(pix)
        print("  overlay     ok")
    except Exception as e:  # noqa: BLE001
        import traceback
        falhas.append(f"overlay: {e}\n{traceback.format_exc()}")
        print("  overlay     QUEBROU")

    if falhas:
        print("\nFALHAS:\n" + "\n\n".join(falhas))
        return 1
    print("\nsmoke degradado: nada quebrou sem sensores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
