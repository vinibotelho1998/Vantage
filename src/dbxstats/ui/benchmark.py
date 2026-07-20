"""Modo benchmark: resume frametimes capturados e mostra o resultado."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout

from .. import theme
from .widgets import make_font


def summarize(frames: list[float]) -> dict | None:
    frames = [f for f in frames if 0 < f < 5000]
    n = len(frames)
    if n < 5:
        return None
    s = sorted(frames)
    avg = sum(frames) / n
    med = s[n // 2]
    return {
        "frames": n,
        "duration": sum(frames) / 1000,
        "fps_avg": 1000 / avg,
        "fps_1low": 1000 / s[min(n - 1, int(n * 0.99))],
        "fps_01low": 1000 / s[min(n - 1, int(n * 0.999))],
        "ft_avg": avg,
        "ft_max": max(frames),
        "stutter_pct": 100 * sum(1 for f in frames if f > med * 1.5) / n,
        "hitches": sum(1 for f in frames if f > med * 2.0 or f > 50),
    }


def _verdict(s: dict) -> str:
    ratio = s["fps_1low"] / s["fps_avg"] if s["fps_avg"] else 0
    if s["stutter_pct"] < 1 and s["hitches"] == 0 and ratio > 0.8:
        return "Suave ✔ — frametime consistente, sem engasgos relevantes."
    if s["stutter_pct"] < 3 and s["hitches"] <= 2:
        return "Quase liso — poucos engasgos isolados."
    return "Stutter perceptível — 1% low longe da média e/ou hitches. Vale investigar."


class BenchmarkDialog(QDialog):
    def __init__(self, summary: dict, game: str) -> None:
        super().__init__()
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats — Resultado do Benchmark")
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        head = QLabel(f"{game}   ·   {summary['duration']:.0f}s   ·   {summary['frames']} frames")
        head.setProperty("role", "title")
        root.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(8)
        rows = [
            ("FPS médio", f"{summary['fps_avg']:.0f}", theme.fps_color(summary["fps_avg"])),
            ("1% low", f"{summary['fps_1low']:.0f}", theme.fps_color(summary["fps_1low"])),
            ("0.1% low", f"{summary['fps_01low']:.0f}", theme.fps_color(summary["fps_01low"])),
            ("Frametime médio", f"{summary['ft_avg']:.2f} ms", theme.TXT),
            ("Frametime máx", f"{summary['ft_max']:.1f} ms",
             theme.BAD if summary["ft_max"] > 50 else theme.TXT),
            ("Stutter", f"{summary['stutter_pct']:.1f}%", theme.stutter_color(summary["stutter_pct"])),
            ("Hitches", str(summary["hitches"]), theme.BAD if summary["hitches"] else theme.OK),
        ]
        for i, (label, val, color) in enumerate(rows):
            lab = QLabel(label)
            lab.setProperty("role", "mute")
            v = QLabel(val)
            v.setFont(make_font(13, QFont.Weight.Bold, theme.FONT_DISPLAY))
            v.setStyleSheet(f"color: {color};")
            grid.addWidget(lab, i, 0)
            grid.addWidget(v, i, 1)
        root.addLayout(grid)

        verdict = QLabel(_verdict(summary))
        verdict.setWordWrap(True)
        verdict.setProperty("role", "mute")
        root.addWidget(verdict)

        btn = QPushButton("Fechar")
        btn.setObjectName("Accent")
        btn.clicked.connect(self.accept)
        root.addWidget(btn)
