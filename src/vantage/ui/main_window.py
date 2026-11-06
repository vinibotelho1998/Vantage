"""Janela principal: chrome proprio, barra lateral de navegacao e pilha de telas."""
from __future__ import annotations

import os

from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, log, paths, theme
from ..core import units
if os.name == "nt":
    from ..platform import win as winapi
from .components import IconButton, LoadDots, NavButton, PillButton, label
from .views.base import View
from .views.benchmark import BenchmarkView
from .views.cpu import CpuView
from .views.dashboard import DashboardView
if os.name == "nt":
    from .views.displays import DisplaysView
    from .views.gamepad import GamepadView
else:
    from .views.linux_devices import DisplaysView, GamepadView
from .views.gpu import GpuView
from .views.launcher import LauncherView
from .views.memory import MemoryView
from .views.network import NetworkView
from .views.processes import ProcessesView
from .views.sensors import SensorsView

_log = log.get("ui")

VIEW_CLASSES = (DashboardView, CpuView, GpuView, MemoryView,
                NetworkView, SensorsView, ProcessesView, BenchmarkView, LauncherView,
                DisplaysView, GamepadView)

# O painel ja' mostra FPS, lows e frametime do jogo em foco; a tela de Jogos
# repetia isso na barra lateral. Ela continua existindo (e acessivel como tela
# inicial nas configuracoes), so' saiu do menu.
NAV_OCULTAS = ()
"""Telas construidas mas fora da navegacao. Nenhuma hoje."""

