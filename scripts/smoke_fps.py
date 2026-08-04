"""Smoke do motor de FPS contra o PresentMon real.

Sem privilegio de administrador o PresentMon nao consegue abrir a sessao ETW; o
teste continua valido porque verifica que o supervisor sobrevive e reinicia sem
travar o processo. Com admin, mostra os jogos detectados e as metricas.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from dbxstats.sensors.fps import FpsEngine  # noqa: E402


def _n(value, decimals: int = 0) -> str:
    return "—" if value is None else f"{value:.{decimals}f}"


def main(seconds: int = 20) -> int:
    engine = FpsEngine(analysis_window=30.0)
    engine.start()
    try:
        for i in range(seconds):
            time.sleep(1)
            streams = engine.snapshot()
            line = f"[{i:02d}] status={engine.status!r} reinicios={engine.restarts}"
            if streams:
                for pid, s in sorted(streams.items()):
                    m = s.metrics
                    line += (f"\n      {s.app} (pid {pid}) {_n(m.fps_now)} fps"
                             f" · média {_n(m.fps_avg)} · 1% {_n(m.low_1)}"
                             f" · 0.1% {_n(m.low_01)} · ft {_n(m.ft_avg, 2)} ms"
                             f" · stutter {m.stutter_pct:.1f}% · {m.bottleneck}"
                             f" · {m.frames} frames · {s.present_mode}")
            else:
                line += "  (nenhum processo apresentando)"
            print(line, flush=True)
    finally:
        engine.stop()
    print("\nmotor encerrado sem travar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 20))
