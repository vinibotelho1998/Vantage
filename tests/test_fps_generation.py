"""Supervisor e recursos simulados; nenhum processo ETW/PresentMon real."""
from vantage.sensors import fps as F


def test_supervisor_aposentado_nao_limpa_nem_publica_sobre_o_novo(monkeypatch):
    motor = F.FpsEngine()
    motor._gen = 1
    antigo, novo = object(), object()
    limpezas, terminados = [], []
    monkeypatch.setattr(motor, "_cleanup_session", lambda nome:limpezas.append(nome))
    monkeypatch.setattr(F, "_create_pipe", lambda nome:123)
    monkeypatch.setattr(F, "_close_handle", lambda handle:None)
    monkeypatch.setattr(F.subprocess, "Popen", lambda *a, **k:antigo)
    monkeypatch.setattr(F, "_wait_connect", lambda *a, **k:True)
    monkeypatch.setattr(F, "_terminate", lambda p:terminados.append(p))
    def ler(handle, processo, geracao):
        motor._gen = 2
        motor._proc = novo
    monkeypatch.setattr(motor, "_read_pipe", ler)
    motor._run_session("fake", 1)
    assert motor._proc is novo
    assert limpezas == [motor._session_name(1)] * 2
    assert terminados == [antigo]


def test_geracao_muda_durante_limpeza_nao_inicia_presentmon(monkeypatch):
    motor = F.FpsEngine()
    motor._gen = 1
    def limpar(nome): motor._gen = 2
    monkeypatch.setattr(motor, "_cleanup_session", limpar)
    monkeypatch.setattr(F, "_create_pipe", lambda nome: (_ for _ in ()).throw(AssertionError("pipe velho")))
    motor._run_session("fake", 1)


def test_motor_parado_nao_varre_recursos_globais(monkeypatch):
    motor = F.FpsEngine()
    motor._stop.set()
    monkeypatch.setattr(motor, "_ensure_presentmon", lambda: (_ for _ in ()).throw(AssertionError("download")))
    monkeypatch.setattr(F, "encerrar_presentmon_orfaos", lambda: (_ for _ in ()).throw(AssertionError("cleanup")))
    motor._supervise()


def test_createprocess_atrasado_nao_para_a_sessao_nova(monkeypatch):
    motor = F.FpsEngine()
    motor._gen = 1
    comandos, limpezas, terminados = [], [], []
    antigo, novo = object(), object()
    monkeypatch.setattr(motor, "_cleanup_session", lambda nome: limpezas.append(nome))
    monkeypatch.setattr(F, "_create_pipe", lambda nome: 123)
    monkeypatch.setattr(F, "_close_handle", lambda handle: None)
    monkeypatch.setattr(F, "_terminate", lambda proc: terminados.append(proc))
    def criar(comando, **kwargs):
        comandos.append(comando)
        # O SO volta do CreateProcess quando outro supervisor ja tomou lugar.
        motor._gen = 2
        motor._proc = novo
        return antigo
    monkeypatch.setattr(F.subprocess, "Popen", criar)
    motor._run_session("fake", 1)
    nome = F._nome_da_sessao(comandos[0])
    assert nome == motor._session_name(1) != motor._session_name(2)
    assert limpezas == [nome, nome]
    assert terminados == [antigo]
    assert motor._proc is novo


def test_orfa_por_geracao_preserva_dono_vivo(monkeypatch):
    monkeypatch.setattr(F, "_pid_vivo", lambda pid: int(pid) == 123)
    assert not F._orfa("Vantage_123_4")
    assert F._orfa("Vantage_456_4")
    assert F._orfa("Vantage_456")
    assert not F._orfa("Vantage_456_x")
    assert not F._orfa("Vantage_456_1_extra")


def test_stop_limpa_apenas_a_sessao_que_estava_rodando(monkeypatch):
    motor = F.FpsEngine()
    motor._gen = 3
    limpezas = []
    monkeypatch.setattr(motor, "_kill_process", lambda: None)
    monkeypatch.setattr(motor, "_cleanup_session", lambda nome: limpezas.append(nome))
    motor.stop()
    assert motor._gen == 4
    assert limpezas == [motor._session_name(3)]
