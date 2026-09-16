"""Partida local nao tem ping que interesse.

Mostrar a latencia ate' um DNS publico durante um jogo offline ocupa espaco com
um numero que nao diz nada sobre o que esta' na tela.
"""
import time

from vantage.app import ONLINE_GRACE_S, App


def _app(pid=0, seguindo=False, medindo=False, visto_ha=0.0):
    a = App.__new__(App)
    a._game_pid = pid
    a._game_seen_at = time.monotonic() - visto_ha
    a.ping = type("P", (), {"following_game": seguindo, "measuring_game": medindo})()
    return a


def test_sem_jogo_nao_opina():
    assert _app(pid=0).jogo_online() is None


def test_servidor_encontrado_e_online():
    assert _app(pid=42, seguindo=True).jogo_online() is True


def test_latencia_medida_no_trafego_tambem_conta():
    """Ha' jogo em que nao descobrimos o servidor, mas medimos o trafego dele."""
    assert _app(pid=42, medindo=True).jogo_online() is True


def test_nao_chama_de_local_cedo_demais():
    """A busca leva alguns segundos; dizer "local" antes disso e' chute."""
    assert _app(pid=42, visto_ha=2.0).jogo_online() is None


def test_depois_de_procurar_bastante_e_local():
    assert _app(pid=42, visto_ha=ONLINE_GRACE_S + 5).jogo_online() is False


def test_rodape_nao_repete_o_nome_do_jogo():
    """O rotulo do ping costuma SER o nome do processo do jogo.

    A latencia sai do trafego dele, entao o rotulo vem com o nome do executavel;
    e concatenar os dois escrevia "cs2.exe · cs2.exe" a partida inteira.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vantage.config import Settings
    from vantage.core import frames as fr
    from vantage.core.series import History
    from vantage.ui.overlay import GameOverlay

    QApplication.instance() or QApplication([])
    m = fr.FrameMetrics()
    m.fps_now = 144.0
    m.frames = 5000

    class _Ping:
        target_label = "cs2.exe"
        following_game = True

    class _Stream:
        app = "cs2.exe"
        pid = 7
        metrics = m

    class _Ctl:
        def __init__(self):
            self.settings = Settings()
            self.ping = _Ping()
            self.history = History(50)

        def last_data(self):
            return {"ping_ms": 15, "gpu": {}}

        def active_stream(self):
            return _Stream()

    o = GameOverlay(_Ctl())
    o.refresh()
    assert o._origem.text().count("cs2.exe") == 1, o._origem.text()
