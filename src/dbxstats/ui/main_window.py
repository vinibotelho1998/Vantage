"""Janela principal: chrome proprio, barra lateral de navegacao e pilha de telas."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core import units
from ..platform import win as winapi
from .components import IconButton, LoadDots, NavButton, label
from .views.base import View
from .views.benchmark import BenchmarkView
from .views.cpu import CpuView
from .views.dashboard import DashboardView
from .views.displays import DisplaysView
from .views.gamepad import GamepadView
from .views.gaming import GamingView
from .views.gpu import GpuView
from .views.launcher import LauncherView
from .views.memory import MemoryView
from .views.network import NetworkView
from .views.processes import ProcessesView
from .views.sensors import SensorsView

VIEW_CLASSES = (DashboardView, GamingView, CpuView, GpuView, MemoryView,
                NetworkView, SensorsView, ProcessesView, BenchmarkView, LauncherView,
                DisplaysView, GamepadView)

_EDGE = 6


class TitleBar(QWidget):
    """Barra superior: identidade, atalhos rapidos e controles da janela."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._win = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(theme.scaled(44))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.scaled(16), 0, theme.scaled(8), 0)
        lay.setSpacing(theme.scaled(10))

        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = label("Painel", 12, QFont.Weight.DemiBold, theme.TXT)
        self.subtitle = label("", 7.5, QFont.Weight.Normal, theme.FAINT)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        lay.addLayout(col)
        lay.addStretch(1)

        self.chips = LoadDots()
        self.chips.setFixedWidth(theme.scaled(330))
        lay.addWidget(self.chips)
        # Em janela estreita esses 330 px fixos empurram titulo e relogio um por
        # cima do outro. Some antes disso acontecer, ver resizeEvent.
        self._chips_min = theme.scaled(980)

        self.clock = label("", 9, QFont.Weight.DemiBold, theme.MUTE, theme.FONT_DISPLAY)
        lay.addWidget(self.clock)
        lay.addSpacing(theme.scaled(8))

        self.btn_overlay = IconButton("▣", "Overlay no jogo (Ctrl+Alt+O)")
        self.btn_overlay.clicked.connect(window.app.toggle_overlay)
        self.btn_settings = IconButton("⚙", "Configurações")
        self.btn_settings.clicked.connect(lambda: window.app.open_settings())
        self.btn_min = IconButton("―", "Minimizar")
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max = IconButton("▢", "Maximizar / restaurar")
        self.btn_max.clicked.connect(window.toggle_maximized)
        self.btn_close = IconButton("✕", "Fechar", danger=True)
        self.btn_close.clicked.connect(window.close)
        for b in (self.btn_overlay, self.btn_settings, self.btn_min,
                  self.btn_max, self.btn_close):
            lay.addWidget(b)

    def resizeEvent(self, event) -> None:
        self.chips.setVisible(self.width() >= self._chips_min)
        self.clock.setVisible(self.width() >= theme.scaled(620))
        self.subtitle.setVisible(self.height() >= theme.scaled(40))
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._win.toggle_maximized()
        event.accept()


class Sidebar(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._win = window
        self.setObjectName("Sidebar")
        self.setFixedWidth(theme.scaled(190))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.scaled(10), theme.scaled(16), theme.scaled(10),
                               theme.scaled(12))
        lay.setSpacing(theme.scaled(3))

        brand = QHBoxLayout()
        brand.setContentsMargins(theme.scaled(6), 0, 0, theme.scaled(14))
        brand.setSpacing(theme.scaled(6))
        self._brand = label("DBX", 15, QFont.Weight.Black, theme.accent_color(
            window.app.settings.accent))
        sub = label("STATS", 9, QFont.Weight.Bold, theme.FAINT)
        sub.setAlignment(Qt.AlignmentFlag.AlignBottom)
        brand.addWidget(self._brand)
        brand.addWidget(sub)
        brand.addStretch(1)
        lay.addLayout(brand)

        self.buttons: dict[str, NavButton] = {}
        for cls in VIEW_CLASSES:
            btn = NavButton(cls.key, cls.title, cls.glyph)
            btn.clicked.connect(window.show_view)
            self.buttons[cls.key] = btn
            lay.addWidget(btn)
        lay.addStretch(1)

        self.status = QVBoxLayout()
        self.status.setSpacing(theme.scaled(3))
        self._lines: dict[str, QLabel] = {}
        for key, text in (("sensors", "Sensores"), ("capture", "Captura"),
                          ("uptime", "Ligado há")):
            row = QHBoxLayout()
            row.setContentsMargins(theme.scaled(6), 0, theme.scaled(4), 0)
            cap = label(text, 7.5, QFont.Weight.Normal, theme.FAINT)
            val = label("—", 7.5, QFont.Weight.DemiBold, theme.MUTE)
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(cap)
            row.addStretch(1)
            row.addWidget(val)
            self._lines[key] = val
            self.status.addLayout(row)
        lay.addLayout(self.status)

    def set_active(self, key: str) -> None:
        accent = theme.accent_color(self._win.app.settings.accent)
        self._brand.setStyleSheet(f"color: {accent}; background: transparent;")
        for btn_key, btn in self.buttons.items():
            btn.set_active(btn_key == key, accent)

    def set_status(self, key: str, text: str, color: str = theme.MUTE) -> None:
        line = self._lines.get(key)
        if line is not None:
            line.setText(text)
            line.setStyleSheet(f"color: {color}; background: transparent;")


