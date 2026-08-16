"""Dialogo de configuracoes organizado por abas."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..config import (
    DASH_CARDS,
    FPS_NOW_WINDOWS,
    FPS_WINDOWS,
    HISTORY_WINDOWS,
    OVERLAY_METRICS,
    UPDATE_INTERVALS,
    VIEWS,
)

_VIEW_LABELS = {
    "dashboard": "Painel", "gaming": "Jogos", "cpu": "CPU", "gpu": "GPU",
    "memory": "Memória & Disco", "network": "Rede", "sensors": "Sensores",
    "processes": "Processos", "benchmark": "Benchmark", "launcher": "Atalhos",
    "displays": "Telas", "gamepad": "Controle",
}
_CORNERS = [("Superior esquerdo", "top-left"), ("Superior direito", "top-right"),
            ("Inferior esquerdo", "bottom-left"), ("Inferior direito", "bottom-right")]


def _combo(pairs, current) -> QComboBox:
    c = QComboBox()
    for text, value in pairs:
        c.addItem(text, value)
    idx = c.findData(current)
    if idx >= 0:
        c.setCurrentIndex(idx)
    return c


def _slider(lo: int, hi: int, value: int, suffix: str) -> tuple[QHBoxLayout, QSlider]:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    lbl = QLabel(f"{value}{suffix}")
    lbl.setMinimumWidth(52)
    s.valueChanged.connect(lambda v: lbl.setText(f"{v}{suffix}"))
    row = QHBoxLayout()
    row.addWidget(s, 1)
    row.addWidget(lbl)
    return row, s


def _page() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(4, 10, 12, 10)
    lay.setSpacing(10)
    area.setWidget(page)
    return area, lay


def _header(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {theme.MUTE}; font-weight: 700; letter-spacing: 1px; margin-top: 8px;")
    return lbl


class SettingsDialog(QDialog):
    def __init__(self, controller, tab: int = 0) -> None:
        super().__init__()
        self._ctl = controller
        self._cfg = controller.settings
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats — Configurações")
        self.setMinimumSize(560, 620)
        self.resize(620, 720)

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_general(), "Geral")
        self.tabs.addTab(self._tab_appearance(), "Aparência")
        self.tabs.addTab(self._tab_charts(), "Gráficos")
        self.tabs.addTab(self._tab_fps(), "FPS")
        self.tabs.addTab(self._tab_overlay(), "Overlay")
        self.tabs.addTab(self._tab_alerts(), "Alertas")
        self.tabs.setCurrentIndex(max(0, min(tab, self.tabs.count() - 1)))
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        reset = QPushButton("Restaurar padrões")
        reset.clicked.connect(self._restore_defaults)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Salvar")
        save.setObjectName("Accent")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    # ── abas ─────────────────────────────────────────────────────────────────
    def _tab_general(self) -> QWidget:
        area, lay = _page()
        form = QFormLayout()
        self.w_view = _combo([(_VIEW_LABELS[v], v) for v in VIEWS], self._cfg.start_view)
        self.w_interval = _combo([(f"{i:g} s", i) for i in UPDATE_INTERVALS],
                                 self._cfg.update_interval)
        form.addRow("Tela inicial", self.w_view)
        form.addRow("Intervalo de atualização", self.w_interval)
        lay.addLayout(form)

        lay.addWidget(_header("Comportamento"))
        self.c_top = QCheckBox("Manter janela sempre no topo")
        self.c_top.setChecked(self._cfg.always_on_top)
        self.c_tray = QCheckBox("Fechar para a bandeja em vez de encerrar")
        self.c_tray.setChecked(self._cfg.close_to_tray)
        self.c_min = QCheckBox("Iniciar minimizado na bandeja")
        self.c_min.setChecked(self._cfg.start_minimized)
        self.c_auto = QCheckBox("Iniciar com o Windows")
        self.c_auto.setChecked(self._cfg.autostart)
        for c in (self.c_top, self.c_tray, self.c_min, self.c_auto):
            lay.addWidget(c)

        lay.addWidget(_header("Rede"))
        net = QFormLayout()
        self.w_host = QLineEdit(self._cfg.ping_host)
        self.w_port = QSpinBox()
        self.w_port.setRange(1, 65535)
        self.w_port.setValue(self._cfg.ping_port)
        net.addRow("Host de teste de ping", self.w_host)
        net.addRow("Porta", self.w_port)
        lay.addLayout(net)
        lay.addStretch(1)
        return area

    def _tab_appearance(self) -> QWidget:
        area, lay = _page()
        form = QFormLayout()
        self.w_accent = _combo([(a.label, a.key) for a in theme.ACCENTS.values()],
                               self._cfg.accent)
        scale_row, self.w_scale = _slider(80, 180, int(self._cfg.ui_scale * 100), "%")
        form.addRow("Cor de destaque", self.w_accent)
        form.addRow("Escala da interface", scale_row)
        lay.addLayout(form)
        note = QLabel("A escala é aplicada ao reabrir o app.")
        note.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(note)

        lay.addWidget(_header("Cards do painel"))
        self.dash_checks: dict[str, QCheckBox] = {}
        grid = QGridLayout()
        active = set(self._cfg.dash_cards)
        for i, (key, text) in enumerate(DASH_CARDS):
            chk = QCheckBox(text)
            chk.setChecked(key in active)
            self.dash_checks[key] = chk
            grid.addWidget(chk, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        return area

    def _tab_charts(self) -> QWidget:
        area, lay = _page()
        form = QFormLayout()
        self.w_history = _combo([(f"{h} s", h) for h in HISTORY_WINDOWS],
                                self._cfg.history_window)
        form.addRow("Janela dos gráficos", self.w_history)
        lay.addLayout(form)

        self.c_smooth = QCheckBox("Linhas suavizadas (interpolação cúbica monotona)")
        self.c_smooth.setChecked(self._cfg.smooth_lines)
        self.c_fill = QCheckBox("Preencher a área sob a linha")
        self.c_fill.setChecked(self._cfg.fill_area)
        self.c_grid = QCheckBox("Mostrar grade e escala")
        self.c_grid.setChecked(self._cfg.show_grid)
        self.c_glow = QCheckBox("Brilho ao redor da linha")
        self.c_glow.setChecked(self._cfg.chart_glow)
        for c in (self.c_smooth, self.c_fill, self.c_grid, self.c_glow):
            lay.addWidget(c)
        note = QLabel(
            "Mesmo com muitos minutos de histórico, cada coluna mostra a faixa entre o "
            "menor e o maior valor do intervalo — picos curtos nunca somem.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(note)
        lay.addStretch(1)
        return area

    def _tab_fps(self) -> QWidget:
        area, lay = _page()
        form = QFormLayout()
        self.w_fpswin = _combo([(f"{w:g} s", w) for w in FPS_WINDOWS], self._cfg.fps_window)
        self.w_fpsnow = _combo([(f"{w:g} s", w) for w in FPS_NOW_WINDOWS],
                               self._cfg.fps_now_window)
        self.w_pin = QComboBox()
        self.w_pin.addItem("Auto (janela ativa)", "")
        for _pid, name, fps in self._ctl.fps.apps():
            self.w_pin.addItem(f"{name}  ({fps:.0f} fps)", name)
        idx = self.w_pin.findData(self._cfg.fps_pin)
        if idx < 0 and self._cfg.fps_pin:
            self.w_pin.addItem(self._cfg.fps_pin, self._cfg.fps_pin)
            idx = self.w_pin.findData(self._cfg.fps_pin)
        self.w_pin.setCurrentIndex(max(0, idx))
        form.addRow("Janela de análise (lows)", self.w_fpswin)
        form.addRow("Janela do FPS instantâneo", self.w_fpsnow)
        form.addRow("Processo monitorado", self.w_pin)
        lay.addLayout(form)

        self.c_fs = QCheckBox("Só considerar jogo em tela cheia")
        self.c_fs.setChecked(self._cfg.fps_only_fullscreen)
        lay.addWidget(self.c_fs)

        lay.addWidget(_header("Diagnóstico"))
        status = QLabel(
            f"Captura: {self._ctl.fps.status}\n"
            f"Reinícios automáticos nesta sessão: {self._ctl.fps.restarts}")
        status.setStyleSheet(f"color: {theme.MUTE};")
        lay.addWidget(status)
        restart = QPushButton("Reiniciar captura de FPS agora")
        restart.clicked.connect(self._ctl.restart_capture)
        lay.addWidget(restart)
        note = QLabel(
            "O motor usa PresentMon 2 e reinicia sozinho se a sessão de captura cair. "
            "O cálculo do 1% low é a média dos piores frames da janela — o mesmo "
            "critério usado em análises de hardware.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(note)
        lay.addStretch(1)
        return area

    def _tab_overlay(self) -> QWidget:
        area, lay = _page()
        self.c_overlay = QCheckBox("Ativar overlay dentro do jogo")
        self.c_overlay.setChecked(self._cfg.overlay_enabled)
        lay.addWidget(self.c_overlay)
        self.c_overlay_auto = QCheckBox("Mostrar apenas quando houver jogo em foco")
        self.c_overlay_auto.setChecked(self._cfg.overlay_auto_game)
        lay.addWidget(self.c_overlay_auto)

        form = QFormLayout()
        self.w_corner = _combo(_CORNERS, self._cfg.overlay_corner)
        op_row, self.w_opacity = _slider(30, 100, int(self._cfg.overlay_opacity * 100), "%")
        sc_row, self.w_oscale = _slider(70, 250, int(self._cfg.overlay_scale * 100), "%")
        hz_row, self.w_ohz = _slider(10, 100, int(self._cfg.overlay_refresh_hz * 10), "")
        gr_row, self.w_ograph = _slider(10, 300, int(self._cfg.overlay_graph_seconds), " s")
        self.w_ocols = _combo([("Automático", 0), ("Uma coluna", 1), ("Duas colunas", 2)],
                              self._cfg.overlay_columns)
        form.addRow("Canto da tela", self.w_corner)
        form.addRow("Opacidade", op_row)
        form.addRow("Tamanho", sc_row)
        form.addRow("Formato", self.w_ocols)
        form.addRow("Atualizações por segundo (x10)", hz_row)
        form.addRow("Janela do gráfico", gr_row)
        lay.addLayout(form)

        lay.addWidget(_header("Métricas exibidas"))
        grid = QGridLayout()
        active = set(self._cfg.overlay_metrics)
        self.overlay_checks: dict[str, QCheckBox] = {}
        for i, (key, text) in enumerate(OVERLAY_METRICS):
            chk = QCheckBox(text)
            chk.setChecked(key in active)
            self.overlay_checks[key] = chk
            grid.addWidget(chk, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addStretch(1)
        return area

    def _tab_alerts(self) -> QWidget:
        area, lay = _page()
        self.c_alerts = QCheckBox("Avisar na bandeja quando um limite for ultrapassado")
        self.c_alerts.setChecked(self._cfg.alerts_enabled)
        lay.addWidget(self.c_alerts)
        form = QFormLayout()
        self.w_cpu_alert = self._spin(self._cfg.alert_cpu_temp, 0, 120, " °C")
        self.w_gpu_alert = self._spin(self._cfg.alert_gpu_temp, 0, 120, " °C")
        self.w_ram_alert = self._spin(self._cfg.alert_ram_pct, 0, 100, " %")
        self.w_vram_alert = self._spin(self._cfg.alert_vram_pct, 0, 100, " %")
        form.addRow("Temperatura da CPU acima de", self.w_cpu_alert)
        form.addRow("Temperatura da GPU acima de", self.w_gpu_alert)
        form.addRow("Uso de RAM acima de", self.w_ram_alert)
        form.addRow("Uso de VRAM acima de", self.w_vram_alert)
        lay.addLayout(form)
        note = QLabel("0 desliga o alerta correspondente.")
        note.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(note)

        lay.addWidget(_header("Sessão"))
        clear = QPushButton("Zerar estatísticas mín/méd/máx  (Ctrl+Alt+R)")
        clear.clicked.connect(self._ctl.clear_stats)
        lay.addWidget(clear)
        lay.addStretch(1)
        return area

    def _spin(self, value: int, lo: int, hi: int, suffix: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSuffix(suffix)
        s.setValue(value)
        return s

    # ── acoes ────────────────────────────────────────────────────────────────
    def _restore_defaults(self) -> None:
        from ..config import Settings
        defaults = Settings()
        for f in defaults.as_dict():
            if f.startswith("win_"):
                continue
            setattr(self._cfg, f, getattr(defaults, f))
        self._cfg.sanitize()
        self._ctl.on_settings_changed()
        self.accept()

    def _save(self) -> None:
        c = self._cfg
        c.start_view = self.w_view.currentData()
        c.update_interval = self.w_interval.currentData()
        c.always_on_top = self.c_top.isChecked()
        c.close_to_tray = self.c_tray.isChecked()
        c.start_minimized = self.c_min.isChecked()
        c.autostart = self.c_auto.isChecked()
        c.ping_host = self.w_host.text()
        c.ping_port = self.w_port.value()

        c.accent = self.w_accent.currentData()
        c.ui_scale = self.w_scale.value() / 100
        c.dash_cards = [k for k, chk in self.dash_checks.items() if chk.isChecked()]

        c.history_window = self.w_history.currentData()
        c.smooth_lines = self.c_smooth.isChecked()
        c.fill_area = self.c_fill.isChecked()
        c.show_grid = self.c_grid.isChecked()
        c.chart_glow = self.c_glow.isChecked()

        c.fps_window = self.w_fpswin.currentData()
        c.fps_now_window = self.w_fpsnow.currentData()
        c.fps_pin = self.w_pin.currentData() or ""
        c.fps_only_fullscreen = self.c_fs.isChecked()

        c.overlay_enabled = self.c_overlay.isChecked()
        c.overlay_auto_game = self.c_overlay_auto.isChecked()
        c.overlay_corner = self.w_corner.currentData()
        c.overlay_opacity = self.w_opacity.value() / 100
        c.overlay_scale = self.w_oscale.value() / 100
        c.overlay_refresh_hz = self.w_ohz.value() / 10
        c.overlay_graph_seconds = self.w_ograph.value()
        c.overlay_columns = self.w_ocols.currentData()
        c.overlay_metrics = [k for k, chk in self.overlay_checks.items() if chk.isChecked()]

        c.alerts_enabled = self.c_alerts.isChecked()
        c.alert_cpu_temp = self.w_cpu_alert.value()
        c.alert_gpu_temp = self.w_gpu_alert.value()
        c.alert_ram_pct = self.w_ram_alert.value()
        c.alert_vram_pct = self.w_vram_alert.value()

        c.sanitize()
        self._ctl.on_settings_changed()
        self.accept()

