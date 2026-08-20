"""O arranjo do overlay: o que some, o que fica em branco e o que nunca se move.

O overlay e' desenhado por cima do jogo e ninguem vai conferi-lo com calma no
meio de uma partida. Os riscos cobertos aqui sao os que passam despercebidos e
estragam a leitura: sensor que falta virar travessao (que se le' como "quebrou"),
peca ausente deixando uma linha oca, coluna reservada mudando de largura quando
um valor encolhe, e a cauda do jogo congelando no ultimo numero depois que o
processo morreu.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from dbxstats.config import OVERLAY_METRICS, Settings  # noqa: E402
from dbxstats.core import frames as fr  # noqa: E402
from dbxstats.ui import overlay as ov  # noqa: E402

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
    """Sem tensao em lugar nenhum, a coluna inteira sai — nao vira fileira de traco.

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


def test_nenhuma_celula_de_peca_mostra_travessao():
    """Numa maquina sem sensor nenhum, o painel fica vazio — nunca furado."""
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
              "jogo_ram_ws", "mem_clock", "teto_watts", "ping", "clock"}
    assert usadas <= conhecidas


def test_desligar_tudo_menos_o_fps_nao_quebra_o_painel():
    """Lista curta e' estado legitimo, e ja' quebrou layout antes."""
    painel = _montar(_snapshot(), _Stream(), overlay_metrics=["fps"])
    assert painel._fps.text() == "98"
    assert [w for w in painel.findChildren(QLabel) if w.text()]