class MainWindow(QWidget):
    """Janela sem moldura nativa, com redimensionamento e snap do Windows."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._maximized = False
        self._normal_geometry = None

        self.setWindowTitle("DBX Stats")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(theme.scaled(980), theme.scaled(620))
        self.setMouseTracking(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_EDGE, _EDGE, _EDGE, _EDGE)
        self._root = QWidget()
        self._root.setObjectName("Root")
        outer.addWidget(self._root)

        row = QHBoxLayout(self._root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.sidebar = Sidebar(self)
        row.addWidget(self.sidebar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.titlebar = TitleBar(self)
        right.addWidget(self.titlebar)

        content = QWidget()
        content.setObjectName("Content")
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(theme.scaled(16), theme.scaled(4),
                                       theme.scaled(16), theme.scaled(14))
        self.stack = QStackedWidget()
        content_lay.addWidget(self.stack)
        right.addWidget(content, 1)
        row.addLayout(right, 1)

        self.views: dict[str, View] = {}
        for cls in VIEW_CLASSES:
            view = cls(app)
            self.views[cls.key] = view
            self.stack.addWidget(view)

        self._current = ""
        self.show_view(app.settings.start_view)
        self.apply_settings()

    # ── navegacao ────────────────────────────────────────────────────────────
    def show_view(self, key: str) -> None:
        view = self.views.get(key)
        if view is None or key == self._current:
            return
        self._current = key
        self.stack.setCurrentWidget(view)
        self.sidebar.set_active(key)
        self.titlebar.title.setText(view.title)
        self.titlebar.subtitle.setText(view.subtitle)
        view.on_settings_changed()
        view.on_activate()
        data = self.app.last_data()
        if data:
            view.on_system(data)
        view.on_fps()

    @property
    def current_view(self) -> View | None:
        return self.views.get(self._current)

    # ── ciclo de atualizacao ─────────────────────────────────────────────────
    def tick_system(self, data: dict) -> None:
        view = self.current_view
        if view is not None:
            view.on_system(data)
        self._update_chips(data)
        self.sidebar.set_status(
            "sensors", "ativos" if data.get("lhm_ok") else "carregando",
            theme.OK if data.get("lhm_ok") else theme.WARN)
        self.sidebar.set_status("uptime", units.duration(data.get("uptime")))

    def tick_fps(self) -> None:
        view = self.current_view
        if view is not None:
            view.on_fps()
        engine = self.app.fps
        color = theme.OK if engine.status == "capturando" else theme.WARN
        text = engine.status if len(engine.status) < 18 else engine.status[:17] + "…"
        self.sidebar.set_status("capture", text, color)
        stream = self.app.active_stream()
        badge = self.sidebar.buttons.get("gaming")
        if badge is not None:
            if stream is not None:
                fps = stream.metrics.fps_now or stream.metrics.fps_avg
                badge.set_badge(units.integer(fps), theme.fps_color(fps))
            else:
                badge.set_badge("")

    def tick_clock(self) -> None:
        self.titlebar.clock.setText(datetime.now().strftime("%H:%M:%S"))

    def _update_chips(self, d: dict) -> None:
        gpu = d.get("gpu") or {}
        items = [
            (f"CPU {d.get('cpu_pct', 0):.0f}%", theme.load_color(d.get("cpu_pct"))),
            (f"{units.temp(d.get('cpu_temp'))}", theme.temp_color(d.get("cpu_temp"))),
            (f"GPU {gpu.get('usage', 0):.0f}%", theme.load_color(gpu.get("usage"))),
            (f"{units.temp(gpu.get('temp'))}", theme.temp_color(gpu.get("temp"))),
            (f"RAM {d.get('ram_pct', 0):.0f}%", theme.load_color(d.get("ram_pct"))),
        ]
        self.titlebar.chips.set_items(items)

    # ── configuracoes ────────────────────────────────────────────────────────
    def apply_settings(self) -> None:
        cfg = self.app.settings
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if cfg.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self.windowFlags() != flags:
            visible = self.isVisible()
            self.setWindowFlags(flags)
            if visible:
                self.show()
        self.sidebar.set_active(self._current)
        for view in self.views.values():
            view.on_settings_changed()

    def restore_geometry(self) -> None:
        cfg = self.app.settings
        if cfg.win_x >= -10000 and cfg.win_y >= -10000 and cfg.win_x != -1:
            self.setGeometry(cfg.win_x, cfg.win_y, cfg.win_w, cfg.win_h)
        else:
            self.resize(cfg.win_w, cfg.win_h)
            screen = QApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.center() - self.rect().center())
        if cfg.win_maximized or cfg.start_maximized:
            self.toggle_maximized(True)

    def store_geometry(self) -> None:
        cfg = self.app.settings
        geo = self._normal_geometry if self._maximized else self.geometry()
        if geo is not None:
            cfg.win_x, cfg.win_y = geo.x(), geo.y()
            cfg.win_w, cfg.win_h = geo.width(), geo.height()
        cfg.win_maximized = self._maximized

    # ── janela ───────────────────────────────────────────────────────────────
    def toggle_maximized(self, force: bool | None = None) -> None:
        target = (not self._maximized) if force is None else force
        if target == self._maximized:
            return
        layout = self.layout()
        if target:
            self._normal_geometry = self.geometry()
            screen = self.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            layout.setContentsMargins(0, 0, 0, 0)
            self._root.setObjectName("RootMax")
            self.setGeometry(screen.availableGeometry())
        else:
            layout.setContentsMargins(_EDGE, _EDGE, _EDGE, _EDGE)
            self._root.setObjectName("Root")
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
        self._root.style().unpolish(self._root)
        self._root.style().polish(self._root)
        self._maximized = target
        self.titlebar.btn_max.setText("❐" if target else "▢")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # O app roda elevado; sem isso o Explorer nao consegue soltar arquivo aqui.
        winapi.allow_drops_from_explorer(int(self.winId()))

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMaximized:
                self.setWindowState(Qt.WindowState.WindowNoState)
                self.toggle_maximized(True)
        super().changeEvent(event)

    def _edges(self, pos: QPoint):
        if self._maximized:
            return Qt.Edge(0)
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        edges = Qt.Edge(0)
        if x <= _EDGE:
            edges |= Qt.Edge.LeftEdge
        elif x >= w - _EDGE - 1:
            edges |= Qt.Edge.RightEdge
        if y <= _EDGE:
            edges |= Qt.Edge.TopEdge
        elif y >= h - _EDGE - 1:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event) -> None:
        edges = self._edges(event.position().toPoint())
        self.setCursor(_cursor_for(edges))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges(event.position().toPoint())
            handle = self.windowHandle()
            if edges and handle is not None:
                handle.startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        super().leaveEvent(event)

    def closeEvent(self, event) -> None:
        self.store_geometry()
        if self.app.settings.close_to_tray:
            event.ignore()
            self.hide()
            self.app.notify_tray_hint()
        else:
            event.accept()
            self.app.quit()


def _cursor_for(edges) -> Qt.CursorShape:
    left = bool(edges & Qt.Edge.LeftEdge)
    right = bool(edges & Qt.Edge.RightEdge)
    top = bool(edges & Qt.Edge.TopEdge)
    bottom = bool(edges & Qt.Edge.BottomEdge)
    if (left and top) or (right and bottom):
        return Qt.CursorShape.SizeFDiagCursor
    if (right and top) or (left and bottom):
        return Qt.CursorShape.SizeBDiagCursor
    if left or right:
        return Qt.CursorShape.SizeHorCursor
    if top or bottom:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor
