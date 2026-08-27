"""Big Picture: escolher e abrir um jogo do sofa, so' com o controle."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbxstats.config import Settings  # noqa: E402
from dbxstats.platform.gamepad import (  # noqa: E402
    BTN_A,
    BTN_B,
    BTN_BACK,
    BTN_DPAD_RIGHT,
    BTN_START,
    XINPUT_GAMEPAD,
    nav_direction,
)
from dbxstats.ui.bigpicture import (  # noqa: E402
    BigPicture,
    tempo_medido,
    ultima_sessao,
)

_app = QApplication.instance() or QApplication([])


class _Ctl:
    def __init__(self, jogos=4, historico=None):
        self.settings = Settings()
        self.settings.launch_items = [
            {"name": f"Jogo {i}", "path": f"C:/j{i}.exe", "target": ""}
            for i in range(jogos)
        ]
        self.session_history = historico or []


def _bp(jogos=4, historico=None) -> BigPicture:
    bp = BigPicture(_Ctl(jogos, historico))
    bp._itens = list(bp._ctl.settings.launch_items)
    bp.resize(1920, 1080)
    return bp


def _pad(**campos) -> XINPUT_GAMEPAD:
    p = XINPUT_GAMEPAD()
    for k, v in campos.items():
        setattr(p, k, v)
    return p


# ── direcao ──────────────────────────────────────────────────────────────────
def test_direcional_manda_mais_que_o_analogico():
    """Segurar o analogico torto enquanto se usa o direcional e' comum."""
    assert nav_direction(_pad(wButtons=BTN_DPAD_RIGHT, sThumbLY=30000)) == "right"


def test_diagonal_resolve_pelo_eixo_maior():
    """Sem isso, um empurrao torto andaria duas casas de uma vez."""
    assert nav_direction(_pad(sThumbLX=20000, sThumbLY=30000)) == "up"
    assert nav_direction(_pad(sThumbLX=30000, sThumbLY=20000)) == "right"


def test_analogico_encostado_nao_anda():
    """A zona morta aqui e' bem maior que a do cursor, de proposito."""
    assert nav_direction(_pad(sThumbLX=9000)) == ""


# ── foco ─────────────────────────────────────────────────────────────────────
def test_foco_anda_com_o_direcional():
    bp = _bp()
    bp.tratar_pad(_pad(wButtons=BTN_DPAD_RIGHT))
    assert bp._foco == 1


def test_segurar_nao_dispara_todo_tique():
    """Sem espera de repeticao, um toque atravessaria a lista inteira."""
    bp = _bp(jogos=8)
    for _ in range(6):
        bp.tratar_pad(_pad(wButtons=BTN_DPAD_RIGHT))
    assert bp._foco == 1


def test_foco_nao_da_a_volta_na_borda():
    """A tres metros nao da' para acompanhar o pulo do fim para o comeco."""
    bp = _bp(jogos=3)
    for _ in range(6):
        bp._mover("left")
    assert bp._foco == 0
    for _ in range(20):
        bp._mover("right")
    assert bp._foco == 2


def test_sem_jogos_nao_quebra():
    bp = _bp(jogos=0)
    bp._mover("right")
    bp.tratar_pad(_pad(wButtons=BTN_A))
    bp.repaint()


# ── acoes ────────────────────────────────────────────────────────────────────
def test_a_escolhe_o_jogo_em_foco():
    bp = _bp()
    escolhidos = []
    bp.escolheu.connect(escolhidos.append)
    bp._mover("right")
    bp.tratar_pad(_pad(wButtons=BTN_A))
    assert escolhidos and escolhidos[0]["name"] == "Jogo 1"


def test_segurar_a_nao_abre_duas_vezes():
    """Um toque um pouco longo abriria o jogo duas vezes."""
    bp = _bp()
    escolhidos = []
    bp.escolheu.connect(escolhidos.append)
    for _ in range(5):
        bp.tratar_pad(_pad(wButtons=BTN_A))
    assert len(escolhidos) == 1


def test_start_tambem_abre():
    bp = _bp()
    escolhidos = []
    bp.escolheu.connect(escolhidos.append)
    bp.tratar_pad(_pad(wButtons=BTN_START))
    assert escolhidos


