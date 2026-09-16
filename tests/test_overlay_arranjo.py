"""O arranjo do overlay: o que some, o que fica em branco e o que nunca se move.

O overlay e' desenhado por cima do jogo e ninguem vai conferi-lo com calma no
meio de uma partida. Os riscos cobertos aqui sao os que passam despercebidos e
estragam a leitura: sensor que falta virar travessao (que se le' como "quebrou"),
peca ausente deixando uma linha oca, coluna reservada mudando de largura quando
um valor encolhe, e a cauda do jogo congelando no ultimo numero depois que o
processo morreu.
"""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from vantage.config import OVERLAY_METRICS, Settings  # noqa: E402
from vantage.core import frames as fr  # noqa: E402
from vantage.ui import overlay as ov  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Metrics:
    frames = 5200
    fps_now = 98.0
    fps_avg = 141.0
    low_1 = 62.0
    ft_avg = 10.2
    stutter_pct = 2.8
    bottleneck = fr.BOTTLENECK_GPU
    cpu_bound_pct = 2.0
    gpu_bound_pct = 96.0
    capped_pct = 1.0


class _Stream:
    app = "jogo.exe"
    pid = 4242

    def __init__(self) -> None:
        self.metrics = _Metrics()


class _Hist:
    def values(self, _chave):
        return [140.0] * 60


class _Ping:
    target_label = "8.8.8.8"
    following_game = False


class _Ctl:
    def __init__(self, dados, stream=None, **opcoes) -> None:
        self.settings = Settings()
        for chave, valor in opcoes.items():
            setattr(self.settings, chave, valor)
        self.ping = _Ping()
        self.history = _Hist()
        self._d = dados
        self._s = stream

    def last_data(self):
        return self._d

    def active_stream(self):
        return self._s


def _snapshot(**mudancas) -> dict:
    d = {
        "cpu_pct": 38.0, "cpu_mhz": 5200, "cpu_watts": 71.0,
        "cpu_temp": 82.0, "cpu_temp_cores": 69.0, "cpu_temp_package": 82.0,
        "cpu_volts": 1.118,
        "ram_used": 27.9, "ram_total": 31.6, "ram_pct": 88.0, "ram_freq": 6000,
        "ram_temp": 47.0,
        "ram_modules": [{"slot": "DIMM #1", "temp": 47.0, "high": 55.0,
                         "critical": 85.0, "model": "A-DATA (#1)"}],
        "game_pid": 4242, "game_name": "jogo.exe",
        "game_ram_private": 14950.0, "game_ram_wset": 12390.0,
        "ping_ms": 23.0, "packet_loss": 0.0,
        "gpu": {"usage": 99.0, "freq": 2440, "volts": 0.928, "watts": 289.0,
                "temp": 81, "temp_hotspot": 104, "temp_vram": 101, "mem_ctrl": 94.0,
                "vram_used": 15810, "vram_total": 16384, "vram_pct": 96.5},
    }
    d.update(mudancas)
    return d


def _montar(dados, stream=None, **opcoes) -> ov.GameOverlay:
    painel = ov.GameOverlay(_Ctl(dados, stream, **opcoes))
    painel.refresh()
    painel.adjustSize()
    return painel


def _texto(painel, linha: str, coluna: int) -> str:
    return painel._cels[(linha, coluna)].text()


def _visivel(painel, linha: str, coluna: int) -> bool:
    cel = painel._cels.get((linha, coluna))
    return cel is not None and not cel.isHidden()


def test_coluna_sem_fonte_nenhuma_colapsa_e_a_grade_encolhe():
    """Sem tensao em lugar nenhum, a coluna inteira sai; nao vira fileira de traco.

    E' o caso da maquina sem elevacao e da placa que nao publica o rail: uma
    coluna de travessoes diria "quebrou" quatro vezes por linha.
    """
    d = _snapshot(cpu_volts=None)
    d["gpu"]["volts"] = None
    painel = _montar(d, _Stream())
    assert not _visivel(painel, "cpu", ov.VOLT)
    assert not _visivel(painel, "gpu", ov.VOLT)
    assert painel._grade.columnMinimumWidth(ov.VOLT) == 0
    # A temperatura continua de pe': ela tem fonte nas duas linhas.
    assert _visivel(painel, "cpu", ov.TEMP)


def test_celula_vazia_fica_em_branco_quando_a_coluna_serve_a_outra_linha():
    """Branco em coluna reservada e' estrutura; travessao seria ruido."""
    d = _snapshot()
    d["gpu"]["temp_vram"] = None
    painel = _montar(d, _Stream())
    assert _texto(painel, "vram", ov.TEMP) == ""
    assert _visivel(painel, "vram", ov.TEMP)
    assert painel._grade.columnMinimumWidth(ov.TEMP) > 0


