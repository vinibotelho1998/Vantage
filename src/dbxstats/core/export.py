"""Exportacao de dados para CSV (sensores, benchmark e log de sessao)."""
from __future__ import annotations

import csv
import time
from pathlib import Path

from .. import log, paths
from . import frames as fr

_log = log.get("export")


def reports_dir() -> Path:
    d = paths.data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _write(name: str, header: list[str], rows) -> Path | None:
    path = reports_dir() / name
    try:
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(header)
            writer.writerows(rows)
        _log.info("relatorio salvo em %s", path)
        return path
    except OSError as e:
        _log.warning("falha exportando %s: %s", name, e)
        return None


def export_sensors(nodes, stats) -> Path | None:
    rows = []
    for node in nodes:
        agg = stats.get(node.key)
        mn, av, mx = agg if agg else ("", "", "")
        rows.append([node.hardware, node.name, node.kind, node.unit,
                     _num(node.value), _num(mn), _num(av), _num(mx)])
    return _write(f"sensores-{_stamp()}.csv",
                  ["Hardware", "Sensor", "Tipo", "Unidade", "Atual", "Mínimo",
                   "Médio", "Máximo"], rows)


def export_frames(samples: list[tuple], game: str) -> Path | None:
    rows = []
    for s in samples:
        rows.append([_num(s[fr.T], 4), _num(s[fr.FT], 3), _num(s[fr.CPU_BUSY], 3),
                     _num(s[fr.GPU_BUSY], 3), _num(s[fr.GPU_TIME], 3),
                     _num(s[fr.DISP_LAT], 3), _num(s[fr.DISPLAYED], 3)])
    safe = "".join(c for c in game if c.isalnum() or c in "-_.") or "sessao"
    return _write(f"frames-{safe}-{_stamp()}.csv",
                  ["Tempo (s)", "Frametime (ms)", "CPU ocupada (ms)", "GPU ocupada (ms)",
                   "GPU total (ms)", "Latência display (ms)", "Tempo exibido (ms)"], rows)


def export_benchmark(summary: dict, game: str) -> Path | None:
    rows = [[key, _num(value)] for key, value in summary.items()
            if isinstance(value, (int, float))]
    safe = "".join(c for c in game if c.isalnum() or c in "-_.") or "sessao"
    return _write(f"benchmark-{safe}-{_stamp()}.csv", ["Métrica", "Valor"], rows)


def _num(value, decimals: int = 2) -> str:
    if value is None or value == "":
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v != v:  # NaN
        return ""
    return f"{v:.{decimals}f}".replace(".", ",")