NAV_GRUPOS = (
    ("Monitor", ("dashboard", "cpu", "gpu", "memory", "network", "sensors", "processes")),
    ("Jogo", ("benchmark", "launcher")),
    ("Máquina", ("displays", "gamepad")),
)
"""Como a barra lateral agrupa as telas.

Onze itens numa lista corrida obrigavam a ler um por um para achar a aba de
Telas no meio das de sensor. Tres blocos, com um rotulo discreto em cima de
cada um, dividem a lista pelo que a pessoa esta' querendo fazer: olhar a
maquina, jogar, ou arrumar a casa. Tela que nao esta' em grupo nenhum entra no
fim, sem rotulo, para nunca sumir do menu por esquecimento aqui.
"""

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

        # Glifo nao dizia nem o que era nem se estava ligado. Texto com estado
        # resolve os dois de uma vez.
        self.btn_overlay = PillButton("OVERLAY", theme.MUTE)
        self.btn_overlay.setToolTip("Liga e desliga o overlay no jogo (Ctrl+Alt+O)")
        self.btn_overlay.clicked.connect(window.app.toggle_overlay)
        self.btn_settings = IconButton(tooltip="Configurações", icon="settings")
        self.btn_settings.clicked.connect(lambda: window.app.open_settings())
        self.btn_min = IconButton(tooltip="Minimizar", icon="minimize")
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max = IconButton(tooltip="Maximizar / restaurar", icon="maximize")
        self.btn_max.clicked.connect(window.toggle_maximized)
        self.btn_close = IconButton(tooltip="Fechar", danger=True, icon="close")
        self.btn_close.clicked.connect(window.close)
        lay.addWidget(self.btn_overlay)
        lay.addSpacing(theme.scaled(6))
        for b in (self.btn_settings, self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)
        self.sync_overlay_button()

    def sync_overlay_button(self) -> None:
        ligado = bool(self._win.app.settings.overlay_enabled)
        self.btn_overlay.setText("OVERLAY ON" if ligado else "OVERLAY OFF")
        self.btn_overlay.set_color(theme.OK if ligado else theme.MUTE)

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
        # Em DPI alto, nome e versão podem exigir mais que a largura usual.
        # A coluna acompanha o tamanho natural desses rótulos sem tomar a
        # folga do conteúdo principal.
        self.setMinimumWidth(theme.scaled(190))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.scaled(10), theme.scaled(16), theme.scaled(10),
                               theme.scaled(12))
        lay.setSpacing(theme.scaled(3))

        brand = QHBoxLayout()
        brand.setContentsMargins(theme.scaled(4), 0, 0, theme.scaled(14))
        brand.setSpacing(theme.scaled(5))
        # O mesmo icone da barra de tarefas, para a janela e o atalho se
        # reconhecerem como a mesma coisa.
        marca = _icone_do_app(theme.scaled(22))
        if marca is not None:
            brand.addWidget(marca)
        self._brand = label("Vantage", 15, QFont.Weight.Black, theme.accent_color(
            window.app.settings.accent))
        brand.addWidget(self._brand)
        # Ao lado do nome, e nao no rodape: no pe' da barra ela ficava abaixo da
        # lista inteira de telas, e um print de qualquer tela ja' tem que dizer
        # qual versao esta' rodando. MUTE e nao FAINT: o cinza do rodape fica em
        # 3.5:1 sobre a barra e, em 8 pt, passa batido.
        self.versao = label(f"v{__version__}", 8, color=theme.MUTE)
        # Alinhar pelo pe' deixaria o numero abaixo da linha de base do nome.
        self.versao.setContentsMargins(0, 0, 0, max(
            0, self._brand.fontMetrics().descent() - self.versao.fontMetrics().descent()))
        brand.addWidget(self.versao, 0, Qt.AlignmentFlag.AlignBottom)
        brand.addStretch(1)
        lay.addLayout(brand)
        self._brand_row = brand
        self._fit_brand()

        self.buttons: dict[str, NavButton] = {}
        por_chave = {cls.key: cls for cls in VIEW_CLASSES if cls.key not in NAV_OCULTAS}
        grupos = [(titulo, [k for k in chaves if k in por_chave])
                  for titulo, chaves in NAV_GRUPOS]
        soltas = [k for k in por_chave if not any(k in chaves for _t, chaves in grupos)]
        if soltas:
            grupos.append(("", soltas))
        for indice, (titulo, chaves) in enumerate(grupos):
            if not chaves:
                continue
            if titulo:
                rotulo = label(titulo.upper(), 7, QFont.Weight.Bold, theme.FAINT)
                rotulo.setStyleSheet(
                    f"color: {theme.FAINT}; letter-spacing: 1.2px; background: transparent;")
                rotulo.setContentsMargins(theme.scaled(12), theme.scaled(10 if indice else 0),
                                          0, theme.scaled(3))
                lay.addWidget(rotulo)
            for key in chaves:
                cls = por_chave[key]
                btn = NavButton(cls.key, cls.title, cls.glyph)
                btn.clicked.connect(window.show_view)
                self.buttons[cls.key] = btn
                lay.addWidget(btn)
        lay.addStretch(1)

        # O rodape voltou, menor e por outro motivo. Ele havia saido por ser
        # "ruido fixo num canto que ninguem olha", e isso valia enquanto tudo
        # funcionava. Quando os sensores ou a captura caem, o app fica com a
        # cara de sempre e simplesmente sem numero nenhum, e nao ha' onde
        # perguntar por que. Sao dois estados: olha-se uma vez, na hora em que
        # algo quebrou, que e' exatamente quando faltava.
        self.saude = label("", 7.5, color=theme.FAINT)
        self.saude.setWordWrap(True)
        lay.addWidget(self.saude)

    def _fit_brand(self) -> None:
        # Leitura após aplicar fontes/QSS: o DPI pode mudar ao mover a janela.
        for label in (self._brand, self.versao):
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance(label.text()))
        self._brand_row.invalidate()
        margins = self.layout().contentsMargins()
        required = self._brand_row.minimumSize().width() + margins.left() + margins.right()
        self.setMinimumWidth(max(theme.scaled(190), required))

    def event(self, event) -> bool:
        if event.type() in (QEvent.Type.Show, QEvent.Type.LayoutRequest) and hasattr(self, "_brand_row"):
            self._fit_brand()
        return super().event(event)

    def atualizar_saude(self) -> None:
        """Diz se os sensores e a captura estao de pe', e o porque quando nao.

        O texto do erro vai para a dica de ferramenta em vez da tela: na barra
        ele quebraria o layout, mas e' o que responde "por que nao aparece
        nada" sem abrir log nenhum.
        """
        app = self._win.app
        lhm = getattr(app, "lhm", None)
        fps = getattr(app, "fps", None)

        # getattr com padrao: o leitor pode existir sem ter terminado de subir,
        # e a barra lateral nao pode cair junto com ele.
        sensores_ok = bool(getattr(lhm, "ready", False))
        erro = str(getattr(lhm, "error", "") or "sem leitor de sensores")
        captura = str(getattr(fps, "status", "") or "—")
        capturando = captura in ("capturando", "aguardando um jogo")

        partes = [
            f"Sensores: {'ok' if sensores_ok else 'falhou'}",
            f"Captura: {captura}",
        ]
        self.saude.setText("\n".join(partes))
        # Vermelho so' quando ha' o que consertar; sensor de pe' e captura
        # esperando jogo sao o estado normal e nao devem chamar atencao.
        ruim = not sensores_ok or (os.name == "nt" and not capturando)
        self.saude.setStyleSheet(
            f"color: {theme.BAD if ruim else theme.FAINT}; background: transparent;")
        self.saude.setToolTip(erro if not sensores_ok else
                              "Sensores lendo normalmente." if capturando else
                              "A captura de quadros nao esta' ativa.")

    def set_active(self, key: str) -> None:
        accent = theme.accent_color(self._win.app.settings.accent)
        self._brand.setStyleSheet(f"color: {accent}; background: transparent;")
        for btn_key, btn in self.buttons.items():
            btn.set_active(btn_key == key, accent)


