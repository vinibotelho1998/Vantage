"""Sessoes gravadas: o histograma que alimenta o grafico, e apagar da lista."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.core.frames import SESSION_BIN_MS, SessionRecorder  # noqa: E402


def _gravador(frametimes) -> SessionRecorder:
    rec = SessionRecorder()
    for ft in frametimes:
        rec.add(ft)
    return rec


# ── histograma que vai para o disco ──────────────────────────────────────────
def test_sessao_guarda_histograma():
    """Sem ele, escolher uma partida deixava os graficos com a corrida anterior
    na tela, e a leitura obvia era que aqueles numeros eram da partida."""
    hist = _gravador([16.6] * 50).result()["hist"]
    assert hist["c"] and sum(hist["c"]) == 50


def test_histograma_guarda_so_a_faixa_com_frame():
    """Um jogo a 144 fps vive perto dos 7 ms; guardar os 243 ms vazios acima
    disso so' engorda o arquivo de sessoes."""
    hist = _gravador([16.6] * 30).result()["hist"]
    assert len(hist["c"]) <= 96
    inicio_ms = hist["i0"] * SESSION_BIN_MS
    assert 16.0 <= inicio_ms <= 17.0


def test_histograma_cabe_no_alvo_mesmo_com_faixa_larga():
    """Partida com frametime espalhado nao pode virar milhares de barras."""
    rec = _gravador([1.0 + i * 0.05 for i in range(4000)])
    hist = rec.result()["hist"]
    assert len(hist["c"]) <= 96
    assert sum(hist["c"]) == 4000


def test_histograma_preserva_a_contagem_total():
    frametimes = [8.0] * 10 + [16.0] * 5 + [33.0] * 2
    hist = _gravador(frametimes).result()["hist"]
    assert sum(hist["c"]) == len(frametimes)


def test_frames_lentissimos_ficam_separados():
    """O balde de estouro sao os piores frames da partida; some-los ao ultimo
    balde mentiria sobre onde eles estao."""
    hist = _gravador([8.0] * 10 + [900.0]).result()["hist"]
    assert hist["over"] == 1
    assert sum(hist["c"]) == 10


def test_sessao_vazia_nao_gera_histograma():
    assert SessionRecorder().result() == {"frames": 0}


def test_centros_das_barras_caem_na_faixa_certa():
    """A tela monta os centros a partir de i0 e w; se a conta nao fecha, o
    grafico sai deslocado no eixo."""
    hist = _gravador([10.0] * 20).result()["hist"]
    centros = [hist["i0"] * SESSION_BIN_MS + (i + 0.5) * hist["w"]
               for i in range(len(hist["c"]))]
    assert all(9.5 <= c <= 10.5 for c in centros)


# ── exclusao ─────────────────────────────────────────────────────────────────
class _App:
    def __init__(self, historico):
        self.session_history = list(historico)
        self.gravou = 0

    def save_session_history(self):
        self.gravou += 1


def _view(historico):
    from PySide6.QtWidgets import QApplication

    from vantage.ui.views.benchmark import BenchmarkView

    QApplication.instance() or QApplication([])
    from vantage.config import Settings

    app = _App(historico)
    app.settings = Settings()
    v = BenchmarkView.__new__(BenchmarkView)
    v.app = app
    return v, app


def test_excluir_grava_no_disco():
    """Sem mandar gravar, a exclusao voltava sozinha na proxima abertura."""
    historico = [{"game": "A"}, {"game": "B"}]
    v, app = _view(historico)
    v._sessao_atual = lambda: app.session_history[0]
    v._fill_sessoes = lambda: None
    v.aviso_sessao = type("L", (), {"setText": lambda self, t: None})()

    v._excluir_sessao()

    assert [s["game"] for s in app.session_history] == ["B"]
    assert app.gravou == 1


def test_excluir_sem_escolher_nao_apaga_nada():
    historico = [{"game": "A"}]
    v, app = _view(historico)
    v._sessao_atual = lambda: None
    v._fill_sessoes = lambda: None
    avisos = []
    v.aviso_sessao = type("L", (), {"setText": lambda self, t: avisos.append(t)})()

    v._excluir_sessao()

    assert len(app.session_history) == 1
    assert avisos and "Escolha" in avisos[0]


# ── paineis nao podem sobreviver a exclusao ──────────────────────────────────
class _Painel:
    """Espia o que foi escrito em cada campo da tela."""

    def __init__(self):
        self.valores = {}

    def set(self, chave, texto, cor=None, sub=None):
        self.valores[chave] = texto


def _view_com_paineis(historico):
    v, app = _view(historico)
    v.kpi = _Painel()
    v.result_rows = _Painel()
    v.sys_rows = _Painel()
    v.verdict = type("L", (), {"setText": lambda self, t: None})()
    v.relatorio = type("T", (), {"setPlainText": lambda self, t: None})()
    v.ft_chart = type("C", (), {"set_data": lambda self, d: None})()
    v.hist = type("H", (), {"set_data": lambda self, c, n: None})()
    v.card_ft = type("K", (), {"set_hint": lambda self, t, c=None: None,
                               "setVisible": lambda self, v: None})()
    v.card_hist = type("K", (), {"set_hint": lambda self, t, c=None: None,
                                 "setVisible": lambda self, v: None})()
    v.aviso_sessao = type("L", (), {"setText": lambda self, t: None})()
    v._fill_sessoes = lambda: None
    return v, app


def test_apagar_a_ultima_sessao_esvazia_os_paineis():
    """O card de Resultado continuava dizendo "Palworld, 138820 frames" com a
    lista de sessoes ja' vazia."""
    v, app = _view_com_paineis([{"game": "Palworld", "frames": 138820}])
    v._sessao_atual = lambda: (app.session_history[0] if app.session_history
                               else None)

    v._excluir_sessao()

    assert app.session_history == []
    assert v.result_rows.valores["game"] == "—"
    assert v.result_rows.valores["frames"] == "—"
    assert v.kpi.valores["avg"] == "—"


def test_paineis_sobrevivem_quando_ainda_ha_sessao_escolhida():
    """Apagar UMA de varias nao pode limpar a tela se outra segue selecionada."""
    v, app = _view_com_paineis([{"game": "A"}, {"game": "B"}])
    v._sessao_atual = lambda: (app.session_history[0] if app.session_history
                               else None)

    v._excluir_sessao()

    assert [s["game"] for s in app.session_history] == ["B"]
    assert v.result_rows.valores == {}
