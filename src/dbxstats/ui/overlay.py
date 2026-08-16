"""Overlay in-game estilo RTSS: click-through, sempre no topo e configuravel."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core import units
from ..platform import win
from .charts import Sparkline

_MONO = "Cascadia Mono"
_FALLBACK = "Consolas"


def rect_center(rect) -> tuple[int, int]:
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def _ghz(mhz: float | None) -> str:
    """Frequencia curta, mas com a unidade explicita.

    Sem o 'Hz' a coluna vira armadilha: '6.00G' ao lado de '18.4G' faz parecer
    que os dois sao gigabytes.
    """
    if not mhz:
        return "—"
    return f"{mhz / 1000:.2f}GHz" if mhz >= 1000 else f"{mhz:.0f}MHz"


def _chunk(caption: str, value: str, color: str) -> str:
    return (f"<span style='color:{theme.TXT}'>{caption}</span>"
            f"<span style='color:{color}'>&nbsp;{value}</span>")


def _mono(pt: float, weight: int = QFont.Weight.Normal, scale: float = 1.0) -> QFont:
    f = QFont(_MONO)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFamilies([_MONO, _FALLBACK])
    f.setPointSizeF(pt * scale)
    f.setWeight(weight)
    return f


class GameOverlay(QWidget):
    """Painel minimo desenhado por cima do jogo."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._ctl = controller
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        self._built_for: tuple = ()
        self._painted = 0.0
        self._build()

    # ── tamanho ──────────────────────────────────────────────────────────────
    def _screen(self):
        """A tela onde o jogo esta', que nem sempre e' a primaria."""
        rect = win.foreground_monitor_rect()
        if rect is not None:
            found = QApplication.screenAt(QPoint(*rect_center(rect)))
            if found is not None:
                return found
        return QApplication.primaryScreen()

    def _auto_scale(self) -> float:
        """Mantem o overlay um cantinho discreto em qualquer tela.

        Duas coisas inflam o overlay num 4K: a fonte e' medida em pontos, entao a
        escala do Windows ja' multiplica tudo; e a tela e' o dobro de larga, o que
        pede um pouco mais de corpo para continuar legivel de longe. O primeiro
        fator e' desfeito, o segundo entra limitado — o resultado e' um painel que
        ocupa mais ou menos a mesma fracao da tela em 1080p e em 4K.
        """
        screen = self._screen()
        if screen is None:
            return 1.0
        dpi = max(72.0, float(screen.logicalDotsPerInch()))
        largura = max(640, screen.geometry().width())
        return (96.0 / dpi) * min(1.35, max(0.75, largura / 1920.0))

    # ── construcao ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        cfg = self._ctl.settings
        self._built_for = self._screen_key()
        scale = cfg.overlay_scale * self._auto_scale()
        # Fundo mais leve: por cima do jogo o painel tem que informar, nao tapar.
        alpha = int(cfg.overlay_opacity * 165)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._root = QFrame()
        self._root.setObjectName("Overlay")
        self._root.setStyleSheet(
            f"QFrame#Overlay {{ background: rgba(6, 9, 14, {alpha});"
            f" border-radius: {int(10 * scale)}px;"
            f" border: 1px solid rgba(255,255,255,26); }}")
        outer.addWidget(self._root)

        lay = QVBoxLayout(self._root)
        pad = int(14 * scale)
        lay.setContentsMargins(pad, int(11 * scale), pad, int(11 * scale))
        lay.setSpacing(int(8 * scale))

        metrics = cfg.overlay_metrics
        if "fps" in metrics:
            head = QHBoxLayout()
            head.setSpacing(int(14 * scale))
            self._fps = QLabel("—")
            self._fps.setFont(_mono(26, QFont.Weight.Bold, scale))
            self._fps.setStyleSheet(f"color: {theme.MUTE};")
            unit = QLabel("FPS")
            unit.setFont(_mono(7.5, QFont.Weight.Bold, scale))
            unit.setStyleSheet(f"color: {theme.accent_color(cfg.accent)};")
            unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
            head.addWidget(self._fps)
            head.addWidget(unit)
            # Media e lows moram ao lado do numero grande: e' a leitura que se faz
            # de um olho so' no meio da partida.
            self._sub = QLabel("")
            self._sub.setFont(_mono(8.5, QFont.Weight.DemiBold, scale))
            self._sub.setAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
            head.addStretch(1)
            head.addWidget(self._sub)
            lay.addLayout(head)
        else:
            self._fps = QLabel()
            self._sub = QLabel("")
            lay.addWidget(self._sub)

        # Numero sozinho nao mostra queda: o traco e' o que denuncia o engasgo que
        # ja' passou. Janela curta de proposito — o desenho fica mais liso.
        if "graph" in metrics:
            self._graph = Sparkline(theme.FPS, height=int(46 * scale),
                                    from_zero=True, line_width=2.4)
            self._graph.setMinimumWidth(int(230 * scale))
            lay.addWidget(self._graph)
        else:
            self._graph = None

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,22);")
        lay.addWidget(line)

        grid = QGridLayout()
        grid.setContentsMargins(0, int(3 * scale), 0, 0)
        grid.setHorizontalSpacing(int(10 * scale))
        grid.setVerticalSpacing(int(5 * scale))
        # Cada linha na cor da sua peca. Tudo cinza era o que fazia o overlay
        # sumir por cima de cenario claro. Potencia entra na linha da propria
        # peca: "68 W" na linha CPU ja' diz tudo, nao precisa de rotulo proprio.
        linhas = (("cpu", "CPU", theme.CPU), ("gpu", "GPU", theme.GPU),
                  ("ram", "RAM", theme.RAM), ("vram", "VRAM", theme.DISK),
                  ("ping", "PING", theme.NET), ("clock", "HORA", theme.FPS))
        wanted = [(k, lbl, cor) for k, lbl, cor in linhas if k in metrics]
        # Duas colunas quando ha' linha suficiente: torre estreita e alta rouba
        # muito mais canto de tela do que um bloco largo e baixo.
        colunas = cfg.overlay_columns or (2 if len(wanted) >= 5 else 1)
        colunas = max(1, min(colunas, max(1, len(wanted))))
        por_coluna = -(-len(wanted) // colunas)
        for i, (key, text, cor) in enumerate(wanted):
            bloco, linha = divmod(i, por_coluna)
            base = bloco * 4
            tag = QLabel(text)
            tag.setFont(_mono(8, QFont.Weight.Bold, scale))
            tag.setStyleSheet(f"color: {cor};")
            main = QLabel("—")
            main.setFont(_mono(9.5, QFont.Weight.DemiBold, scale))
            main.setAlignment(Qt.AlignmentFlag.AlignRight)
            sub = QLabel("")
            sub.setFont(_mono(8, QFont.Weight.Normal, scale))
            sub.setStyleSheet(f"color: {theme.TXT};")
            grid.addWidget(tag, linha, base)
            grid.addWidget(main, linha, base + 1)
            grid.addWidget(sub, linha, base + 2)
            self._rows[key] = (tag, main, sub)
        self._grid_cols = colunas
        for bloco in range(colunas):
            grid.setColumnStretch(bloco * 4 + 2, 1)
            if bloco + 1 < colunas:
                grid.setColumnMinimumWidth(bloco * 4 + 3, int(22 * scale))
        lay.addLayout(grid)

        # Assinatura discreta no rodape: identifica sem disputar espaco com o dado.
        rodape = QHBoxLayout()
        rodape.setContentsMargins(0, 0, 0, 0)
        marca = QLabel("dbx")
        marca.setFont(_mono(6.5, QFont.Weight.Bold, scale))
        marca.setStyleSheet(f"color: {theme.rgba(theme.accent_color(cfg.accent), 0.45)};")
        # De qual processo saem estes numeros. Com launcher, overlay de loja e
        # segunda janela na jogada, saber a origem evita ler o FPS errado.
        self._origem = QLabel("")
        self._origem.setFont(_mono(6.5, QFont.Weight.Normal, scale))
        self._origem.setStyleSheet(f"color: {theme.rgba(theme.TXT, 0.5)};")
        rodape.addWidget(self._origem)
        rodape.addStretch(1)
        rodape.addWidget(marca)
        lay.addLayout(rodape)

    def rebuild(self) -> None:
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)
        self._rows.clear()
        self._build()
        self.place()

    # ── posicionamento ───────────────────────────────────────────────────────
    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        win.set_clickthrough(hwnd, True)
        win.set_tool_window(hwnd)
        self.place()

    def place(self) -> None:
        self.adjustSize()
        screen = self._screen()
        if screen is None:
            return
        area = screen.geometry()
        m = max(8, int(area.height() * 0.012))
        w, h = self.width(), self.height()
        vert, _, horiz = self._ctl.settings.overlay_corner.partition("-")
        x = area.right() - w - m + 1 if horiz == "right" else area.left() + m
        y = area.bottom() - h - m + 1 if vert == "bottom" else area.top() + m
        self.move(int(x), int(y))

    # ── atualizacao ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        cfg = self._ctl.settings
        # O controlador chama a 8 Hz para o overlay acompanhar o mouse e o topmost,
        # mas numero trocando nessa velocidade nao da' para ler. O texto anda no
        # ritmo escolhido nas configuracoes.
        agora = time.monotonic()
        if agora - self._painted < 1.0 / max(1.0, cfg.overlay_refresh_hz):
            return
        self._painted = agora

        metrics = cfg.overlay_metrics
        stream = self._ctl.active_stream()

        if stream is not None:
            m = stream.metrics
            now = m.fps_now or m.fps_avg
            self._fps.setText(units.integer(now))
            self._fps.setStyleSheet(f"color: {theme.fps_color(now)};")
            # Cada numero na sua cor, a mesma do painel: cinza para tudo era o que
            # tornava o 1% low ilegivel por cima do jogo.
            parts = [_chunk("méd", units.integer(m.fps_avg), theme.FPS)]
            if "low1" in metrics:
                parts.append(_chunk("1%", units.integer(m.low_1), theme.WARN))
            if "frametime" in metrics:
                parts.append(_chunk("ft", units.ms(m.ft_avg, 1), theme.FRAME))
            self._sub.setText("&nbsp;&nbsp;".join(parts))
        else:
            self._fps.setText("—")
            self._fps.setStyleSheet(f"color: {theme.MUTE};")
            self._sub.setText(f"<span style='color:{theme.FAINT}'>sem jogo em foco</span>")

        origem = stream.app if stream is not None else ""
        alvo = getattr(self._ctl.ping, "target_label", "")
        if origem and alvo and alvo != origem:
            origem = f"{origem}  ·  ping {alvo}"
        self._origem.setText(origem or "sem captura")

        d = self._ctl.last_data() or {}
        g = d.get("gpu") or {}
        watts_on = "watts" in metrics
        # A coluna da direita carrega carga e frequencia: temperatura sozinha nao
        # diz se a peca esta' entregando clock ou se afundou por limite termico.
        if "cpu" in self._rows:
            temp = d.get("cpu_temp")
            self._set("cpu", units.temp(temp), theme.temp_color(temp),
                      f"{d.get('cpu_pct', 0):.0f}%  {_ghz(d.get('cpu_mhz'))}"
                      + (f"  {units.watts(d.get('cpu_watts'), 0)}" if watts_on else ""))
        if "gpu" in self._rows:
            # Hot spot e' o ponto mais quente do die e o que dita throttle; o
            # "GPU Core" e' uma media mais fria e mais otimista que a realidade.
            temp = g.get("temp_hotspot") or g.get("temp")
            self._set("gpu", units.temp(temp), theme.temp_color(temp),
                      f"{g.get('usage', 0):.0f}%  {_ghz(g.get('freq'))}"
                      + (f"  {units.watts(g.get('watts'), 0)}" if watts_on else ""))
        if "ram" in self._rows:
            self._set("ram",
                      f"{d.get('ram_used', 0):.1f}/{d.get('ram_total', 0):.0f}GB",
                      theme.load_color(d.get("ram_pct")),
                      f"{d.get('ram_pct', 0):.0f}%  {_ghz(d.get('ram_freq'))}")
        if "vram" in self._rows:
            self._set("vram",
                      f"{g.get('vram_used', 0) / 1024:.1f}/"
                      f"{g.get('vram_total', 0) / 1024:.1f}GB",
                      theme.load_color(g.get("vram_pct")),
                      f"{units.percent(g.get('vram_pct'))}  {_ghz(g.get('mem_freq'))}")
        if "ping" in self._rows:
            ping = d.get("ping_ms")
            perda = d.get("packet_loss")
            cor_perda = theme.BAD if (perda or 0) > 1 else theme.TXT
            self._rows["ping"][2].setStyleSheet(f"color: {cor_perda};")
            self._set("ping", units.ms(ping, 0), theme.ping_color(ping),
                      f"{perda:.0f}% perda" if perda is not None else "")
        if "clock" in self._rows:
            self._set("clock", datetime.now().strftime("%H:%M"), theme.TXT, "")
        if self._graph is not None:
            # Menos segundos na tela = cada ponto mais largo = tracado mais liso.
            valores = self._ctl.history.values("fps")
            passo = max(0.05, float(cfg.update_interval))
            self._graph.set_values(valores[-max(8, int(cfg.overlay_graph_seconds / passo)):])
        # Jogo mudou de monitor: refaz na escala da tela nova antes de reposicionar.
        if self._screen_key() != self._built_for:
            self.rebuild()
            return
        self.place()

    def _screen_key(self) -> tuple:
        screen = self._screen()
        if screen is None:
            return ()
        return (screen.name(), int(screen.logicalDotsPerInch()),
                screen.geometry().width(), screen.geometry().height())

    def _set(self, key: str, main: str, color: str, sub: str) -> None:
        row = self._rows.get(key)
        if row is None:
            return
        _tag, value, subtitle = row
        value.setText(main)
        value.setStyleSheet(f"color: {color};")
        subtitle.setText(sub)
