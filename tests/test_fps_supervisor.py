"""O supervisor precisa poder ser ressuscitado.

O caso real: o PresentMon subiu, nao conectou no pipe, e o supervisor congelou no
desmonte da sessao. O watchdog escreveu "reiniciando" 111 vezes em meia hora sem
nada acontecer, porque tudo o que ele sabia fazer era matar um processo que ja'
estava morto. Sem captura de FPS o overlay tambem some, ja' que ele so' aparece
quando ha' um jogo entregando quadros.
"""
import time

from vantage.sensors import fps as fpsmod
from vantage.sensors.fps import FpsEngine


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


def test_geracao_aposenta_a_thread_antiga(monkeypatch):
    """A travada que acordar depois tem de sair, e nao subir um segundo PresentMon."""
    eng = FpsEngine()
    monkeypatch.setattr(eng, "_supervise", lambda geracao: None)
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


def test_sessao_legada_conta_como_orfa():
    """A sessao de nome fixo que sobrou foi o que travou a captura por meia hora."""
    assert fpsmod._orfa(fpsmod.SESSION_PREFIX)
    assert fpsmod._orfa(fpsmod.SESSION_PREFIX + "_999999")
    assert not fpsmod._orfa(fpsmod.SESSION)
    assert not fpsmod._orfa("OutroApp")
    assert not fpsmod._orfa("")


def test_sessao_bloqueada_varre_em_vez_de_degradar_metricas(monkeypatch):
    """"access denied" nao diz nada sobre --v2_metrics."""
    eng = FpsEngine()
    monkeypatch.setattr(fpsmod, "encerrar_presentmon_orfaos", lambda: 0)
    varridas: list[int] = []
    fpsmod_sweep = fpsmod.sweep_stale_sessions
    fpsmod.sweep_stale_sessions = lambda: varridas.append(1)
    try:
        eng._note_failure("error: failed to start trace session: access denied.")
    finally:
        fpsmod.sweep_stale_sessions = fpsmod_sweep
    assert varridas == [1]
    assert eng._use_v1 is False


def test_so_cai_para_v1_quando_a_opcao_e_recusada():
    eng = FpsEngine()
    eng._note_failure("error: unrecognized option '--v2_metrics'.")
    assert eng._use_v1 is True


def test_falha_generica_nao_muda_o_modo():
    eng = FpsEngine()
    eng._note_failure("(nada)")
    eng._note_failure("(nada)")
    assert eng._use_v1 is False


# ── silencio nao e' falha ────────────────────────────────────────────────────
class _ProcFalso:
    """PresentMon que fica vivo e calado, como no desktop sem jogo."""

    def __init__(self, morre_apos=None):
        self.chamadas = 0
        self._morre_apos = morre_apos

    def poll(self):
        self.chamadas += 1
        if self._morre_apos is not None and self.chamadas >= self._morre_apos:
            return 1
        return None


def test_processo_vivo_e_calado_nao_conta_como_falha():
    """O PresentMon so' abre a saida quando tem o primeiro quadro a escrever.

    A lista de exclusoes do app tira tudo o que apresenta quadros no desktop:
    navegador, terminal, o proprio app. Sem jogo aberto, ficar calado e' o
    comportamento certo dele. O prazo de 12 s transformava esse silencio em
    "falhou", matando e ressuscitando o processo a cada quinze segundos.
    """
    import threading

    stop, force = threading.Event(), threading.Event()
    proc = _ProcFalso()
    vidas = []

    def parar_depois():
        vidas.append(1)
        if len(vidas) >= 3:
            stop.set()

    ok = fpsmod._esperar_conexao(threading.Event(), proc, stop, force, parar_depois)
    assert ok is False              # nao conectou, mas...
    assert len(vidas) >= 3          # ...ficou esperando, dando sinal de vida


def test_processo_que_morre_de_verdade_e_falha():
    import threading

    stop, force = threading.Event(), threading.Event()
    ok = fpsmod._esperar_conexao(threading.Event(), _ProcFalso(morre_apos=2),
                                 stop, force, lambda: None)
    assert ok is False


def test_pedido_de_reinicio_interrompe_a_espera():
    """Sem isso, reiniciar a captura na mao ficaria preso na espera."""
    import threading

    stop, force = threading.Event(), threading.Event()
    force.set()
    assert fpsmod._esperar_conexao(threading.Event(), _ProcFalso(),
                                   stop, force, lambda: None) is False


def test_espera_alimenta_o_watchdog():
    """O watchdog mataria uma captura saudavel que so' esta' esperando jogo."""
    eng = FpsEngine()
    eng._alive_at = 0.0
    eng._aguardando_jogo()
    assert eng._alive_at > 0
    assert "aguardando" in eng.status
