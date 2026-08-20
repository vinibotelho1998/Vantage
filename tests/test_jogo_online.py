"""Partida local nao tem ping que interesse.

Mostrar a latencia ate' um DNS publico durante um jogo offline ocupa espaco com
um numero que nao diz nada sobre o que esta' na tela.
"""
import time

from dbxstats.app import ONLINE_GRACE_S, App


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
