"""Dialogo unico de configuracoes: pagina rolavel com todas as opcoes."""
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
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..config import ALL_STATS_LABELS, SECTION_LABELS, SECTION_METRICS

_MODES = [("reduced", "Reduzido (painel compacto)"), ("fullscreen", "Fullscreen (dashboard)"),
          ("tablet", "Tablet (tela cheia em outro monitor)"), ("overlay", "Overlay (dentro do jogo)")]
_POSITIONS = [("Inferior direita", "bottom-right"), ("Inferior esquerda", "bottom-left"),
              ("Superior direita", "top-right"), ("Superior esquerda", "top-left"),
              ("Direita", "right"), ("Esquerda", "left")]
_CORNERS = [("Superior esquerdo", "top-left"), ("Superior direito", "top-right"),
            ("Inferior esquerdo", "bottom-left"), ("Inferior direito", "bottom-right")]
_INTERVALS = [("0,25 s", 0.25), ("0,5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0)]
_FPS_WINDOWS = [("Rápido (0,25 s)", 0.25), ("Normal (0,5 s)", 0.5), ("Suave (1,0 s)", 1.0)]
_FPS_SOURCES = [("Render — o que a GPU produziu", "present"),
                ("Display — o que apareceu na tela", "display")]
_FPS_METRICS = [("inst", "FPS atual"), ("avg", "FPS médio"), ("1low", "1% Low"),
                ("01low", "0.1% Low"), ("frametime", "Frametime"), ("graph", "Gráfico de frametime")]


def _combo(pairs, current) -> QComboBox:
    c = QComboBox()
    for label, value in pairs:
        c.addItem(label, value)
    idx = c.findData(current)
    if idx >= 0:
        c.setCurrentIndex(idx)
    return c


def _header(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setProperty("role", "title")
    lbl.setStyleSheet(f"color: {theme.MUTE}; font-weight: 700; margin-top: 6px;")
    return lbl


class SettingsDialog(QDialog):
    def __init__(self, controller, tab: int = 0) -> None:
        super().__init__()
        self._ctl = controller
        self._cfg = controller.settings
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats — Configurações")
        self.setMinimumWidth(460)
        self.resize(460, 720)

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page = QWidget()
        self._lay = QVBoxLayout(page)
        self._lay.setSpacing(8)
        scroll.setWidget(page)
        root.addWidget(scroll, 1)

        self._build_mode()
        self._build_appearance()
        self._build_behavior()
        self._build_alerts()
        self._build_fps()
        self._build_visibility()
        self._build_stats()
        self._lay.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Salvar")
        save.setObjectName("Accent")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

    def _build_mode(self) -> None:
        self._lay.addWidget(_header("Modo de exibição"))
        form = QFormLayout()
        self._w_mode = _combo(_MODES, self._cfg.mode)
        form.addRow("Modo", self._w_mode)
        self._lay.addLayout(form)

    def _build_appearance(self) -> None:
        self._lay.addWidget(_header("Aparência"))
        form = QFormLayout()
        self._w_position = _combo(_POSITIONS, self._cfg.position)
        self._w_accent = _combo([(a.label, a.key) for a in theme.ACCENTS.values()], self._cfg.accent)
        self._w_corner = _combo(_CORNERS, self._cfg.overlay_corner)
        self._w_interval = _combo(_INTERVALS, self._cfg.update_interval)

        self._w_opacity = QSlider(Qt.Orientation.Horizontal)
        self._w_opacity.setRange(40, 100)
        self._w_opacity.setValue(int(self._cfg.opacity * 100))
        op_lbl = QLabel(f"{self._w_opacity.value()}%")
        self._w_opacity.valueChanged.connect(lambda v: op_lbl.setText(f"{v}%"))
        op_row = QHBoxLayout()
        op_row.addWidget(self._w_opacity)
        op_row.addWidget(op_lbl)

        self._w_width = QSlider(Qt.Orientation.Horizontal)
        self._w_width.setRange(200, 380)
        self._w_width.setValue(self._cfg.width)
        wd_lbl = QLabel(f"{self._w_width.value()} px")
        self._w_width.valueChanged.connect(lambda v: wd_lbl.setText(f"{v} px"))
        wd_row = QHBoxLayout()
        wd_row.addWidget(self._w_width)
        wd_row.addWidget(wd_lbl)

        form.addRow("Posição (modo reduzido)", self._w_position)
        form.addRow("Largura (modo reduzido)", wd_row)
        form.addRow("Opacidade", op_row)
        form.addRow("Cor de destaque", self._w_accent)
        form.addRow("Canto do overlay", self._w_corner)
        form.addRow("Atualização", self._w_interval)
        self._lay.addLayout(form)

    def _build_behavior(self) -> None:
        self._lay.addWidget(_header("Comportamento"))
        self._chk_top = QCheckBox("Sempre no topo")
        self._chk_top.setChecked(self._cfg.always_on_top)
        self._chk_auto = QCheckBox("Iniciar com o Windows")
        self._chk_auto.setChecked(self._cfg.autostart)
        self._chk_hide = QCheckBox("Ocultar painel em jogos em tela cheia")
        self._chk_hide.setChecked(self._cfg.hide_fullscreen)
        self._chk_lock = QCheckBox("Travar posição (impede arrastar)")
        self._chk_lock.setChecked(self._cfg.locked)
        for chk in (self._chk_top, self._chk_auto, self._chk_hide, self._chk_lock):
            self._lay.addWidget(chk)

    def _build_alerts(self) -> None:
        self._lay.addWidget(_header("Alertas de temperatura (0 = desligado)"))
        form = QFormLayout()
        self._w_cpu_alert = QSpinBox()
        self._w_cpu_alert.setRange(0, 120)
        self._w_cpu_alert.setSuffix(" °C")
        self._w_cpu_alert.setValue(self._cfg.alert_cpu_temp)
        self._w_gpu_alert = QSpinBox()
        self._w_gpu_alert.setRange(0, 120)
        self._w_gpu_alert.setSuffix(" °C")
        self._w_gpu_alert.setValue(self._cfg.alert_gpu_temp)
        form.addRow("Avisar se CPU passar de", self._w_cpu_alert)
        form.addRow("Avisar se GPU passar de", self._w_gpu_alert)
        self._lay.addLayout(form)

    def _build_fps(self) -> None:
        self._lay.addWidget(_header("FPS"))
        form = QFormLayout()
        self._w_fpswin = _combo(_FPS_WINDOWS, self._cfg.fps_window)
        self._w_fpssrc = _combo(_FPS_SOURCES, self._cfg.fps_source)
        self._w_proc = self._build_proc_combo()
        form.addRow("Janela de amostragem", self._w_fpswin)
        form.addRow("Fonte", self._w_fpssrc)
        form.addRow("Processo monitorado", self._w_proc)
        self._lay.addLayout(form)
        self._chk_fs_only = QCheckBox("Só capturar jogo em tela cheia (ignora janelas)")
        self._chk_fs_only.setChecked(self._cfg.fps_fullscreen_only)
        self._lay.addWidget(self._chk_fs_only)
        self._lay.addWidget(QLabel("Métricas de FPS visíveis:"))
        self._fps_metric_checks = self._check_grid(_FPS_METRICS, set(self._cfg.fps_metrics))

    def _build_visibility(self) -> None:
        self._lay.addWidget(_header("O que mostrar em cada seção"))
        self._vis_checks: dict[str, dict[str, QCheckBox]] = {}
        vis = self._cfg.visible_metrics or {}
        for sec, rows in SECTION_METRICS.items():
            self._lay.addWidget(QLabel(SECTION_LABELS[sec]))
            active = set(vis.get(sec, [k for k, _ in rows]))
            self._vis_checks[sec] = self._check_grid(rows, active)

    def _build_stats(self) -> None:
        self._lay.addWidget(_header("Estatísticas (mín / méd / máx)"))
        self._chk_show_stats = QCheckBox("Mostrar mín / méd / máx no painel")
        self._chk_show_stats.setChecked(self._cfg.show_stats)
        self._lay.addWidget(self._chk_show_stats)
        self._lay.addWidget(QLabel("Métricas rastreadas:"))
        self._stat_checks = self._check_grid(ALL_STATS_LABELS, set(self._cfg.stats_keys))
        reset = QPushButton("Zerar estatísticas agora  (atalho: Ctrl+Alt+R)")
        reset.clicked.connect(self._ctl.clear_stats)
        self._lay.addWidget(reset)

    def _check_grid(self, items, active: set) -> dict[str, QCheckBox]:
        grid = QGridLayout()
        grid.setSpacing(4)
        checks: dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(items):
            chk = QCheckBox(label)
            chk.setChecked(key in active)
            checks[key] = chk
            grid.addWidget(chk, i // 2, i % 2)
        self._lay.addLayout(grid)
        return checks

    def _build_proc_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Auto (janela ativa)", "")
        seen: dict[str, int] = {}
        for _, tup in self._ctl.fps.snapshot().items():
            app, fps = tup[1], tup[0]
            if app not in seen or fps > seen[app]:
                seen[app] = fps
        for app, fps in sorted(seen.items(), key=lambda x: -x[1]):
            combo.addItem(f"{app}  ({fps} fps)", app)
        idx = combo.findData(self._cfg.fps_pin)
        if idx < 0 and self._cfg.fps_pin:
            combo.addItem(self._cfg.fps_pin, self._cfg.fps_pin)
            idx = combo.findData(self._cfg.fps_pin)
        combo.setCurrentIndex(max(0, idx))
        return combo

    def _save(self) -> None:
        c = self._cfg
        c.mode = self._w_mode.currentData()
        new_pos = self._w_position.currentData()
        if new_pos != c.position:
            c.pos_x = -1
            c.pos_y = -1
        c.position = new_pos
        c.accent = self._w_accent.currentData()
        c.overlay_corner = self._w_corner.currentData()
        c.update_interval = self._w_interval.currentData()
        c.opacity = self._w_opacity.value() / 100
        c.width = self._w_width.value()
        c.always_on_top = self._chk_top.isChecked()
        c.autostart = self._chk_auto.isChecked()
        c.hide_fullscreen = self._chk_hide.isChecked()
        c.locked = self._chk_lock.isChecked()
        c.fps_window = self._w_fpswin.currentData()
        c.fps_source = self._w_fpssrc.currentData()
        c.fps_fullscreen_only = self._chk_fs_only.isChecked()
        c.fps_metrics = [k for k, chk in self._fps_metric_checks.items() if chk.isChecked()]
        c.fps_pin = self._w_proc.currentData() or ""
        c.visible_metrics = {sec: [k for k, chk in checks.items() if chk.isChecked()]
                             for sec, checks in self._vis_checks.items()}
        c.show_stats = self._chk_show_stats.isChecked()
        c.stats_keys = [k for k, chk in self._stat_checks.items() if chk.isChecked()]
        c.alert_cpu_temp = self._w_cpu_alert.value()
        c.alert_gpu_temp = self._w_gpu_alert.value()
        c.sanitize()
        self._ctl.on_settings_changed()
        self.accept()
