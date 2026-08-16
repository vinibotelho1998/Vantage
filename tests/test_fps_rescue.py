"""Destravamento da captura: parar de dar sinal de vida precisa virar reinicio."""
import time

from dbxstats.sensors import fps as fpsmod
from dbxstats.sensors.fps import FpsEngine


class _PipeFalso:
    def __init__(self) -> None:
        self.fechado = False

    def close(self) -> None:
        self.fechado = True


def test_primeira_passada_so_marca_o_relogio():
    eng = FpsEngine()
    eng._rescue_if_stuck()
    assert eng._alive_at > 0
    assert not eng._force_restart.is_set()


def test_captura_viva_fica_em_paz():
    eng = FpsEngine()
    eng._alive_at = time.monotonic()
    eng._reader = _PipeFalso()
    eng._rescue_if_stuck()
    assert not eng._force_restart.is_set()
    assert eng._reader.fechado is False


def test_frame_recente_conta_como_sinal_de_vida():
    eng = FpsEngine()
    eng._alive_at = time.monotonic() - 999
    eng._last_frame_at = time.monotonic()
    eng._reader = _PipeFalso()
    eng._rescue_if_stuck()
    assert not eng._force_restart.is_set()


def test_captura_travada_fecha_o_pipe_e_pede_reinicio():
    """`read` no pipe nao volta quando o PresentMon some sem fechar a ponta dele."""
    eng = FpsEngine()
    pipe = _PipeFalso()
    eng._reader = pipe
    eng._alive_at = time.monotonic() - (fpsmod.STUCK_S + 5)
    eng._rescue_if_stuck()
    assert pipe.fechado is True
    assert eng._force_restart.is_set()
    assert eng._reader is None
    assert "destravando" in eng.status


def test_nao_mexe_em_motor_ja_parado():
    eng = FpsEngine()
    eng._alive_at = time.monotonic() - 999
    eng._reader = _PipeFalso()
    eng._stop.set()
    eng._rescue_if_stuck()
    assert eng._reader.fechado is False
    assert not eng._force_restart.is_set()


def test_relogio_reinicia_depois_do_resgate():
    """Sem isso ele tentaria destravar de novo no proximo tick, em loop."""
    eng = FpsEngine()
    eng._reader = _PipeFalso()
    eng._alive_at = time.monotonic() - (fpsmod.STUCK_S + 5)
    eng._rescue_if_stuck()
    antes = eng._alive_at
    eng._force_restart.clear()
    eng._rescue_if_stuck()
    assert eng._alive_at == antes
    assert not eng._force_restart.is_set()
