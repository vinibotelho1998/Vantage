"""Smoke de integracao: monta o app (engine + UI) offscreen e roda ciclos."""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dbxstats.app import App


def main() -> int:
    qt = QApplication(sys.argv)
    app = App(qt)
    app.boot()

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(0.03)

    snap = app.last_data()
    if not snap:
        print("FAIL: nenhum snapshot coletado")
        app.quit()
        return 1
    print("snapshot keys:", ", ".join(sorted(snap)[:8]), "...")
    print(f"cpu={snap.get('cpu_pct')}% ram={snap.get('ram_pct')}% "
          f"gpu={(snap.get('gpu') or {}).get('usage')} ping={snap.get('ping_ms')}")
    print(f"lhm_ready={app.lhm.ready} nvml={app.gpu.nvml_ok} overlay={app.overlay_active()}")

    app.toggle_overlay()
    qt.processEvents()
    print(f"overlay apos toggle={app.overlay_active()}")

    app.quit()
    print("APP SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
