"""Tela de jogos: tudo sobre frametime, lows, latencia e gargalo."""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QMenu, QVBoxLayout

from ... import theme
from ...core import frames as fr
from ...core import units
from ..charts import FrameTimeChart, Histogram, PercentileChart, Plot, TimeSeriesChart
from ..components import Badge, Card, KpiStrip, MetricList, PillButton, label
from .base import View, scroll_page

_KPIS = [
    ("fps", "FPS agora", ""), ("avg", "Média", ""), ("low1", "1% Low", ""),
    ("low01", "0.1% Low", ""), ("ft", "Frametime", "ms"), ("stutter", "Stutter", "%"),
    ("smooth", "Fluidez", ""), ("bottleneck", "Gargalo", ""),
]


class GamingView(View):
    key = "gaming"
    title = "Jogos"
    glyph = "🎮"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        root.addLayout(self._build_toolbar())
        self.kpi = KpiStrip(_KPIS, columns=8)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        card_ft = Card("Frametime", theme.FRAME,
                       "faixa clara = variação entre mín e máx do intervalo")
        self.ft_chart = FrameTimeChart(height=210)
        card_ft.add(self.ft_chart, 1)
        lay.addWidget(card_ft, 3)

        card_fps = Card("FPS ao longo do tempo", theme.FPS)
        self.fps_chart = TimeSeriesChart(
            [Plot("fps", "FPS", theme.FPS), Plot("low", "1% low", theme.WARN, width=1.4)],
            y_max=None, height=170, unit="")
        card_fps.add(self.fps_chart, 1)
        lay.addWidget(card_fps, 2)

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(theme.GAP))
        card_hist = Card("Distribuição de FPS", theme.GPU,
                         "onde o jogo passa a maior parte do tempo")
        self.hist = Histogram(height=150)
        card_hist.add(self.hist, 1)
        row.addWidget(card_hist, 1)

        card_pct = Card("Curva de percentis", theme.RAM,
                        "quanto mais plana à esquerda, menos engasgos")
        self.pct = PercentileChart(height=150)
        card_pct.add(self.pct, 1)
        row.addWidget(card_pct, 1)
        lay.addLayout(row, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(theme.scaled(theme.GAP))
        bottom.addWidget(self._build_frame_card(), 1)
        bottom.addWidget(self._build_latency_card(), 1)
        bottom.addWidget(self._build_session_card(), 1)
        lay.addLayout(bottom, 2)
        lay.addStretch(0)

    # ── construcao ───────────────────────────────────────────────────────────
    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.pick_btn = PillButton("Auto (janela ativa)", theme.accent_color(self.cfg.accent))
        self.pick_btn.clicked.connect(self._open_picker)
        bar.addWidget(self.pick_btn)

        self.window_btn = PillButton("Janela: 60 s", theme.MUTE)
        self.window_btn.clicked.connect(self._open_window_menu)
        bar.addWidget(self.window_btn)

        self.reset_btn = PillButton("Zerar sessão", theme.MUTE)
        self.reset_btn.clicked.connect(self.app.clear_stats)
        bar.addWidget(self.reset_btn)

        self.restart_btn = PillButton("Reiniciar captura", theme.MUTE)
        self.restart_btn.clicked.connect(self.app.restart_capture)
        bar.addWidget(self.restart_btn)
        bar.addStretch(1)

        self.status = Badge("—", theme.FAINT)
        bar.addWidget(self.status)
        self.mode_badge = Badge("—", theme.FAINT)
        bar.addWidget(self.mode_badge)
        return bar

    def _build_frame_card(self) -> Card:
        card = Card("Entrega de quadros", theme.FRAME)
        self.frame_rows = MetricList([
            ("frames", "Frames na janela"), ("duration", "Duração"),
            ("ftmin", "Frametime mín"), ("ftmax", "Frametime máx"),
            ("ftstd", "Desvio padrão"), ("consistency", "Consistência"),
            ("hitches", "Engasgos (>50 ms)"), ("dropped", "Quadros descartados"),
        ])
        card.add(self.frame_rows)
        self.verdict = label("", 8.5, QFont.Weight.Normal, theme.MUTE)
        self.verdict.setWordWrap(True)
        card.add(self.verdict)
        return card

    def _build_latency_card(self) -> Card:
        card = Card("Latência e carga", theme.CPU)
        self.lat_rows = MetricList([
            ("cpu_busy", "CPU por frame"), ("gpu_busy", "GPU por frame"),
            ("gpu_wait", "GPU esperando"), ("render", "Latência de render"),
            ("c2p", "Clique → tela"), ("cpu_ratio", "Ocupação da CPU"),
            ("gpu_ratio", "Ocupação da GPU"), ("sync", "Sincronização"),
        ])
        card.add(self.lat_rows)
        self.hint = label("", 8, QFont.Weight.Normal, theme.FAINT)
        self.hint.setWordWrap(True)
        card.add(self.hint)
        return card

    def _build_session_card(self) -> Card:
        card = Card("Sessão", theme.GPU, "desde o último reset")
        self.session_rows = MetricList([
            ("fps", "FPS"), ("cpu", "CPU"), ("cpu_temp", "CPU temp"),
            ("gpu", "GPU"), ("gpu_temp", "GPU temp"), ("gpu_watts", "GPU potência"),
            ("ram", "RAM"), ("ping", "Ping"),
        ])
        card.add(self.session_rows)
        card.body.addStretch(1)
        return card

    # ── interacao ────────────────────────────────────────────────────────────
    def _open_picker(self) -> None:
        menu = QMenu(self)
        menu.addAction("Auto (janela ativa)", lambda: self.app.set_fps_pin(""))
        apps = self.app.fps.apps()
        if apps:
            menu.addSeparator()
            for _pid, name, fps in apps:
                menu.addAction(f"{name}   ·   {fps:.0f} fps",
                               lambda n=name: self.app.set_fps_pin(n))
        menu.exec(self.pick_btn.mapToGlobal(QPoint(0, self.pick_btn.height() + 4)))

    def _open_window_menu(self) -> None:
        menu = QMenu(self)
        for seconds in (10.0, 30.0, 60.0, 180.0, 300.0):
            menu.addAction(f"{seconds:.0f} s", lambda s=seconds: self.app.set_fps_window(s))
        menu.exec(self.window_btn.mapToGlobal(QPoint(0, self.window_btn.height() + 4)))

    def on_settings_changed(self) -> None:
        self.ft_chart.configure(self.cfg.smooth_lines)
        self.fps_chart.configure(**self.chart_config())
        self.fps_chart.set_span(self.cfg.history_window)
        self.pick_btn.set_color(theme.accent_color(self.cfg.accent))
        self.pick_btn.setText(self.cfg.fps_pin or "Auto (janela ativa)")
        self.window_btn.setText(f"Janela: {self.cfg.fps_window:.0f} s")

    def on_system(self, d: dict) -> None:
        st = self.app.stats
        for key, decimals, unit in (("fps", 0, ""), ("cpu_pct", 0, "%"), ("cpu_temp", 0, "°C"),
                                    ("gpu_pct", 0, "%"), ("gpu_temp", 0, "°C"),
                                    ("gpu_watts", 0, " W"), ("ram_pct", 0, "%"),
                                    ("ping_ms", 0, " ms")):
            row = {"cpu_pct": "cpu", "cpu_temp": "cpu_temp", "gpu_pct": "gpu",
                   "gpu_temp": "gpu_temp", "gpu_watts": "gpu_watts", "ram_pct": "ram",
                   "ping_ms": "ping", "fps": "fps"}[key]
            self.session_rows.set(row, _range_text(st, key, decimals, unit))

        self.fps_chart.set_values("fps", self.history.values("fps"))
        self.fps_chart.set_values("low", self.history.values("fps_low1"))
        self.fps_chart.refresh()

    def on_fps(self) -> None:
        engine = self.app.fps
        self.status.update_badge(engine.status,
                                 theme.OK if engine.status == "capturando" else theme.WARN)
        stream = self.app.active_stream()
        if stream is None:
            self._clear()
            return

        m = stream.metrics
        self.pick_btn.setText(self.cfg.fps_pin or f"Auto · {stream.app}")
        mode = stream.present_mode or "—"
        self.mode_badge.update_badge(mode, theme.MUTE)

        self.kpi.set("fps", units.integer(m.fps_now), theme.fps_color(m.fps_now),
                     stream.app)
        self.kpi.set("avg", units.integer(m.fps_avg), theme.fps_color(m.fps_avg),
                     f"máx {units.integer(m.fps_max)}")
        self.kpi.set("low1", units.integer(m.low_1), theme.fps_color(m.low_1),
                     f"P1 {units.integer(m.p1)}")
        self.kpi.set("low01", units.integer(m.low_01), theme.fps_color(m.low_01),
                     f"P0.1 {units.integer(m.p01)}")
        self.kpi.set("ft", f"{m.ft_avg:.2f}" if m.ft_avg else units.DASH,
                     theme.frametime_color(m.ft_avg),
                     f"máx {units.ms(m.ft_max, 1)}")
        self.kpi.set("stutter", f"{m.stutter_pct:.1f}", theme.stutter_color(m.stutter_pct),
                     f"{m.hitches} engasgos")
        self.kpi.set("smooth", f"{m.smoothness:.0f}" if m.smoothness is not None
                     else units.DASH, theme.score_color(m.smoothness), "0–100")
        self.kpi.set("bottleneck", m.bottleneck,
                     theme.CPU if m.bottleneck == "CPU" else
                     (theme.GPU if m.bottleneck == "GPU" else theme.MUTE),
                     f"{m.frames} frames")

        ft = engine.frametimes(stream.pid)
        self.ft_chart.set_data(ft[-4000:])
        centers, counts = fr.histogram(ft)
        self.hist.set_data(centers, counts)
        self.pct.set_points(fr.percentile_curve(ft))

        self.frame_rows.set("frames", f"{m.frames}")
        self.frame_rows.set("duration", units.duration(m.duration))
        self.frame_rows.set("ftmin", units.ms(m.ft_min, 2))
        self.frame_rows.set("ftmax", units.ms(m.ft_max, 2), theme.frametime_color(m.ft_max))
        self.frame_rows.set("ftstd", units.ms(m.ft_std, 2))
        self.frame_rows.set("consistency", f"{m.consistency:.0f}%" if m.consistency
                            is not None else units.DASH, theme.score_color(m.consistency))
        self.frame_rows.set("hitches", str(m.hitches),
                            theme.BAD if m.hitches else theme.OK)
        self.frame_rows.set("dropped", f"{m.dropped_pct:.1f}%",
                            theme.stutter_color(m.dropped_pct))
        self.verdict.setText(fr.verdict(m))

        self.lat_rows.set("cpu_busy", units.ms(m.cpu_busy, 2))
        self.lat_rows.set("gpu_busy", units.ms(m.gpu_busy, 2))
        self.lat_rows.set("gpu_wait", units.ms(m.gpu_wait, 2))
        self.lat_rows.set("render", units.ms(m.render_latency, 1))
        self.lat_rows.set("c2p", units.ms(m.click_to_photon, 1))
        self.lat_rows.set("cpu_ratio", _ratio(m.cpu_load_ratio), theme.CPU)
        self.lat_rows.set("gpu_ratio", _ratio(m.gpu_load_ratio), theme.GPU)
        self.lat_rows.set("sync", ("VSync ligado" if stream.vsync else "VSync desligado"),
                          theme.WARN if stream.vsync else theme.OK)
        self.hint.setText(_advice(m, stream))

    def _clear(self) -> None:
        for key in ("fps", "avg", "low1", "low01", "ft", "stutter", "smooth"):
            self.kpi.set(key, units.DASH, theme.MUTE, "")
        self.kpi.set("bottleneck", "—", theme.MUTE, self.app.fps_hint())
        self.ft_chart.set_data([])
        self.hist.set_data([], [])
        self.pct.set_points([])
        self.verdict.setText(
            "Nenhum jogo apresentando quadros. Abra um jogo — a captura é automática.")
        self.hint.setText("")
        self.mode_badge.update_badge("—", theme.FAINT)


def _ratio(v: float | None) -> str:
    return units.DASH if v is None else f"{v * 100:.0f}%"


def _range_text(stats, key: str, decimals: int, unit: str) -> str:
    r = stats.get(key)
    if r is None:
        return units.DASH
    mn, av, mx = r
    f = f".{decimals}f"
    return f"{mn:{f}} / {av:{f}} / {mx:{f}}{unit}"


def _advice(m, stream) -> str:
    if m.bottleneck == "CPU":
        return ("A CPU termina o frame depois da GPU. Baixar distância de visão, "
                "sombras e densidade de NPCs costuma ajudar mais que baixar resolução.")
    if m.bottleneck == "GPU":
        return ("A GPU está saturada — é o cenário ideal para jogar. Para mais fps, "
                "reduza resolução, ray tracing ou ative upscaling.")
    if stream.vsync:
        return "Com VSync ligado o frametime fica preso ao refresh do monitor."
    if m.stutter_pct > 3:
        return ("Stutter alto sem gargalo claro: verifique VRAM cheia, shader compilation "
                "ou algum processo em segundo plano.")
    return "Nem CPU nem GPU saturadas — provavelmente há um limitador de fps ativo."
