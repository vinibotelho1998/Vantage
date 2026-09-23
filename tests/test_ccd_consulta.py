"""Leitura da configuracao de telas pela CCD, sem tocar em tela nenhuma.

O user32 aqui e' um duble: so' `GetDisplayConfigBufferSizes` e
`QueryDisplayConfig` existem nele, e nenhum dos dois conversa com o Windows.
Nada neste arquivo pode chegar perto de `SetDisplayConfig`.
"""
from vantage.platform import ccd


class _User32:
    """Responde tamanhos e, nas primeiras leituras, a recusa por buffer curto."""

    def __init__(self, recusas: int, caminhos: int = 2, modos: int = 3):
        self.recusas = recusas
        self.caminhos = caminhos
        self.modos = modos
        self.consultas = 0

    def GetDisplayConfigBufferSizes(self, _flags, n_paths, n_modes):
        n_paths._obj.value = self.caminhos
        n_modes._obj.value = self.modos
        return ccd.ERROR_SUCCESS

    def QueryDisplayConfig(self, _flags, n_paths, _paths, n_modes, _modes, _topo):
        self.consultas += 1
        if self.consultas <= self.recusas:
            return ccd.ERROR_INSUFFICIENT_BUFFER
        return ccd.ERROR_SUCCESS

    def SetDisplayConfig(self, *_a):
        raise AssertionError("leitura nao pode aplicar configuracao nenhuma")


def test_topologia_mudando_no_meio_da_leitura_e_lida_de_novo(monkeypatch):
    """Entre medir o buffer e ler, um monitor pode entrar ou sair; o Windows
    responde ERROR_INSUFFICIENT_BUFFER e a documentacao manda medir de novo.
    Desistir ali fazia o arranjo falhar exatamente quando a TV era plugada."""
    falso = _User32(recusas=1)
    monkeypatch.setattr(ccd, "user32", falso)

    cfg = ccd.query(all_paths=True)

    assert cfg is not None
    assert (cfg.path_count, cfg.mode_count) == (2, 3)
    assert falso.consultas == 2


def test_recusa_que_nao_passa_desiste_sem_laco_infinito(monkeypatch):
    falso = _User32(recusas=99)
    monkeypatch.setattr(ccd, "user32", falso)

    assert ccd.query(all_paths=False) is None
    assert falso.consultas <= 5


def test_outro_erro_nao_e_repetido(monkeypatch):
    falso = _User32(recusas=0)
    falso.QueryDisplayConfig = lambda *a: 87          # parametro invalido
    monkeypatch.setattr(ccd, "user32", falso)

    assert ccd.query() is None
