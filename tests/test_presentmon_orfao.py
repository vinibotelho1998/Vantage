"""Encerrar PresentMon largado: o degrau que impedia a captura de voltar.

Quando o app morre a forca, o PresentMon filho sobrevive segurando um logger de
sistema. Esse logger, uma vez orfao, NAO pode ser removido por ninguem, nem
administrador, nem SYSTEM, nem pela API direta; so' o reinicio do Windows. Por
isso o unico caminho e' pedir ao processo que saia enquanto ele ainda esta' vivo.
"""
import os
import signal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.sensors import fps  # noqa: E402


class _Proc:
    def __init__(self, pid, nome, ppid=1, sessao=None):
        self.info = {"pid": pid, "name": nome, "ppid": ppid,
                     "cmdline": [nome, "--session_name", sessao or f"Vantage_{ppid}"]}
        self.terminado = False

    def terminate(self):
        self.terminado = True

    def wait(self, timeout=None):
        return 0


def _psutil_falso(monkeypatch, processos, vivos=()):
    import types

    falso = types.SimpleNamespace()
    falso.process_iter = lambda campos=None: iter(processos)
    falso.Process = lambda pid: next(p for p in processos if p.info["pid"] == pid)
    falso.Error = Exception
    falso.pid_exists = lambda pid: pid in vivos
    monkeypatch.setitem(__import__("sys").modules, "psutil", falso)
    return falso


def test_pede_para_sair_em_vez_de_matar(monkeypatch):
    """Matar a forca deixaria o logger de sistema orfao para sempre."""
    proc = _Proc(4242, "presentmon.exe")
    _psutil_falso(monkeypatch, [proc])
    sinais = []
    monkeypatch.setattr(fps.os, "kill", lambda pid, sig: sinais.append((pid, sig)))

    n = fps.encerrar_presentmon_orfaos()

    assert n == 1
    assert sinais == [(4242, signal.CTRL_BREAK_EVENT)]
    assert not proc.terminado          # nada de hard kill quando o sinal passa


def test_filho_da_propria_instancia_nao_e_orfao(monkeypatch):
    """Quem cuida do filho e' o supervisor; encerra-lo aqui derrubaria a
    captura que acabou de subir."""
    meu = _Proc(999, "presentmon.exe", ppid=os.getpid())
    _psutil_falso(monkeypatch, [meu])
    monkeypatch.setattr(fps.os, "kill", lambda pid, sig: None)

    assert fps.encerrar_presentmon_orfaos() == 0


def test_outros_processos_sao_ignorados(monkeypatch):
    _psutil_falso(monkeypatch, [_Proc(1, "chrome.exe"), _Proc(2, "dwm.exe")])
    monkeypatch.setattr(fps.os, "kill", lambda pid, sig: None)

    assert fps.encerrar_presentmon_orfaos() == 0


def test_presentmon_de_outra_ferramenta_nao_e_encerrado(monkeypatch):
    proc = _Proc(4242, "presentmon.exe", sessao="CapFrameX")
    _psutil_falso(monkeypatch, [proc])
    sinais = []
    monkeypatch.setattr(fps.os, "kill", lambda *args: sinais.append(args))
    assert fps.encerrar_presentmon_orfaos() == 0
    assert sinais == [] and not proc.terminado


def test_pai_vivo_e_preservado_mesmo_com_sessao_legada(monkeypatch):
    proc = _Proc(4242, "presentmon.exe", ppid=123, sessao="Vantage")
    _psutil_falso(monkeypatch, [proc], vivos=(123,))
    sinais = []
    monkeypatch.setattr(fps.os, "kill", lambda *args: sinais.append(args))
    assert fps.encerrar_presentmon_orfaos() == 0
    assert sinais == []


def test_sessao_de_instancia_viva_nao_e_orfa(monkeypatch):
    _psutil_falso(monkeypatch, [], vivos=(123,))
    assert not fps._orfa("Vantage_123")
    assert fps._orfa("Vantage_456")
    assert not fps._orfa("Vantage_outro_programa")


def test_sinal_que_nao_chega_cai_para_terminate(monkeypatch):
    """Sem grupo de console em comum o CTRL+BREAK falha; ainda assim e' melhor
    liberar o processo do que deixar tudo travado."""
    proc = _Proc(4242, "presentmon.exe")
    _psutil_falso(monkeypatch, [proc])

    def explode(pid, sig):
        raise OSError("sem grupo de console")

    monkeypatch.setattr(fps.os, "kill", explode)

    assert fps.encerrar_presentmon_orfaos() == 1
    assert proc.terminado


def test_sem_psutil_nao_quebra(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr("builtins.__import__",
                        lambda n, *a, **k: (_ for _ in ()).throw(ImportError())
                        if n == "psutil" else __import__(n, *a, **k))
    assert fps.encerrar_presentmon_orfaos() == 0
