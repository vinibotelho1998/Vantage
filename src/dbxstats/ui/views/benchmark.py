"""Tela de benchmark: captura uma corrida, resume e exporta."""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QMenu, QProgressBar, QVBoxLayout

from ... import theme
from ...core import frames as fr
from ...core import units
from ..charts import FrameTimeChart, Histogram, PercentileChart
from ..components import Badge, Card, KpiStrip, MetricList, PillButton, label
from .base import View, scroll_page

_KPIS = [
    ("avg", "FPS médio", ""), ("low1", "1% Low", ""), ("low01", "0.1% Low", ""),
    ("ft", "Frametime", "ms"), ("stutter", "Stutter", "%"), ("smooth", "Fluidez", ""),
]


class BenchmarkView(View):
    key = "benchmark"
    title = "Benchmark"
    glyph = "◔"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.run_btn = PillButton("Iniciar benchmark", theme.accent_color(self.cfg.accent),
                                  filled=True)
        self.run_btn.clicked.connect(self._toggle)
        bar.addWidget(self.run_btn)
        self.dur_btn = PillButton(f"Duração: {self.cfg.bench_seconds}s", theme.MUTE)
        self.dur_btn.clicked.connect(self._pick_duration)
        bar.addWidget(self.dur_btn)
        self.export_btn = PillButton("Exportar CSV", theme.MUTE)
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        bar.addStretch(1)
        self.target = Badge("nenhum jogo", theme.FAINT)
        bar.addWidget(self.target)
        root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(theme.scaled(6))
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.kpi = KpiStrip(_KPIS, columns=6)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        card_ft = Card("Frametime da corrida", theme.FRAME)
        self.ft_chart = FrameTimeChart(height=200)
        card_ft.add(self.ft_chart, 1)
        lay.addWidget(card_ft, 3)

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(theme.GAP))
        card_hist = Card("Distribuição", theme.GPU)
        self.hist = Histogram(height=150)
        card_hist.add(self.hist, 1)
        row.addWidget(card_hist, 1)
        card_pct = Card("Percentis", theme.RAM)
        self.pct = PercentileChart(height=150)
        card_pct.add(self.pct, 1)
        row.addWidget(card_pct, 1)
        lay.addLayout(row, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(theme.scaled(theme.GAP))
        card_res = Card("Resultado", theme.FPS)
        self.result_rows = MetricList([
            ("game", "Jogo"), ("frames", "Frames"), ("duration", "Duração"),
            ("min", "FPS mínimo"), ("max", "FPS máximo"), ("p1", "Percentil 1"),
            ("ftmax", "Frametime máx"), ("hitches", "Engasgos"),
            ("consistency", "Consistência"), ("bottleneck", "Gargalo"),
        ])
        card_res.add(self.result_rows)
        self.verdict = label("", 8.5, QFont.Weight.Normal, theme.MUTE)
        self.verdict.setWordWrap(True)
        card_res.add(self.verdict)
        bottom.addWidget(card_res, 1)

        card_sys = Card("Sistema durante a corrida", theme.CPU, "média / máximo")
        self.sys_rows = MetricList([
            ("cpu", "CPU"), ("cpu_temp", "CPU temp"), ("cpu_watts", "CPU potência"),
            ("gpu", "GPU"), ("gpu_temp", "GPU temp"), ("gpu_watts", "GPU potência"),
            ("ram", "RAM"), ("vram", "VRAM"),
        ])
        card_sys.add(self.sys_rows)
        card_sys.body.addStretch(1)
        bottom.addWidget(card_sys, 1)

        card_hist_runs = Card("Corridas anteriores", theme.DISK)
        self.runs = MetricList([(f"r{i}", "—") for i in range(8)])
        card_hist_runs.add(self.runs)
        card_hist_runs.body.addStretch(1)
        bottom.addWidget(card_hist_runs, 1)
        lay.addLayout(bottom, 2)
        lay.addStretch(0)

    # ── acoes ────────────────────────────────────────────────────────────────
    def _toggle(self) -> None:
        if self.app.benchmark_active():
            self.app.benchmark_stop()
        else:
            self.app.benchmark_start(self.cfg.bench_seconds)

    def _pick_duration(self) -> None:
        menu = QMenu(self)
        for seconds in (15, 30, 60, 120, 300, 600):
            menu.addAction(f"{seconds} s", lambda s=seconds: self._set_duration(s))
        menu.addSeparator()
        menu.addAction("Manual (parar no botão)", lambda: self._set_duration(3600))
        menu.exec(self.dur_btn.mapToGlobal(QPoint(0, self.dur_btn.height() + 4)))

    def _set_duration(self, seconds: int) -> None:
        self.cfg.bench_seconds = seconds
        self.app.save_settings()
        self.dur_btn.setText("Duração: manual" if seconds >= 3600 else f"Duração: {seconds}s")

    def _export(self) -> None:
        path = self.app.benchmark_export()
        if path:
            self.app.notify("DBX Stats", f"Benchmark exportado para {path.name}")
        else:
            self.app.notify("DBX Stats", "Nenhum benchmark para exportar.")

    def on_settings_changed(self) -> None:
        self.run_btn.set_color(theme.accent_color(self.cfg.accent))
        self.ft_chart.configure(self.cfg.smooth_lines)

    def on_fps(self) -> None:
        state = self.app.benchmark_state()
        if state["active"]:
            self.run_btn.setText("Parar benchmark")
            self.run_btn.set_color(theme.BAD)
            ratio = min(1.0, state["elapsed"] / max(1.0, state["total"]))
            self.progress.setValue(int(ratio * 1000))
            self.target.update_badge(
                f"{state['game']} · {state['frames']} frames · "
                f"{state['elapsed']:.0f}/{state['total']:.0f}s", theme.FPS)
        else:
            self.run_btn.setText("Iniciar benchmark")
            self.run_btn.set_color(theme.accent_color(self.cfg.accent))
            stream = self.app.active_stream()
            self.target.update_badge(stream.app if stream else "nenhum jogo",
                                     theme.FPS if stream else theme.FAINT)
            if not self.app.benchmark_last():
                self.progress.setValue(0)

        result = self.app.benchmark_last()
        if result is not None and result.get("_rev") != getattr(self, "_rev", None):
            self._rev = result.get("_rev")
            self._show(result)

    # ── resultado ────────────────────────────────────────────────────────────
    def _show(self, result: dict) -> None:
        m: fr.FrameMetrics = result["metrics"]
        ft = result["frametimes"]
        self.progress.setValue(1000)
        self.kpi.set("avg", units.integer(m.fps_avg), theme.fps_color(m.fps_avg))
        self.kpi.set("low1", units.integer(m.low_1), theme.fps_color(m.low_1))
        self.kpi.set("low01", units.integer(m.low_01), theme.fps_color(m.low_01))
        self.kpi.set("ft", f"{m.ft_avg:.2f}" if m.ft_avg else units.DASH,
                     theme.frametime_color(m.ft_avg))
        self.kpi.set("stutter", f"{m.stutter_pct:.1f}", theme.stutter_color(m.stutter_pct))
        self.kpi.set("smooth", f"{m.smoothness:.0f}" if m.smoothness is not None
                     else units.DASH, theme.score_color(m.smoothness))

        self.ft_chart.set_data(ft)
        centers, counts = fr.histogram(ft)
        self.hist.set_data(centers, counts)
        self.pct.set_points(fr.percentile_curve(ft))

        self.result_rows.set("game", result.get("game", "—"))
        self.result_rows.set("frames", str(m.frames))
        self.result_rows.set("duration", units.duration(m.duration))
        self.result_rows.set("min", units.integer(m.fps_min), theme.fps_color(m.fps_min))
        self.result_rows.set("max", units.integer(m.fps_max))
        self.result_rows.set("p1", units.integer(m.p1))
        self.result_rows.set("ftmax", units.ms(m.ft_max, 2), theme.frametime_color(m.ft_max))
        self.result_rows.set("hitches", str(m.hitches), theme.BAD if m.hitches else theme.OK)
        self.result_rows.set("consistency", f"{m.consistency:.0f}%" if m.consistency
                             is not None else units.DASH, theme.score_color(m.consistency))
        self.result_rows.set("bottleneck", m.bottleneck)
        self.verdict.setText(fr.verdict(m))

        env = result.get("system", {})
        for key, unit, decimals in (("cpu", "%", 0), ("cpu_temp", "°C", 0),
                                    ("cpu_watts", " W", 0), ("gpu", "%", 0),
                                    ("gpu_temp", "°C", 0), ("gpu_watts", " W", 0),
                                    ("ram", "%", 0), ("vram", "%", 0)):
            pair = env.get(key)
            if pair:
                self.sys_rows.set(key, f"{pair[0]:.{decimals}f}{unit} / "
                                       f"{pair[1]:.{decimals}f}{unit}")
            else:
                self.sys_rows.set(key, units.DASH)

        for i in range(8):
            row = self.runs.row(f"r{i}")
            history = self.app.bench_history
            if row is None:
                continue
            if i < len(history):
                run = history[-(i + 1)]
                row.set_label(f"{run['time']}  {run['game'][:14]}")
                row.set(f"{run['avg']:.0f} / {run['low1']:.0f} fps",
                        theme.fps_color(run["avg"]))
            else:
                row.set_label("—")
                row.set(units.DASH, theme.MUTE)