def test_peca_ausente_derruba_a_linha_inteira():
    """Sem GPU nao ha' linha de GPU nem de VRAM: nem tag, nem celula."""
    painel = _montar(_snapshot(gpu=None), _Stream())
    assert painel._cels[("gpu", ov.TAG)].isHidden()
    assert painel._cels[("vram", ov.TAG)].isHidden()
    assert not painel._cels[("cpu", ov.TAG)].isHidden()


def test_gpu_sem_sensor_de_memoria_perde_a_linha_de_vram():
    """Sem os dois sensores a linha some inteira, e nao vira "0.0/0.0GB" com barra.

    A barra vazia e' o pior desfecho possivel: dez celulas de trilho se leem como
    "VRAM sobrando" quando o certo e' "nao sei medir a VRAM desta placa".
    """
    d = _snapshot()
    d["gpu"] = dict(d["gpu"], vram_used=None, vram_total=None, vram_pct=None,
                    mem_ctrl=None, temp_vram=None)
    painel = _montar(d, _Stream())
    assert _texto(painel, "vram", ov.CARGA) == ""
    assert painel._cels[("vram", ov.TAG)].isHidden()
    # A linha da GPU continua viva: uso e temperatura essa placa publica.
    assert not painel._cels[("gpu", ov.TAG)].isHidden()


def test_nenhuma_celula_de_peca_mostra_travessao():
    """Numa maquina sem sensor nenhum, o painel fica vazio; nunca furado."""
    pelado = {"cpu_pct": 12.0, "ram_used": 7.8, "ram_total": 16.0, "gpu": None}
    painel = _montar(pelado, None)
    for (_linha, coluna), cel in painel._cels.items():
        if coluna != ov.TAG:
            assert "—" not in cel.text()


def test_veredito_sem_base_apaga_a_linha_do_limite():
    """Captura sem CPUBusy/GPUBusy nao pode virar um palpite com cara de resposta."""
    stream = _Stream()
    stream.metrics.bottleneck = fr.BOTTLENECK_NA
    stream.metrics.frames = 0
    painel = _montar(_snapshot(), stream)
    assert painel._limite_box.isHidden()


def test_veredito_mostra_a_fatia_de_quadros_que_o_sustenta():
    """"GPU" sozinho nao diz se foram 61% dos quadros ou 99%."""
    painel = _montar(_snapshot(), _Stream())
    assert painel._limite.text() == "GPU 96%"
    assert not painel._limite_box.isHidden()


def test_cauda_do_jogo_some_no_instante_em_que_o_pid_muda():
    """Numero de RAM congelado no jogo anterior mente com cara de medida.

    O coletor so' larga as chaves no ciclo dele; o overlay compara o pid a cada
    pintura para nao mostrar a memoria de um processo que ja' morreu.
    """
    outro = _Stream()
    outro.pid = 777
    painel = _montar(_snapshot(), outro)
    assert "jogo" not in _texto(painel, "ram", ov.CAUDA)


def test_largura_reservada_nao_muda_quando_o_valor_encolhe():
    """Overlay que reflui no meio da partida chama atencao pelo motivo errado."""
    painel = _montar(_snapshot(), _Stream())
    antes = painel._grade.columnMinimumWidth(ov.CARGA)
    painel._ctl._d = _snapshot(cpu_pct=9.0)
    painel._painted = 0.0
    painel.refresh()
    assert painel._grade.columnMinimumWidth(ov.CARGA) == antes


def test_duas_colunas_nao_perdem_nenhuma_linha():
    """O formato de duas colunas e' opcao de tela baixa, nao um corte de dado."""
    painel = _montar(_snapshot(), _Stream(), overlay_columns=2)
    assert len(painel._bases) == 2
    for linha in ("cpu", "gpu", "vram", "ram"):
        assert not painel._cels[(linha, ov.TAG)].isHidden(), linha


def test_rebaixamento_automatico_nao_deixa_o_painel_em_branco():
    """Escala alta encolhe o arranjo, mas a grade nova tem que nascer preenchida.

    A reconstrucao troca todos os rotulos; sem repintar na hora, o overlay
    ficaria apagado ate' o tique seguinte, justo quando acabou de mudar de forma.
    """
    painel = _montar(_snapshot(), _Stream(), overlay_scale=2.5)
    assert painel._compacto
    assert _texto(painel, "cpu", ov.CARGA) == "38%"
    assert not _visivel(painel, "cpu", ov.VOLT)


