"""Gravar a partida e' escolha de cada atalho.

Alguem que so' quer abrir o jogo na TV nao precisa de relatorio no fim, e o
gravador nao deve nem comecar nesse caso.
"""
import vantage.app as appmod
from vantage.app import App
from vantage.config import Settings, _clean_launch_item
from vantage.core.series import Accumulator, History


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
    a._session_env = Accumulator()
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


def test_prioridade_usa_o_nome_do_executavel(monkeypatch):
    """A funcao confere nome contra pid antes de agir.

    O apelido do atalho ("CrimsonDesert") nunca casa com o executavel
    ("CrimsonDesert.exe"), e a promocao falhava calada dizendo que o jogo ja'
    nao estava em execucao, no instante exato em que ele acabara de abrir.
    """
    import vantage.app as appmod

    a = App.__new__(App)
    a._session_priority = "high"
    a._session_name = "CrimsonDesert"
    a.notify = lambda *args: None
    vistos = []
    monkeypatch.setattr(appmod, "_process_name", lambda pid: "CrimsonDesert.exe")
    monkeypatch.setattr(appmod.procs, "mudar_prioridade",
                        lambda pid, nome, chave: (vistos.append((pid, nome, chave)),
                                                  (True, "ok"))[1])
    a._apply_launch_priority(4242)
    assert vistos == [(4242, "CrimsonDesert.exe", "high")]


def test_sem_nome_de_processo_cai_no_apelido(monkeypatch):
    """Processo que morreu entre a descoberta e a promocao nao pode estourar."""
    import vantage.app as appmod

    a = App.__new__(App)
    a._session_priority = "high"
    a._session_name = "Jogo"
    a.notify = lambda *args: None
    vistos = []
    monkeypatch.setattr(appmod, "_process_name", lambda pid: "")
    monkeypatch.setattr(appmod.procs, "mudar_prioridade",
                        lambda pid, nome, chave: (vistos.append(nome), (True, "ok"))[1])
    a._apply_launch_priority(1)
    assert vistos == ["Jogo"]


# ── sistema durante a partida ────────────────────────────────────────────────
class _Sessao:
    def __init__(self, path, args=""):
        self.path = path

    def start(self):
        return True, "ok"


def _jogar(monkeypatch, a) -> None:
    """Abre o atalho pelo caminho de verdade, com telas e processo de mentira."""
    telas = type("D", (), {"snapshot": lambda self: [],
                           "list_displays": lambda self, with_modes=False: []})()
    monkeypatch.setattr(appmod, "dsp", telas)
    monkeypatch.setattr(appmod, "GameSession", _Sessao)
    a._session_off = ""
    a._bp_voltar = False
    ok, _msg = a.play_item({"path": r"C:\Jogos\jogo.exe", "name": "jogo", "bench": True})
    assert ok


def _tique(a, cpu: float, gpu: float) -> None:
    dados = {"cpu_pct": cpu, "gpu": {"usage": gpu}}
    a.collector = type("C", (), {"snapshot": lambda self: dict(dados)})()
    a._tick_system()


def test_media_do_sistema_no_resumo_e_so_da_partida(monkeypatch):
    """O relatorio diz "media do sistema durante a partida", e o numero vinha do
    acumulador do app inteiro: horas de area de trabalho parada entravam na media
    do jogo, e duas partidas diferentes saiam com a mesma media."""
    a = _app(monkeypatch)
    a.stats = Accumulator()
    a.history = History(100)
    a._stream = None
    a._bench_active = False
    a.lhm = type("L", (), {"tree": lambda self: []})()
    a.window = type("W", (), {"isVisible": lambda self: False})()
    a._check_alerts = lambda d, g: None
    a._update_tray_tooltip = lambda d, g: None

    for _ in range(300):                    # a tarde inteira com o PC parado
        _tique(a, cpu=3.0, gpu=1.0)
    a._session_bench = True                  # uma partida anterior, ja' gravada
    _tique(a, cpu=50.0, gpu=50.0)
    a._close_session_bench()

    _jogar(monkeypatch, a)
    for _ in range(10):
        _tique(a, cpu=80.0, gpu=97.0)
    a._close_session_bench()

    registro = a.session_history[-1]
    assert registro["cpu"] == 80.0
    assert registro["gpu"] == 97.0
