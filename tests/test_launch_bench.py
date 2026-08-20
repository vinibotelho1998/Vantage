"""Gravar a partida e' escolha de cada atalho.

Alguem que so' quer abrir o jogo na TV nao precisa de relatorio no fim, e o
gravador nao deve nem comecar nesse caso.
"""
import dbxstats.app as appmod
from dbxstats.app import App
from dbxstats.config import Settings, _clean_launch_item


class _Fps:
    def __init__(self):
        self.iniciados = []
        self.seguidos = []
        self.parou = 0

    def session_start(self, pid):
        self.iniciados.append(pid)

    def session_follow(self, pid):
        self.seguidos.append(pid)

    def session_stop(self):
        self.parou += 1
        return {"frames": 999999, "fps_avg": 140.0, "low_1": 90.0, "duracao_s": 600}


def _app(monkeypatch):
    a = App.__new__(App)
    a.fps = _Fps()
    a._session_bench = False
    a._session_bench_pid = 0
    a._session_name = "jogo"
    a._session_priority = ""
    a.session_history = []
    a.stats = type("S", (), {"get": lambda self, k: None})()
    a.notify = lambda *args: None
    a.show_view = lambda *args: None
    monkeypatch.setattr(appmod, "_save_session_history", lambda h: None)
    return a


def test_atalho_sem_gravacao_nao_liga_o_gravador(monkeypatch):
    a = _app(monkeypatch)
    a._session_bench = bool({"bench": False}.get("bench", True))
    assert a._session_bench is False
    a._close_session_bench()
    assert a.fps.parou == 0, "parou uma gravacao que nunca comecou"
    assert a.session_history == []


def test_atalho_com_gravacao_guarda_o_resumo(monkeypatch):
    a = _app(monkeypatch)
    a._session_bench = True
    a._close_session_bench()
    assert a.fps.parou == 1
    assert len(a.session_history) == 1
    assert a.session_history[0]["game"] == "jogo"


def test_fechar_duas_vezes_nao_duplica_o_registro(monkeypatch):
    """_tick_session pode chamar de novo antes de a sessao ser zerada."""
    a = _app(monkeypatch)
    a._session_bench = True
    a._close_session_bench()
    a._close_session_bench()
    assert len(a.session_history) == 1


def test_a_chave_sobrevive_ao_disco():
    item = _clean_launch_item({"path": "C:/jogo.exe", "bench": False})
    assert item["bench"] is False
    assert _clean_launch_item({"path": "C:/jogo.exe"})["bench"] is True


def test_valor_estragado_vira_o_padrao():
    """settings.json editado a mao nao pode fazer o app decidir por acaso."""
    assert _clean_launch_item({"path": "C:/j.exe", "bench": "talvez"})["bench"] is True
    assert _clean_launch_item({"path": "C:/j.exe", "bench": 0})["bench"] is False