def test_barra_destaca_a_fatia_do_jogo_dentro_do_usado():
    """A barra existe para responder "quanto disso e' o jogo" sem gastar numero."""
    barra = ov._barra(20.0, 40.0, "#A78BFA", destaque=10.0)
    assert barra.count("█") == 5
    assert barra.count("░") == 5
    # Duas cores dentro do usado: a fatia do jogo e o resto do sistema.
    assert barra.count("<span") == 3


def test_barra_sem_total_nao_desenha_nada():
    """Total zero viria de sensor mudo; uma barra vazia parece memoria livre."""
    assert ov._barra(5.0, None, "#A78BFA") == ""


def test_frequencia_sem_leitura_devolve_vazio_e_nao_traco():
    assert ov._ghz(None) == ""
    assert ov._ghz(5200) == "5.20GHz"


def test_toda_metrica_do_arranjo_pode_ser_desligada():
    """Chave que o overlay usa sem estar na lista de escolha e' opcao invisivel."""
    conhecidas = {k for k, _ in OVERLAY_METRICS}
    usadas = {"fps", "graph", "low1", "frametime", "limite", "cpu", "gpu", "watts",
              "volts", "vram", "ram", "temps_mem", "mem_ctrl", "jogo_ram",
              "engasgo", "mem_clock", "teto_watts", "ping", "clock"}
    assert usadas <= conhecidas


def test_desligar_tudo_menos_o_fps_nao_quebra_o_painel():
    """Lista curta e' estado legitimo, e ja' quebrou layout antes."""
    painel = _montar(_snapshot(), _Stream(), overlay_metrics=["fps"])
    assert painel._fps.text() == "98"
    assert [w for w in painel.findChildren(QLabel) if w.text()]


# ── rebaixamento automatico para o modo compacto ─────────────────────────────
_ALTURAS_REAIS = {
    "1280x720 (TV)": (203, 720),
    "1366x768 (notebook)": (203, 768),
    "1920x1080": (271, 1080),
    "3440x1440 (ultrawide)": (352, 1440),
    "3840x2160": (352, 2160),
}
"""(altura do painel, altura da tela) com TODAS as metricas ligadas na escala 1.0.

Medido com a fonte real do sistema, fora do pytest: a plataforma offscreen do Qt
nao tem familia de fonte nenhuma nesta maquina, mede todo glifo com o mesmo
avanco e devolve um painel 41% mais baixo que o de verdade. Medir a altura aqui
dentro daria um numero confortavel e falso: por isso o que se testa e' a
decisao (`cabe_na_tela`), alimentada com as alturas que o painel tem mesmo.
"""


def test_o_conjunto_padrao_nunca_nasce_rebaixado():
    """Rebaixar no padrao apaga metade das metricas de quem nao pediu nada.

    O limiar era 26% da tela e o painel completo ocupa entre 24% e 27%: numa TV
    de 720p o overlay ja' abria cortado, e a tela de Configuracoes continuava com
    tudo marcado. Nao ha' como descobrir isso de dentro do jogo.
    """
    for tela, (painel, altura) in _ALTURAS_REAIS.items():
        assert ov.cabe_na_tela(painel, altura), tela


def test_ha_folga_para_o_painel_crescer_antes_de_rebaixar():
    """Sem folga, uma linha nova ou uma fonte mais alta corta metricas em silencio.

    A familia preferida (Cascadia Mono) nem esta' instalada em toda maquina: onde
    ela entra no lugar da Consolas o painel cresce sozinho, sem ninguem mexer em
    nada. Um quarto de folga absorve isso e ainda sobra para uma linha a mais.
    """
    for tela, (painel, altura) in _ALTURAS_REAIS.items():
        assert ov.cabe_na_tela(painel * 1.25, altura), tela


def test_escala_grande_em_tela_baixa_continua_rebaixando():
    """O rebaixamento nao pode virar letra morta: e' ele que impede tapar o jogo."""
    assert not ov.cabe_na_tela(203 * 1.6, 720)
    assert not ov.cabe_na_tela(271 * 1.6, 1080)


def test_o_painel_rebaixado_diz_que_esta_rebaixado():
    """Dez metricas somem no compacto; sem uma palavra no rodape ninguem liga uma
    coisa a' outra e a busca vai parar no sensor ou na configuracao."""
    painel = _montar(_snapshot(), _Stream(), overlay_scale=2.5)
    assert painel._compacto
    assert painel._marca_compacto.text()
    assert not painel._marca_compacto.isHidden()