def _icone_do_app(lado: int) -> QLabel | None:
    """O icone do app num rotulo, ou None se o arquivo nao veio junto."""
    try:
        arquivo = paths.asset("icon.png")
        if not arquivo.exists():
            return None
        pix = QPixmap(str(arquivo))
        if pix.isNull():
            return None
    except OSError:
        return None
    rotulo = QLabel()
    rotulo.setPixmap(pix.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
    rotulo.setFixedSize(lado, lado)
    rotulo.setStyleSheet("background: transparent;")
    return rotulo


def _cabe_em_alguma_tela(x: int, y: int, w: int, h: int) -> bool:
    """A janela restaurada aparece em alguma tela ligada?

    A posicao guardada envelhece: basta fechar o app com a janela na TV e depois
    desligar a TV para a geometria apontar para o vazio. O app abria, a janela
    nascia fora de qualquer monitor, e de fora parecia que ele tinha fechado
    sozinho, com o processo vivo na bandeja o tempo todo.

    Exige um pedaco de verdade visivel, e nao so' o canto: um titulo de 40 px
    espiando na borda nao da' para arrastar de volta.
    """
    from PySide6.QtCore import QRect

    janela = QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
    minimo = janela.width() * janela.height() * 0.15
    for tela in QApplication.screens():
        visivel = janela.intersected(tela.availableGeometry())
        if visivel.width() * visivel.height() >= minimo:
            return True
    return False


class MainWindow(QWidget):
    """Janela sem moldura nativa, com redimensionamento e snap do Windows."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._maximized = False
        self._normal_geometry = None

        self.setWindowTitle(f"Vantage {__version__}")
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

    def reload_displays(self) -> None:
        """Redesenha a aba Telas depois de um monitor entrar ou sair.

        Ela so' se redesenhava ao ser aberta, entao plugar um monitor com ela
        ja' na frente nao mostrava nada.
        """
        view = self.views.get("displays")
        if view is not None and hasattr(view, "reload"):
            try:
                view.reload()
            except Exception:
                _log.exception("falha redesenhando a aba Telas")

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

    def tick_system(self, data: dict) -> None:
        view = self.current_view
        if view is not None:
            view.on_system(data)
        self._update_chips(data)
        self.sidebar.atualizar_saude()

    def tick_fps(self) -> None:
        view = self.current_view
        if view is not None:
            view.on_fps()

    def tick_clock(self) -> None:
        self.titlebar.clock.setText(datetime.now().strftime("%H:%M:%S"))

    def _update_chips(self, d: dict) -> None:
        gpu = d.get("gpu") or {}
        items = [
            (f"CPU {d.get('cpu_pct', 0):.0f}%", theme.load_color(d.get("cpu_pct"))),
            (f"{units.temp(d.get('cpu_temp'))}", theme.temp_color(d.get("cpu_temp"))),
            # Sem sensor de carga o chip mostra travessao: formatar o None
            # estourava, e "GPU 0%" seria uma medida que ninguem fez.
            (f"GPU {units.percent(gpu.get('usage'))}", theme.load_color(gpu.get("usage"))),
            (f"{units.temp(gpu.get('temp'))}", theme.temp_color(gpu.get("temp"))),
            (f"RAM {d.get('ram_pct', 0):.0f}%", theme.load_color(d.get("ram_pct"))),
        ]
        self.titlebar.chips.set_items(items)

    def apply_settings(self) -> None:
        cfg = self.app.settings
        self.titlebar.sync_overlay_button()
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
        if (cfg.win_x >= -10000 and cfg.win_y >= -10000 and cfg.win_x != -1
                and _cabe_em_alguma_tela(cfg.win_x, cfg.win_y, cfg.win_w, cfg.win_h)):
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
        self.titlebar.btn_max.set_icon("restore" if target else "maximize")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # O app roda elevado; sem isso o Explorer nao consegue soltar arquivo aqui.
        if os.name == "nt":
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
        from PySide6.QtWidgets import QSystemTrayIcon
        if self.app.settings.close_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
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
