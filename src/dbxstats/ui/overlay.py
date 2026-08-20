"""Overlay in-game estilo RTSS: click-through, sempre no topo e configuravel.

O painel esta' organizado na ordem em que uma queda de FPS se investiga, e nao
na ordem em que os sensores existem:

    veredito  — o que esta' acontecendo (FPS, traco, quem esta' no limite)
    limite    — quem esta' segurando (CPU e GPU, com clock, tensao e calor)
    memoria   — o que esta' estourando (VRAM e RAM, com o quanto o jogo pegou)

Dai' a tensao morar entre o clock e a temperatura da mesma peca: clock caindo
com tensao caindo e temperatura no teto e' limite termico; clock serrilhando com
watts cravados e temperatura tranquila e' limite de energia. Em linhas separadas
esse par de leituras simplesmente nao existe.
"""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontMetricsF
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
from ..core import frames as fr
from ..core import units
from ..platform import win
from .charts import Sparkline
from .components import dimm_color

_MONO = "Cascadia Mono"
_FALLBACK = "Consolas"

# ── grade das linhas de peca ─────────────────────────────────────────────────
TAG, CARGA, CLOCK, VOLT, TEMP, CAUDA = range(6)
_COLUNAS = 6
_GUTTER = _COLUNAS          # coluna de folga entre um bloco e o seguinte

_LARGURAS = {TAG: 4, CARGA: 4, CLOCK: 7, VOLT: 6, TEMP: 8}
"""Largura de pior caso por coluna, em caracteres ("VRAM", "100%", "5.20GHz",
"1.118V", "81/104°C"). Reservada na construcao porque overlay que reflui no meio
da partida chama atencao pelo motivo errado: com a caixa fixa, um valor que
cresce, colapsa ou some so' troca o texto dentro dela e nada mais anda."""

_PECAS = ("cpu", "gpu")
_MEMORIAS = ("vram", "ram")
_TAGS = {"cpu": ("CPU", theme.CPU), "gpu": ("GPU", theme.GPU),
         "vram": ("VRAM", theme.DISK), "ram": ("RAM", theme.RAM)}

_CELULAS_BARRA = 10
"""Celulas da barra de memoria. Sem meio-bloco: precisao que ninguem le' nesse
corpo de letra, e o meio-bloco ainda muda de forma conforme a fonte que sobrar."""

_HOTSPOT_JUNTOS = 2.0
_HOTSPOT_SEPARA = 4.0
"""Histerese do ponto quente. Nesta RX 9070 XT o hotspot marca igual ao nucleo
("74/74" e' meia coluna gasta para nao dizer nada), mas no Ryzen o Tctl salta
15 graus em milissegundos — sem as duas bordas a celula piscaria a 3 Hz."""

_LOW_AFUNDOU = 0.5
"""Fracao da media abaixo da qual o 1% low ganha a seta. E' texto, e nao cor,
porque cerca de 8% dos homens nao separam verde de vermelho."""

_ALTURA_MAXIMA = 0.26
"""Fracao da tela a partir da qual o painel cai sozinho para o modo compacto.

Medido: o arranjo completo da' 256 px na escala 1.0 de um 1080p, contra os 280
px do limite — ou seja, na configuracao mais comum ele passa inteiro. O
rebaixamento existe para escala alta e tela baixa, onde a torre de numeros comeca
a tapar justamente o jogo que ela deveria estar medindo."""

_CORTE_COMPACTO = frozenset({
    "volts", "ram", "temps_mem", "jogo_ram", "jogo_ram_ws", "mem_clock",
    "mem_ctrl", "teto_watts", "ping", "clock",
})
"""O que sai no modo compacto: sobra FPS, traco, limite, CPU, GPU e VRAM."""