def test_b_fecha():
    bp = _bp()
    fechou = []
    bp.fechou.connect(lambda: fechou.append(1))
    bp.tratar_pad(_pad(wButtons=BTN_B))
    assert fechou


def test_back_sozinho_nao_faz_nada_aqui():
    """Back e' o gesto de ABRIR a grade; dentro dela ele nao pode agir."""
    bp = _bp()
    escolhidos, fechou = [], []
    bp.escolheu.connect(escolhidos.append)
    bp.fechou.connect(lambda: fechou.append(1))
    bp.tratar_pad(_pad(wButtons=BTN_BACK))
    assert not escolhidos and not fechou


# ── fatos da partida ─────────────────────────────────────────────────────────
_HIST = [{"game": "Jogo 1", "fps_avg": 120.0, "duracao_s": 600},
         {"game": "Jogo 1", "fps_avg": 144.0, "duracao_s": 1800},
         {"game": "Outro", "fps_avg": 60.0, "duracao_s": 300}]


def test_ultima_sessao_e_a_mais_recente_daquele_jogo():
    assert ultima_sessao(_HIST, "Jogo 1")["fps_avg"] == 144.0


def test_sem_sessao_devolve_nada_e_nao_zero():
    """Zero se le' como "rodou a zero fps", que e' pior que nao mostrar."""
    assert ultima_sessao(_HIST, "Nunca jogado") is None
    assert ultima_sessao([], "Jogo 1") is None


def test_tempo_medido_soma_so_o_jogo_certo():
    assert tempo_medido(_HIST, "Jogo 1") == 2400
    assert tempo_medido(_HIST, "Outro") == 300


def test_arquivo_sumido_aparece_no_card():
    bp = _bp()
    assert "não encontrado" in bp._rodape_do_card({"name": "X", "path": "C:/nao/existe.exe"})


# ── desenho ──────────────────────────────────────────────────────────────────
def test_desenha_em_1080p_e_em_4k():
    for largura, altura in ((1920, 1080), (3840, 2160)):
        bp = _bp(jogos=6, historico=_HIST)
        bp.resize(largura, altura)
        bp._escala = 1.0 if largura == 1920 else 2.0
        bp.repaint()


def test_cabem_no_maximo_quatro_colunas():
    """Mais que isso vira card pequeno demais para tres metros."""
    bp = _bp(jogos=12)
    assert bp._colunas() <= 4


# ── gesto de abrir ───────────────────────────────────────────────────────────
def _app_para_gesto(botoes=0):
    import dbxstats.app as appmod

    a = appmod.App.__new__(appmod.App)
    a._bigpicture = None
    a._bp_back_desde = 0.0
    a._bp_back_pronto = False
    a.abriu = []
    a.big_picture_abrir = lambda: a.abriu.append(1)
    pad = XINPUT_GAMEPAD()
    pad.wButtons = botoes
    a.gamepad = type("G", (), {"last": pad})()
    return a


def test_back_ja_apertado_na_abertura_nao_abre_sozinho():
    """O app subiu no Big Picture porque o controle ja' reportava Back.

    Sem exigir a borda, um botao preso (ou apertado no instante em que o app
    sobe) abre a grade sozinho um segundo depois.
    """
    import time

    a = _app_para_gesto(BTN_BACK)
    for _ in range(3):
        a._vigiar_atalho_do_sofa()
    a._bp_back_desde = time.monotonic() - 5
    a._vigiar_atalho_do_sofa()
    assert a.abriu == []


def test_segurar_depois_de_soltar_abre():
    import time

    a = _app_para_gesto(0)
    a._vigiar_atalho_do_sofa()          # viu solto: arma
    a.gamepad.last.wButtons = BTN_BACK
    a._vigiar_atalho_do_sofa()          # comecou a segurar
    a._bp_back_desde = time.monotonic() - 2
    a._vigiar_atalho_do_sofa()
    assert a.abriu == [1]


def test_combo_do_mouse_nao_abre_a_grade():
    """Back+Start assume o mouse; nao pode virar Big Picture tambem."""
    import time

    a = _app_para_gesto(0)
    a._vigiar_atalho_do_sofa()
    a.gamepad.last.wButtons = BTN_BACK | BTN_START
    a._vigiar_atalho_do_sofa()
    a._bp_back_desde = time.monotonic() - 2
    a._vigiar_atalho_do_sofa()
    assert a.abriu == []
