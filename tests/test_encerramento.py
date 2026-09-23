"""Fechar o app tem de ir ate' o fim, mesmo quando um passo do meio falha.

A ordem do `quit` importa: devolver as telas vem antes de parar a captura. Se a
devolucao levantasse, o PresentMon nunca recebia o pedido de sair e o Qt nunca
encerrava: o app ficava pendurado na bandeja, e quem o matasse a forca daquele
ponto deixava a sessao ETW orfa, que so' sai reiniciando o Windows. Tudo aqui
e' duble: nenhuma tela e nenhum processo de verdade e' tocado.
"""
import vantage.app as appmod
from vantage.app import App


class _Anota:
    def __init__(self, nome, diario):
        self._nome = nome
        self._diario = diario

    def __getattr__(self, metodo):
        return lambda *a, **k: self._diario.append(f"{self._nome}.{metodo}")


def _app(monkeypatch, diario) -> App:
    a = App.__new__(App)
    for nome in ("window", "settings", "gamepad", "peers", "collector", "procs",
                 "ping", "gpu", "fps", "tray", "lhm", "qt"):
        setattr(a, nome, _Anota(nome, diario))
    a.bench_history = []
    a._hotkeys = None
    a._overlay = None
    monkeypatch.setattr(appmod, "_save_bench_history", lambda h: None)
    return a


def test_falha_devolvendo_as_telas_nao_impede_o_resto_do_encerramento(monkeypatch):
    diario: list[str] = []
    a = _app(monkeypatch, diario)

    def _quebra():
        raise OSError("CCD recusou a leitura")

    a._restore_displays = _quebra

    a.quit()

    assert "fps.stop" in diario
    assert "collector.stop" in diario
    assert diario[-1] == "qt.quit"


def test_encerramento_normal_segue_a_ordem(monkeypatch):
    diario: list[str] = []
    a = _app(monkeypatch, diario)
    a._restore_displays = lambda: diario.append("telas")

    a.quit()

    assert diario.index("telas") < diario.index("fps.stop")
    assert diario[-1] == "qt.quit"