def rect_center(rect) -> tuple[int, int]:
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def _ghz(mhz: float | None) -> str:
    """Frequencia curta, mas com a unidade explicita.

    Sem o 'Hz' a coluna vira armadilha: '6.00G' ao lado de '18.4G' faz parecer
    que os dois sao gigabytes. Sem leitura devolve vazio, nunca travessao: um
    traco diz "quebrou", e celula em branco numa coluna de largura reservada diz
    "esta maquina nao publica isso", que e' a verdade.
    """
    if not mhz:
        return ""
    return f"{mhz / 1000:.2f}GHz" if mhz >= 1000 else f"{mhz:.0f}MHz"


def _pct(v: float | None) -> str:
    return "" if v is None else f"{v:.0f}%"


def _volt(v: float | None) -> str:
    return "" if not v else f"{v:.3f}V"


def _watt(v: float | None, teto: float | None = None) -> str:
    if v is None:
        return ""
    return f"{v:.0f}/{teto:.0f}W" if teto else f"{v:.0f}W"


def _gb(mib: float | None) -> float | None:
    return None if mib is None else mib / 1024.0


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


def _largura_cauda(metrics: set[str]) -> int:
    """Pior caso da ultima coluna, que e' compartilhada por quatro conteudos.

    Ela carrega watts nas linhas de peca e a cauda das linhas de memoria. Como a
    reserva e' feita uma vez, na construcao, ela tem que caber no maior texto que
    as opcoes ligadas conseguem produzir — senao a coluna cresce no meio do jogo.
    """
    watts = (9 if "teto_watts" in metrics else 5) if "watts" in metrics else 0
    vram = (8 if "mem_ctrl" in metrics else 0) + (9 if "mem_clock" in metrics else 0)
    ram = 0
    if "jogo_ram" in metrics:
        ram = 16 if "jogo_ram_ws" in metrics else 10
    if "mem_clock" in metrics:
        ram += 10
    return max(watts, vram, ram)


