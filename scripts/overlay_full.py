"""Liga todas as metricas do overlay.

Settings antigo pode ter guardado uma lista curta, feita antes de existirem
metricas novas (grafico de FPS, frequencias). Rodar isto devolve o overlay
completo sem precisar marcar item por item nas configuracoes.

    python scripts/overlay_full.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from dbxstats.config import OVERLAY_METRICS, Settings  # noqa: E402


def main() -> int:
    cfg = Settings.load()
    cfg.overlay_metrics = [k for k, _ in OVERLAY_METRICS]
    cfg.overlay_enabled = True
    cfg.sanitize()
    cfg.save()
    print("overlay completo:", ", ".join(cfg.overlay_metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