def test_painel_inteiro_nao_carrega_marca_de_compacto():
    """Aviso permanente vira ruido e deixa de ser aviso."""
    painel = _montar(_snapshot(), _Stream())
    assert not painel._compacto
    assert painel._marca_compacto.isHidden()


def test_o_aviso_de_administrador_sobrevive_ao_corte_do_compacto(monkeypatch):
    """O aviso explica colunas que sumiram; no compacto ele sumia junto com elas.

    Sobrava a pior combinacao possivel: Configuracoes com "Tensao" marcada,
    painel sem tensao nenhuma e nenhuma linha dizendo por que.
    """
    monkeypatch.setattr(ov.win, "is_admin", lambda: False)
    painel = _montar(_snapshot(), _Stream(), overlay_scale=2.5)
    assert painel._compacto
    assert "volts" not in painel._metricas()
    assert not painel._aviso.isHidden()


# ── legibilidade por cima do jogo ────────────────────────────────────────────
_CENA_CLARA = (255, 255, 255)
"""Pior fundo possivel: neve, deserto, menu branco. O painel e' translucido, entao
a cor por tras entra na conta; testar so' sobre preto testa o caso facil."""

_MINIMO_CONTRASTE = 3.0
"""Razao de contraste minima aceita para qualquer tinta do painel.

E' o piso do WCAG para texto grande e para elemento grafico. Abaixo disso o
rotulo GARGALO, o trilho da barra e a barra "/" entre as duas temperaturas
simplesmente somem, e "69/82°C" passa a ser lido como "69 82°C": erro de
leitura, e nao feiura.
"""

_HEX = re.compile(r"#([0-9A-Fa-f]{6})")
_RGBA = re.compile(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)")


def _luminancia(cor) -> float:
    def canal(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * canal(cor[0]) + 0.7152 * canal(cor[1]) + 0.0722 * canal(cor[2]))


def _contraste(a, b) -> float:
    la, lb = _luminancia(a), _luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _sobre(cor, alpha: float, fundo):
    return tuple(round(c * alpha + f * (1 - alpha)) for c, f in zip(cor, fundo, strict=True))


def _fundo_do_painel(painel, cena=_CENA_CLARA):
    """Cor que o fundo do painel assume de fato com a cena atras dele.

    Lido da folha de estilo que o painel declarou, e nao de uma constante copiada
    para ca': o risco e' justamente o mapa de opacidade mudar e o teste continuar
    medindo o painel de ontem.
    """
    r, g, b, a = _RGBA.search(painel._root.styleSheet()).groups()
    return _sobre((int(r), int(g), int(b)), int(a) / 255.0, cena)


def _tintas(painel, fundo) -> dict:
    """Toda cor de texto que o painel pinta, ja' resolvida contra o fundo."""
    cores = {}
    for w in painel.findChildren(QLabel):
        for fonte in (w.styleSheet(), w.text()):
            for hexa in _HEX.findall(fonte):
                cores[f"#{hexa.upper()}"] = tuple(
                    int(hexa[i:i + 2], 16) for i in (0, 2, 4))
            for r, g, b, a in _RGBA.findall(fonte):
                cores[f"rgba({r},{g},{b},{a})"] = _sobre(
                    (int(r), int(g), int(b)), float(a), fundo)
    return cores


def _paineis_variados(**opcoes):
    """Um painel de cada caminho de pintura: e' onde cada tinta aparece."""
    cap = _Stream()
    cap.metrics.bottleneck = fr.BOTTLENECK_CAP
    return [
        _montar(_snapshot(), _Stream(), **opcoes),
        # Barra pela metade: so' assim o trilho vazio e o meio-tom sao desenhados.
        _montar(_snapshot(ram_used=12.0), _Stream(), **opcoes),
        _montar(_snapshot(), None, **opcoes),
        _montar(_snapshot(), cap, **opcoes),
    ]


def test_toda_tinta_do_painel_se_le_sobre_uma_cena_clara():
    """Sobre fundo claro o painel compunha um cinza medio e engolia meio painel.

    O cinza mais escuro da paleta caia para 1.02:1: nao "dificil de ler",
    invisivel. Levava junto a tag do gargalo, o trilho das barras de memoria e a
    barra que separa as duas temperaturas.
    """
    for painel in _paineis_variados():
        fundo = _fundo_do_painel(painel)
        for nome, cor in _tintas(painel, fundo).items():
            assert _contraste(cor, fundo) >= _MINIMO_CONTRASTE, (
                f"{nome}: {_contraste(cor, fundo):.2f}:1")