def _barra(usado: float | None, total: float | None, cor: str,
           destaque: float | None = None) -> str:
    """Barra de ocupacao em rich text, com uma fatia destacada opcional.

    Existe porque "falta de memoria" e' a unica das quatro causas que se le'
    melhor como proporcao: 15.8/16.0 pede um segundo de leitura, barra cheia pede
    zero. A fatia destacada entrega de graca, em dez caracteres, a relacao que o
    par de numeros nao conta — quanto do total e' o jogo.
    """
    if not total or usado is None:
        return ""
    cheias = max(0, min(_CELULAS_BARRA, round(_CELULAS_BARRA * usado / total)))
    marcadas = 0
    if destaque:
        marcadas = max(0, min(cheias, round(_CELULAS_BARRA * destaque / total)))
    # Meio tom solido em vez de alpha: rich text de QLabel nao mistura com o
    # fundo translucido do overlay, entao a transparencia sairia como cor chapada.
    meio = theme.mix(cor, theme.BG_SUNKEN, 0.55)
    partes = []
    if marcadas:
        partes.append(f"<span style='color:{cor}'>{'█' * marcadas}</span>")
    if cheias - marcadas:
        partes.append(f"<span style='color:{meio if marcadas else cor}'>"
                      f"{'█' * (cheias - marcadas)}</span>")
    if _CELULAS_BARRA - cheias:
        partes.append(f"<span style='color:{theme.FAINT}'>"
                      f"{'░' * (_CELULAS_BARRA - cheias)}</span>")
    return "".join(partes)


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
        self._cels: dict[tuple[str, int], QLabel] = {}
        self._cores: dict[tuple[str, int], str] = {}
        self._dados: dict[str, list[tuple[int, QLabel]]] = {}
        self._bases: list[int] = [0]
        self._largura_col: dict[int, int] = {}
        self._grade_viva: tuple = ()
        self._hotspot_junto: dict[str, bool] = {}
        self._built_for: tuple = ()
        self._painted = 0.0
        self._compacto = False
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

    def _metricas(self) -> set[str]:
        escolhidas = set(self._ctl.settings.overlay_metrics)
        return escolhidas - _CORTE_COMPACTO if self._compacto else escolhidas

    # ── construcao ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        cfg = self._ctl.settings
        self._built_for = self._screen_key()
        scale = cfg.overlay_scale * self._auto_scale()
        # Fundo mais leve: por cima do jogo o painel tem que informar, nao tapar.
        alpha = int(cfg.overlay_opacity * 165)
        metrics = self._metricas()

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
        lay.setSpacing(int(7 * scale))

        self._build_veredito(lay, cfg, metrics, scale)
        self._build_grade(lay, cfg, metrics, scale)
        self._build_rodape(lay, cfg, metrics, scale)

    def _build_veredito(self, lay, cfg, metrics: set[str], scale: float) -> None:
        """Bloco 0: o numero grande, o traco e a linha do gargalo."""
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

        # A linha mais assertiva do painel: responde "e' a placa, nao e' a CPU"
        # sem tirar o olho do jogo. O veredito ja' vem pronto do motor de quadros
        # (votacao por quadro, criterio do PresentMon) e nao custa sensor nenhum.
        self._limite_box = QWidget()
        linha = QHBoxLayout(self._limite_box)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(int(8 * scale))
        self._limite_tag = QLabel("LIMITE")
        self._limite_tag.setFont(_mono(8, QFont.Weight.Bold, scale))
        self._limite_tag.setStyleSheet(f"color: {theme.FAINT};")
        self._limite = QLabel("")
        self._limite.setFont(_mono(9.5, QFont.Weight.DemiBold, scale))
        self._engasgo = QLabel("")
        self._engasgo.setFont(_mono(9.5, QFont.Weight.DemiBold, scale))
        self._engasgo.setAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
        linha.addWidget(self._limite_tag)
        linha.addWidget(self._limite)
        linha.addStretch(1)
        linha.addWidget(self._engasgo)
        self._limite_box.setVisible(False)
        # Desligada, a linha nem entra no layout — e' por isso que o estado vive
        # aqui: um setVisible(True) num widget sem pai viraria uma janelinha
        # solta no meio da tela do jogo.
        self._limite_on = "limite" in metrics
        if self._limite_on:
            lay.addWidget(self._limite_box)

        regua = QFrame()
        regua.setFixedHeight(1)
        regua.setStyleSheet("background: rgba(255,255,255,22);")
        lay.addWidget(regua)

    def _build_grade(self, lay, cfg, metrics: set[str], scale: float) -> None:
        """Blocos 1 e 2: uma linha por peca, celulas de largura reservada."""
        grid = QGridLayout()
        grid.setContentsMargins(0, int(3 * scale), 0, 0)
        grid.setHorizontalSpacing(int(9 * scale))
        grid.setVerticalSpacing(int(4 * scale))

        linhas = [k for k in _PECAS + _MEMORIAS if k in metrics]
        # Uma coluna e' o arranjo: a adjacencia clock-tensao-temperatura dentro da
        # mesma peca e' a funcao do bloco 1. Duas colunas continuam possiveis
        # porque em tela baixa a torre alta rouba mais canto que um bloco largo.
        colunas = max(1, min(cfg.overlay_columns or 1, 2, max(1, len(linhas))))
        por_bloco = -(-len(linhas) // colunas) if linhas else 1
        self._bases = [b * (_COLUNAS + 1) for b in range(colunas)]

        fonte = _mono(9.5, QFont.Weight.DemiBold, scale)
        char = max(1.0, QFontMetricsF(fonte).horizontalAdvance("0"))
        self._largura_col = {c: int(char * n) for c, n in _LARGURAS.items()}
        self._largura_col[CAUDA] = int(char * _largura_cauda(metrics))

        direita = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for i, key in enumerate(linhas):
            bloco, linha = divmod(i, por_bloco)
            base = self._bases[bloco]
            texto, cor = _TAGS[key]
            tag = QLabel(texto)
            tag.setFont(_mono(8, QFont.Weight.Bold, scale))
            # So' a tag recebe cor de identidade. Se o valor tambem ganhasse cor
            # de peca, o vermelho de alarme deixaria de alarmar.
            tag.setStyleSheet(f"color: {cor};")
            grid.addWidget(tag, linha, base + TAG)
            self._cels[(key, TAG)] = tag
            self._dados[key] = []

            if key in _PECAS:
                colunas_linha = (CARGA, CLOCK, VOLT, TEMP, CAUDA)
            else:
                # Par + barra num label so', ocupando as colunas de clock e
                # tensao: mantem a temperatura na coluna compartilhada sem criar
                # alinhamento falso entre "1.118V" e uma barra de blocos.
                colunas_linha = (CARGA, TEMP, CAUDA)
            for c in colunas_linha:
                cel = QLabel("")
                cel.setFont(fonte)
                cel.setStyleSheet(f"color: {theme.TXT};")
                self._cores[(key, c)] = theme.TXT
                if key in _MEMORIAS and c == CARGA:
                    cel.setAlignment(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignVCenter)
                    grid.addWidget(cel, linha, base + c, 1, 3)
                else:
                    cel.setAlignment(direita)
                    grid.addWidget(cel, linha, base + c)
                self._cels[(key, c)] = cel
                self._dados[key].append((c, cel))

        for base in self._bases:
            for c, largura in self._largura_col.items():
                grid.setColumnMinimumWidth(base + c, largura)
            # A folga sobra nas ultimas colunas: com o texto alinhado a' direita,
            # isso vira espaco ANTES do numero e o painel respira sem que nada
            # mude de lugar quando um valor encolhe. Coluna sem conteudo nenhum
            # fica de fora, senao a folga se acumularia numa borda vazia.
            grid.setColumnStretch(base + TEMP, 1)
            if self._largura_col[CAUDA]:
                grid.setColumnStretch(base + CAUDA, 1)
            if base != self._bases[-1]:
                grid.setColumnMinimumWidth(base + _GUTTER, int(22 * scale))
        lay.addLayout(grid)
        self._grade = grid
        self._grade_viva = ()

    def _build_rodape(self, lay, cfg, metrics: set[str], scale: float) -> None:
        """Bloco 3: estado e procedencia, no menor corpo do painel."""
        rodape = QHBoxLayout()
        rodape.setContentsMargins(0, 0, 0, 0)
        rodape.setSpacing(int(10 * scale))
        pequena = _mono(6.5, QFont.Weight.Normal, scale)

        self._ping = QLabel("")
        self._ping.setFont(pequena)
        self._perda = QLabel("")
        self._perda.setFont(pequena)
        # De qual processo saem estes numeros. Com launcher, overlay de loja e
        # segunda janela na jogada, saber a origem evita ler o FPS errado.
        self._origem = QLabel("")
        self._origem.setFont(pequena)
        self._origem.setStyleSheet(f"color: {theme.rgba(theme.TXT, 0.5)};")
        self._hora = QLabel("")
        self._hora.setFont(pequena)
        self._hora.setStyleSheet(f"color: {theme.rgba(theme.TXT, 0.5)};")
        # Assinatura discreta: identifica sem disputar espaco com o dado.
        marca = QLabel("dbx")
        marca.setFont(_mono(6.5, QFont.Weight.Bold, scale))
        marca.setStyleSheet(f"color: {theme.rgba(theme.accent_color(cfg.accent), 0.45)};")

        self._ping.setVisible("ping" in metrics)
        self._perda.setVisible(False)
        self._hora.setVisible("clock" in metrics)
        for w in (self._ping, self._perda, self._origem):
            rodape.addWidget(w)
        rodape.addStretch(1)
        rodape.addWidget(self._hora)
        rodape.addWidget(marca)
        lay.addLayout(rodape)

        # Um aviso, uma vez, no rodape — nunca um aviso por celula. Sem elevacao
        # a tensao do processador e a temperatura dos pentes nem aparecem na
        # arvore do LHM: some a coluna inteira, e o motivo tem que caber em algum
        # lugar ou a pessoa conclui que a maquina nao tem os sensores.
        self._aviso = QLabel("Vcore e temp dos pentes pedem administrador")
        self._aviso.setFont(pequena)
        self._aviso.setStyleSheet(f"color: {theme.WARN};")
        self._aviso.setVisible(bool(metrics & {"volts", "temps_mem"})
                               and not win.is_admin())
        lay.addWidget(self._aviso)

    def rebuild(self) -> None:
        """Refaz o painel do zero; e' o que as configuracoes chamam ao salvar.

        A densidade volta a ser reavaliada: quem acabou de baixar a escala tem
        que reaver o arranjo inteiro, e nao ficar preso no compacto que um valor
        antigo tinha forcado.
        """
        self._compacto = False
        self._reconstruir()

    def _reconstruir(self) -> None:
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)
        self._cels.clear()
        self._cores.clear()
        self._dados.clear()
        self._build()
        # Pinta antes de posicionar: a grade nova nasce vazia, e sem isto o painel
        # ficaria em branco ate' o proximo tique — um terco de segundo de overlay
        # apagado bem no momento em que ele mudou de forma.
        self._pintar()
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
        if not self._compacto and self.height() > area.height() * _ALTURA_MAXIMA:
            # So' desce, nunca sobe de volta sozinho: alternar entre os dois
            # arranjos daria um painel piscando entre dois tamanhos, ja' que o
            # compacto sempre cabe onde o completo nao coube.
            self._compacto = True
            self._reconstruir()
            return
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

        self._pintar()
        # Jogo mudou de monitor: refaz na escala da tela nova antes de reposicionar.
        if self._screen_key() != self._built_for:
            self.rebuild()
            return
        self.place()

    def _pintar(self) -> None:
        cfg = self._ctl.settings
        metrics = self._metricas()
        stream = self._ctl.active_stream()
        d = self._ctl.last_data() or {}
        g = d.get("gpu") or {}

        self._pintar_veredito(stream, metrics)
        self._pintar_pecas(d, g, metrics)
        self._pintar_memoria(d, g, stream, metrics)
        self._pintar_rodape(d, stream, metrics)
        self._aplicar_grade()

        if self._graph is not None:
            # Menos segundos na tela = cada ponto mais largo = tracado mais liso.
            valores = self._ctl.history.values("fps")
            passo = max(0.05, float(cfg.update_interval))
            self._graph.set_values(valores[-max(8, int(cfg.overlay_graph_seconds / passo)):])

    def _screen_key(self) -> tuple:
        screen = self._screen()
        if screen is None:
            return ()
        return (screen.name(), int(screen.logicalDotsPerInch()),
                screen.geometry().width(), screen.geometry().height())

    def _pintar_veredito(self, stream, metrics: set[str]) -> None:
        if stream is None:
            self._fps.setText("—")
            self._fps.setStyleSheet(f"color: {theme.MUTE};")
            self._sub.setText(f"<span style='color:{theme.FAINT}'>sem captura</span>")
            self._limite_box.setVisible(False)
            return

        m = stream.metrics
        now = m.fps_now or m.fps_avg
        self._fps.setText(units.integer(now))
        self._fps.setStyleSheet(f"color: {theme.fps_color(now)};")
        # Cada numero na sua cor, a mesma do painel: cinza para tudo era o que
        # tornava o 1% low ilegivel por cima do jogo.
        parts = [_chunk("méd", units.integer(m.fps_avg), theme.FPS)]
        if "low1" in metrics:
            afundou = (m.low_1 is not None and m.fps_avg
                       and m.low_1 < m.fps_avg * _LOW_AFUNDOU)
            parts.append(_chunk("1%", units.integer(m.low_1) + (" ▼" if afundou else ""),
                                theme.WARN))
        if "frametime" in metrics:
            parts.append(_chunk("ft", units.ms(m.ft_avg, 1), theme.FRAME))
        self._sub.setText("&nbsp;&nbsp;".join(parts))

        veredito, cor = _veredito(m)
        self._limite.setText(veredito)
        self._limite.setStyleSheet(f"color: {cor};")
        # A janela do veredito e' a de analise (60 s por padrao), e o painel
        # repinta a 3 Hz: o rotulo responde "quem segurou o ultimo minuto", nao
        # "quem esta' segurando agora". A porcentagem ao lado existe para isso —
        # ela diz o quanto do minuto sustenta a afirmacao.
        engasgo = f"engasgo {m.stutter_pct:.1f}%" if m.frames else ""
        self._engasgo.setText(engasgo)
        self._engasgo.setStyleSheet(f"color: {theme.stutter_color(m.stutter_pct)};")
        self._limite_tag.setVisible(bool(veredito))
        self._limite.setVisible(bool(veredito))
        self._engasgo.setVisible(bool(engasgo))
        self._limite_box.setVisible(self._limite_on and bool(veredito or engasgo))

    def _pintar_pecas(self, d: dict, g: dict, metrics: set[str]) -> None:
        volts = "volts" in metrics
        watts = "watts" in metrics
        teto = "teto_watts" in metrics
        if "cpu" in self._dados:
            self._set("cpu", CARGA, _pct(d.get("cpu_pct")),
                      theme.load_color(d.get("cpu_pct")))
            self._set("cpu", CLOCK, _ghz(d.get("cpu_mhz")))
            self._set("cpu", VOLT, _volt(d.get("cpu_volts")) if volts else "")
            # Duas temperaturas por peca: a de trabalho e o ponto quente. Uma so'
            # sempre mente para algum lado — a media esconde throttle, o pico
            # assusta a toa. Juntas dizem se o calor esta' espalhado ou concentrado.
            self._temps("cpu", d.get("cpu_temp_cores"),
                        d.get("cpu_temp_package") or d.get("cpu_temp"),
                        theme.temp_color)
            self._set("cpu", CAUDA,
                      _watt(d.get("cpu_watts")) if watts else "")
        if "gpu" in self._dados:
            self._set("gpu", CARGA, _pct(g.get("usage")), theme.load_color(g.get("usage")))
            self._set("gpu", CLOCK, _ghz(g.get("freq")))
            self._set("gpu", VOLT, _volt(g.get("volts")) if volts else "")
            self._temps("gpu", g.get("temp"), g.get("temp_hotspot"), theme.temp_color)
            limite = (g.get("power_limit") or (g.get("static") or {}).get("power_limit")
                      if teto else None)
            self._set("gpu", CAUDA, _watt(g.get("watts"), limite) if watts else "")

    def _pintar_memoria(self, d: dict, g: dict, stream, metrics: set[str]) -> None:
        if "vram" in self._dados:
            usado, total = _gb(g.get("vram_used")), _gb(g.get("vram_total"))
            par = f"{usado:.1f}/{total:.1f}GB" if total else ""
            barra = _barra(usado, total, theme.DISK)
            self._set("vram", CARGA, f"{par}&nbsp;&nbsp;{barra}" if par else "")
            self._set("vram", TEMP, "")
            if "temps_mem" in metrics and g.get("temp_vram") is not None:
                self._set("vram", TEMP, units.temp(g["temp_vram"]).replace(" ", ""),
                          theme.vram_temp_color(g["temp_vram"]))
            cauda = []
            if "mem_ctrl" in metrics and g.get("mem_ctrl") is not None:
                cauda.append(f"ctrl {g['mem_ctrl']:.0f}%")
            if "mem_clock" in metrics and g.get("mem_freq"):
                cauda.append(_ghz(g.get("mem_freq")))
            self._set("vram", CAUDA, " ".join(cauda))

        if "ram" in self._dados:
            usado, total = d.get("ram_used"), d.get("ram_total")
            # Jogo vivo e' o que o motor de FPS esta' medindo agora. Comparar o pid
            # evita a cauda congelar no ultimo valor por um ciclo do coletor
            # inteiro depois de o jogo fechar — numero parado mente.
            pid = stream.pid if stream is not None else 0
            jogo = d.get("game_ram_private") if d.get("game_pid") == pid and pid else None
            par = f"{usado:.1f}/{total:.1f}GB" if total else ""
            barra = _barra(usado, total, theme.RAM,
                           destaque=(jogo or 0) / 1024.0 if jogo else None)
            self._set("ram", CARGA, f"{par}&nbsp;&nbsp;{barra}" if par else "")
            self._set("ram", TEMP, "")
            if "temps_mem" in metrics and d.get("ram_temp") is not None:
                self._set("ram", TEMP, units.temp(d["ram_temp"]).replace(" ", ""),
                          dimm_color(d))
            cauda = []
            if "jogo_ram" in metrics and jogo:
                wset = d.get("game_ram_wset")
                if "jogo_ram_ws" in metrics and wset:
                    cauda.append(f"jogo {jogo / 1024:.1f}/{wset / 1024:.1f}G")
                else:
                    cauda.append(f"jogo {jogo / 1024:.1f}G")
            if "mem_clock" in metrics and d.get("ram_freq"):
                # MT/s, nunca GHz: "6.00GHz" logo abaixo de "5.20GHz" convida a
                # comparar coisas que nao se comparam.
                cauda.append(f"{d['ram_freq']:.0f}MT/s")
            self._set("ram", CAUDA, " ".join(cauda))

    def _pintar_rodape(self, d: dict, stream, metrics: set[str]) -> None:
        if "ping" in metrics:
            ping = d.get("ping_ms")
            # Partida sem servidor nao tem ping que interesse. Mostrar a
            # latencia ate' um DNS publico no meio de um jogo local so' ocuparia
            # espaco com um numero que nao diz nada sobre o que esta' na tela.
            online = getattr(self._ctl, "jogo_online", lambda: None)()
            if online is False:
                self._ping.setText("local")
                self._ping.setStyleSheet(f"color: {theme.MUTE};")
                self._ping.setVisible(True)
            else:
                self._ping.setText(f"ping {units.ms(ping, 0).replace(' ', '')}"
                                   if ping is not None else "")
                self._ping.setStyleSheet(f"color: {theme.ping_color(ping)};")
                self._ping.setVisible(ping is not None)
            perda = d.get("packet_loss")
            # Zero nao e' noticia: "0% perda" ocupava largura a partida inteira
            # para dizer que nada aconteceu.
            self._perda.setText(f"perda {perda:.0f}%" if perda else "")
            self._perda.setStyleSheet(f"color: {theme.BAD};")
            self._perda.setVisible(bool(perda))

        origem = stream.app if stream is not None else ""
        # O alvo do ping so' e' noticia quando ele deixou de ser o host fixo e
        # passou a seguir o servidor da partida; repetir "8.8.8.8" a partida
        # inteira ao lado do numero de ping nao acrescenta nada.
        alvo = getattr(self._ctl.ping, "target_label", "")
        if origem and alvo and getattr(self._ctl.ping, "following_game", False):
            origem = f"{origem}  ·  {alvo}"
        # Sem jogo o rodape fica vazio: o "sem captura" ja' esta' no lugar do
        # sub, ao lado do numero grande, e dizer duas vezes so' gasta linha.
        self._origem.setText(origem)
        if "clock" in metrics:
            self._hora.setText(datetime.now().strftime("%H:%M"))

    # ── celulas ──────────────────────────────────────────────────────────────
    def _set(self, linha: str, coluna: int, texto: str, cor: str | None = None) -> None:
        cel = self._cels.get((linha, coluna))
        if cel is None:
            return
        cel.setText(texto)
        # Trocar folha de estilo custa recalculo; a 3 Hz, em quatro linhas, isso
        # e' desperdicio puro quando a cor nao mudou.
        if cor is not None and cor != self._cores.get((linha, coluna)):
            self._cores[(linha, coluna)] = cor
            cel.setStyleSheet(f"color: {cor};")

    def _temps(self, linha: str, media, pico, cor) -> None:
        """Media e ponto quente na mesma celula, com histerese no colapso.

        Quando a maquina so' expoe uma das duas, mostra a que existe em vez de um
        travessao ao lado de um numero: placa e processador variam muito no que
        publicam, e furo de sensor nao pode virar buraco no overlay.
        """
        valores = [v for v in (media, pico) if v is not None]
        if not valores:
            self._set(linha, TEMP, "")
            return
        if len(valores) == 1:
            self._set(linha, TEMP, f"{valores[0]:.0f}°C", cor(valores[0]))
            return
        delta = abs(pico - media)
        junto = self._hotspot_junto.get(linha, True)
        if junto and delta > _HOTSPOT_SEPARA:
            junto = False
        elif not junto and delta < _HOTSPOT_JUNTOS:
            junto = True
        self._hotspot_junto[linha] = junto
        if junto:
            alto = max(media, pico)
            self._set(linha, TEMP, f"{alto:.0f}°C", cor(alto))
            return
        # A unidade aparece uma vez so'. Repetir "°C" nos dois numeros custa
        # largura que o overlay nao tem de sobra e nao esclarece nada.
        self._set(linha, TEMP,
                  f"<span style='color:{cor(media)}'>{media:.0f}</span>"
                  f"<span style='color:{theme.FAINT}'>/</span>"
                  f"<span style='color:{cor(pico)}'>{pico:.0f}°C</span>")

    def _aplicar_grade(self) -> None:
        """Coluna sem fonte colapsa e a grade encolhe; peca ausente perde a linha.

        Sao tres casos e nenhuma excecao: coluna vazia em todas as linhas some
        (a maquina nao publica aquilo); celula vazia numa coluna que serve a outra
        linha fica em branco, com a largura reservada mantida; peca inteira
        ausente derruba a linha. Travessao nao entra em nenhum dos tres — ele diz
        "quebrou" quando nada quebrou.
        """
        vivas = {k for k, cels in self._dados.items()
                 if any(cel.text() for _c, cel in cels)}
        colunas = {c for k in vivas for c, cel in self._dados[k] if cel.text()}
        estado = (tuple(sorted(vivas)), tuple(sorted(colunas)))
        if estado == self._grade_viva:
            return
        self._grade_viva = estado
        for key, cels in self._dados.items():
            viva = key in vivas
            tag = self._cels.get((key, TAG))
            if tag is not None:
                tag.setVisible(viva)
            for c, cel in cels:
                cel.setVisible(viva and c in colunas)
        for base in self._bases:
            for c, largura in self._largura_col.items():
                # A coluna das tags nunca colapsa: ela nao carrega leitura de
                # sensor nenhum, e' a identidade da linha.
                viva = c == TAG or c in colunas
                self._grade.setColumnMinimumWidth(base + c, largura if viva else 0)


