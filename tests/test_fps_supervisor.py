"""O supervisor precisa poder ser ressuscitado.

O caso real: o PresentMon subiu, nao conectou no pipe, e o supervisor congelou no
desmonte da sessao. O watchdog escreveu "reiniciando" 111 vezes em meia hora sem
nada acontecer, porque tudo o que ele sabia fazer era matar um processo que ja'
estava morto. Sem captura de FPS o overlay tambem some, ja' que ele so' aparece
quando ha' um jogo entregando quadros.
"""
import time

from dbxstats.sensors import fps as fpsmod
from dbxstats.sensors.fps import FpsEngine


def _motor_rodando() -> tuple[FpsEngine, list[int]]:
    """Motor que se diz iniciado, com o nascimento de supervisor sob vigia."""
    eng = FpsEngine()
    eng._threads.append(object())      # finge que start() ja' rodou
    chamadas: list[int] = []
    eng._spawn_supervisor = lambda: chamadas.append(1)   # type: ignore[method-assign]
    return eng, chamadas


def test_supervisor_parado_demais_e_substituido():
    eng, chamadas = _motor_rodando()
    eng._alive_at = time.monotonic() - (fpsmod.STUCK_S + 5)
    eng._loop_at = time.monotonic() - (fpsmod.REVIVE_S + 5)
    eng._rescue_if_stuck()
    assert chamadas == [1]


def test_supervisor_que_ainda_da_voltas_e_deixado_em_paz():
    """Matar o processo basta quando o ciclo continua andando."""
    eng, chamadas = _motor_rodando()
    eng._alive_at = time.monotonic() - (fpsmod.STUCK_S + 5)
    eng._loop_at = time.monotonic()
    eng._rescue_if_stuck()
    assert eng._force_restart.is_set()   # resgate normal aconteceu
    assert chamadas == []                # mas sem trocar a thread


def test_motor_nunca_iniciado_nao_ganha_supervisor():
    """Um motor recem-criado nao pode parecer travado ha' uma eternidade."""
    eng = FpsEngine()
    chamadas: list[int] = []
    eng._spawn_supervisor = lambda: chamadas.append(1)   # type: ignore[method-assign]
    eng._alive_at = time.monotonic() - (fpsmod.STUCK_S + 5)
    eng._rescue_if_stuck()
    assert chamadas == []


def test_geracao_aposenta_a_thread_antiga():
    """A travada que acordar depois tem de sair, e nao subir um segundo PresentMon."""
    eng = FpsEngine()
    eng._spawn_supervisor()
    primeira = eng._gen
    eng._stop.set()          # a nova thread sai sozinha; so' a geracao importa aqui
    eng._spawn_supervisor()
    assert eng._gen > primeira


def test_sessao_etw_leva_o_pid_no_nome():
    """Duas copias do app com o mesmo nome de sessao se derrubavam sem parar."""
    import os
    assert fpsmod.SESSION.startswith(fpsmod.SESSION_PREFIX + "_")
    assert fpsmod.SESSION.endswith(str(os.getpid()))


def test_comando_auxiliar_respeita_o_prazo():
    """subprocess.run(timeout=) podia travar no proprio wait depois de matar."""
    inicio = time.monotonic()
    fpsmod._run_bounded(["ping", "-n", "30", "127.0.0.1"], 1.0, "ping de teste")
    assert time.monotonic() - inicio < 4.0