def test_a_opacidade_escolhida_e_a_opacidade_pintada():
    """Sem um extremo opaco o controle de opacidade e' decoracao.

    O mapa antigo parava em 165/255: quem nao conseguia ler arrastava o controle
    ate' o fim e continuava sem ler, porque o jogo seguia atravessando o fundo.
    Nao havia posicao boa, e a conclusao natural e' que o app esta' quebrado.
    """
    for escolhida in (0.30, 0.50, 0.88, 1.0):
        assert ov._alpha_do_fundo(escolhida) == round(escolhida * 255), escolhida
    assert ov._alpha_do_fundo(1.0) == 255


_SPAN = re.compile(r"<span style='color:([^']+)'>([^<]*)</span>")


def _hex(cor: str):
    h = cor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _cor_do_trecho(rico: str, trecho: str):
    for cor, texto in _SPAN.findall(rico):
        if trecho in texto:
            return cor
    return None


def test_o_que_carrega_leitura_nao_fica_no_cinza_mais_apagado():
    """Tres pedacos do painel viviam no cinza mais escuro da paleta.

    Nenhum dos tres e' enfeite: a tag GARGALO rotula a linha mais assertiva do
    painel; o trilho vazio e' a proporcao que a barra existe para mostrar (sem
    ele sobra um bloco solto, sem escala); e a barra entre as duas temperaturas e'
    o que separa "69/82°C" de "69 82°C", que ja' e' outro numero.
    """
    painel = _montar(_snapshot(ram_used=12.0), _Stream())
    fundo = _fundo_do_painel(painel)
    alvos = {
        "tag do gargalo": _HEX.search(painel._limite_tag.styleSheet()).group(0),
        "trilho da barra": _cor_do_trecho(_texto(painel, "ram", ov.CARGA), "░"),
        "barra entre as temperaturas": _cor_do_trecho(_texto(painel, "cpu", ov.TEMP), "/"),
    }
    for nome, cor in alvos.items():
        assert cor, nome
        # 4.5:1 e' o piso de texto corrido: acima do cinza mais apagado da paleta,
        # que sobre cena clara para nesta mesma conta em 3.3:1.
        assert _contraste(_hex(cor), fundo) >= 4.5, f"{nome}: {cor}"


# ── furo de sensor nao pode piscar ───────────────────────────────────────────
def test_media_de_temperatura_sobrevive_a_um_ciclo_sem_leitura():
    """O sensor de nucleo falha em ciclo solto.

    Sem carencia, a celula piscava entre "61/78" e "78" varias vezes por minuto;
    o que se le' como o app perdendo dado, nao como a temperatura mudando.
    """
    import vantage.ui.overlay as ov

    painel = _montar(_snapshot(), _Stream())
    painel._temps("cpu", 61.0, 78.0, lambda _v: "#fff")
    com_par = _texto(painel, "cpu", ov.TEMP)

    painel._temps("cpu", None, 78.0, lambda _v: "#fff")
    assert _texto(painel, "cpu", ov.TEMP) == com_par, "piscou no furo de sensor"


def test_media_some_quando_o_sensor_nao_volta():
    """Segurar para sempre seria mostrar um numero velho como se fosse de agora."""
    import time

    import vantage.ui.overlay as ov

    painel = _montar(_snapshot(), _Stream())
    painel._temps("cpu", 61.0, 78.0, lambda _v: "#fff")
    painel._media_recente["cpu"] = (61.0, time.monotonic() - ov._SEGURA_MEDIA_S - 1)
    painel._temps("cpu", None, 78.0, lambda _v: "#fff")
    assert "61" not in _texto(painel, "cpu", ov.TEMP)


def test_fatia_do_jogo_fica_colada_na_barra():
    """Na ponta direita ela ficava solta, parecendo outro assunto.

    A memoria do jogo e' um PEDACO do numero que a barra desenha, e leitura que
    se compara precisa ficar ao lado do que se compara com ela.
    """
    import vantage.ui.overlay as ov

    d = _snapshot()
    painel = _montar(d, _Stream())
    carga = _texto(painel, "ram", ov.CARGA)
    assert "jogo" in carga, carga
    assert "jogo" not in _texto(painel, "ram", ov.CAUDA)


def test_linha_de_memoria_nao_estica_as_colunas_das_pecas():
    """Celula propria para cada numero da memoria abria um vao entre o clock e a
    tensao da CPU e da GPU: o alinhamento certo de uma linha estragava o das
    outras."""
    import vantage.ui.overlay as ov

    painel = _montar(_snapshot(), _Stream())
    assert ("ram", ov.CLOCK) not in painel._cels
    assert ("vram", ov.VOLT) not in painel._cels
