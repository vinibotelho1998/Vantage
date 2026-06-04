"""Dialogo unico de configuracoes com abas (Geral, FPS, Estatisticas)."""
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
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..config import ALL_STATS_LABELS

_POSITIONS = [("Inferior direita", "bottom-right"), ("Inferior esquerda", "bottom-left"),
              ("Superior direita", "top-right"), ("Superior esquerda", "top-left"),
              ("Direita", "right"), ("Esquerda", "left")]
_CORNERS = [("Superior esquerdo", "top-left"), ("Superior direito", "top-right"),
            ("Inferior esquerdo", "bottom-left"), ("Inferior direito", "bottom-right")]
_INTERVALS = [("0,25 s", 0.25), ("0,5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0)]
_FPS_WINDOWS = [("Rápido (0,25 s)", 0.25), ("Normal (0,5 s)", 0.5), ("Suave (1,0 s)", 1.0)]
_FPS_SOURCES = [("Render — o que a GPU produziu", "present"),
                ("Display — o que apareceu na tela", "display")]
_FPS_METRICS = [("inst", "FPS instantâneo"), ("avg", "FPS médio"), ("1low", "1% Low"),
                ("01low", "0.1% Low"), ("frametime", "Frametime"), ("graph", "Gráfico de frametime")]


def _combo(pairs, current) -> QComboBox:
    c = QComboBox()
    for label, value in pairs:
        c.addItem(label, value)
    idx = c.findData(current)
    if idx >= 0:
        c.setCurrentIndex(idx)
    return c


class SettingsDialog(QDialog):
    def __init__(self, controller, tab: int = 0) -> None:
        super().__init__()
        self._ctl = controller
        self._cfg = controller.settings
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats — Configurações")
        self.setMinimumWidth(400)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_general(), "Geral")
        tabs.addTab(self._build_fps(), "FPS")
        tabs.addTab(self._build_stats(), "Estatísticas")
        tabs.setCurrentIndex(tab)
        root.addWidget(tabs)

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

    def _build_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)
        self._w_position = _combo(_POSITIONS, self._cfg.position)
        accents = [(a.label, a.key) for a in theme.ACCENTS.values()]
        self._w_accent = _combo(accents, self._cfg.accent)
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

        form.addRow("Posição do painel", self._w_position)
        form.addRow("Largura do painel", wd_row)
        form.addRow("Opacidade", op_row)
        form.addRow("Cor de destaque", self._w_accent)
        form.addRow("Canto do overlay", self._w_corner)
        form.addRow("Atualização", self._w_interval)

        self._chk_top = QCheckBox("Sempre no topo")
        self._chk_top.setChecked(self._cfg.always_on_top)
        self._chk_auto = QCheckBox("Iniciar com o Windows")
        self._chk_auto.setChecked(self._cfg.autostart)
        self._chk_hide = QCheckBox("Ocultar painel em jogos em tela cheia")
        self._chk_hide.setChecked(self._cfg.hide_fullscreen)
        self._chk_lock = QCheckBox("Travar posição (impede arrastar)")
        self._chk_lock.setChecked(self._cfg.locked)
        for chk in (self._chk_top, self._chk_auto, self._chk_hide, self._chk_lock):
            form.addRow(chk)
        return w

    def _build_fps(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(10)
        self._w_fpswin = _combo(_FPS_WINDOWS, self._cfg.fps_window)
        self._w_fpssrc = _combo(_FPS_SOURCES, self._cfg.fps_source)
        self._w_proc = self._build_proc_combo()
        form.addRow("Janela de amostragem", self._w_fpswin)
        form.addRow("Fonte", self._w_fpssrc)
        form.addRow("Processo monitorado", self._w_proc)
        lay.addLayout(form)

        lay.addWidget(_section_label("Métricas visíveis"))
        grid = QGridLayout()
        grid.setSpacing(4)
        active = set(self._cfg.fps_metrics)
        self._fps_metric_checks: dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(_FPS_METRICS):
            chk = QCheckBox(label)
            chk.setChecked(key in active)
            self._fps_metric_checks[key] = chk
            grid.addWidget(chk, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch(1)
        return w

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

    def _build_stats(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        self._chk_show_stats = QCheckBox("Mostrar mín / méd / máx no painel")
        self._chk_show_stats.setChecked(self._cfg.show_stats)
        lay.addWidget(self._chk_show_stats)
        lay.addWidget(_section_label("Métricas rastreadas"))
        grid = QGridLayout()
        grid.setSpacing(4)
        active = set(self._cfg.stats_keys)
        self._stat_checks: dict[str, QCheckBox] = {}
        for i, (key, label) in enumerate(ALL_STATS_LABELS):
            chk = QCheckBox(label)
            chk.setChecked(key in active)
            self._stat_checks[key] = chk
            grid.addWidget(chk, i // 2, i % 2)
        lay.addLayout(grid)
        reset = QPushButton("Zerar estatísticas agora")
        reset.clicked.connect(self._ctl.clear_stats)
        lay.addWidget(reset)
        lay.addStretch(1)
        return w

    def _save(self) -> None:
        c = self._cfg
        c.position = self._w_position.currentData()
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
        c.fps_metrics = [k for k, chk in self._fps_metric_checks.items() if chk.isChecked()]
        c.fps_pin = self._w_proc.currentData() or ""
        c.show_stats = self._chk_show_stats.isChecked()
        c.stats_keys = [k for k, chk in self._stat_checks.items() if chk.isChecked()]
        c.sanitize()
        self._ctl.on_settings_changed()
        self.accept()


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "title")
    return lbl
