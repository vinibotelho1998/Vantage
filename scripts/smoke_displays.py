"""Smoke da camada de telas: so leitura, nao altera nada.

    .venv\\Scripts\\python.exe scripts\\smoke_displays.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vantage.platform import displays as D  # noqa: E402


def main() -> int:
    ds = D.list_displays()
    print(f"{len(ds)} telas fisicas\n")
    for d in ds:
        flag = "PRIMARIA" if d.primary else ("ligada" if d.active else "desligada")
        nativa = f"{d.native[0]}x{d.native[1]}" if d.native else "?"
        print(f"{d.device:14} {d.name:14} {flag:10} {d.summary:22} "
              f"nativa={nativa:10} modos={len(d.modes)}")

    print("\n=== maior taxa por resolucao, marcando o que passa do painel ===")
    for d in ds:
        best: dict[tuple[int, int], int] = {}
        for m in d.modes:
            best[(m.width, m.height)] = max(best.get((m.width, m.height), 0), m.refresh)
        top = sorted(best.items(), key=lambda kv: (kv[0][0] * kv[0][1], kv[1]), reverse=True)[:6]
        print(f"  {d.name}:")
        for (w, h), hz in top:
            marca = "  <- escalonado (VSR)" if d.is_upscaled(D.Mode(w, h, hz)) else ""
            print(f"      {w}x{h} @ {hz} Hz{marca}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