def _veredito(m) -> tuple[str, str]:
    """Rotulo curto de gargalo e sua cor, na mesma regra do painel.

    Sem quadros pareados o motor devolve "indisponivel" ou "coletando": nesses
    dois casos a linha inteira some, porque um veredito sem base e' pior que
    nenhum — ele parece uma resposta.
    """
    # A porcentagem pode faltar mesmo com o veredito presente: um resultado
    # relido do disco traz o rotulo salvo, mas nao necessariamente os campos que
    # entraram depois. Formatar None estourava e derrubava o overlay inteiro.
    def _com_pct(rotulo: str, valor, cor: str) -> tuple[str, str]:
        return (f"{rotulo} {valor:.0f}%" if valor is not None else rotulo), cor

    if m.bottleneck == fr.BOTTLENECK_GPU:
        return _com_pct("GPU", m.gpu_bound_pct, theme.GPU)
    if m.bottleneck == fr.BOTTLENECK_CPU:
        return _com_pct("CPU", m.cpu_bound_pct, theme.CPU)
    if m.bottleneck == fr.BOTTLENECK_CAP:
        return _com_pct("cap/VSync", m.capped_pct, theme.FAINT)
    if m.bottleneck == fr.BOTTLENECK_BALANCED:
        return "os dois", theme.TXT
    return "", theme.FAINT
