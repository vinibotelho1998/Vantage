"""RAM do jogo: duas medidas, e nenhuma delas fingida quando o jogo fecha.

O risco principal e' o grafico que despenca sozinho: o working set e' so' o que
esta' residente agora, e o Windows o poda quando a janela perde o foco. Medindo o
RadeonSoftware deu 50 MB de working set contra 1150 MB comprometidos: em alt-tab
um jogo faria a mesma curva sem ter liberado nada. O segundo risco e' o oposto:
quando o jogo fecha, a chave tem de sumir do snapshot; um zero parado na tela le'
como "o jogo nao usa RAM".
"""
import psutil
import pytest

from vantage.sensors.collector import _GameMemory


class _Mem:
    def __init__(self, rss: float, private: float):
        self.rss = rss
        self.private = private


class _Proc:
    """Processo vivo com o handle preso, como o coletor usa."""

    def __init__(self, pid: int, nome: str, rss: float, private: float):
        self.pid = pid
        self._nome = nome
        self._mem = _Mem(rss, private)
        self.leituras = 0
        self.nomeacoes = 0

    def name(self) -> str:
        self.nomeacoes += 1
        return self._nome

    def memory_info(self) -> _Mem:
        self.leituras += 1
        return self._mem


def _fabrica(*processos):
    tabela = {p.pid: p for p in processos}

    def abrir(pid):
        if pid not in tabela:
            raise psutil.NoSuchProcess(pid)
        return tabela[pid]
    return abrir


@pytest.fixture
def sonda(monkeypatch):
    def montar(*processos) -> _GameMemory:
        monkeypatch.setattr(psutil, "Process", _fabrica(*processos))
        return _GameMemory()
    return montar


def test_publica_o_alocado_e_o_residente_lado_a_lado(sonda):
    """So' o working set faria o jogo em alt-tab parecer que largou a RAM."""
    m = sonda(_Proc(4242, "cs2.exe", 50.3 * 1024 ** 2, 1150.9 * 1024 ** 2))
    m.follow(4242)
    d = m.read()
    assert d["game_pid"] == 4242
    assert d["game_name"] == "cs2.exe"
    assert d["game_ram_private"] == 1150.9
    assert d["game_ram_wset"] == 50.3


def test_sem_jogo_nao_ha_chave_nenhuma(sonda):
    """Sem jogo o card some inteiro; zero seria uma medida que nao existe."""
    m = sonda()
    assert m.read() is None
    m.follow(0)
    assert m.read() is None


def test_jogo_que_fechou_para_de_publicar(sonda):
    """O pid morre antes de o app perceber; o ultimo numero nao pode congelar."""
    proc = _Proc(4242, "cs2.exe", 1024 ** 2, 2 * 1024 ** 2)
    m = sonda(proc)
    m.follow(4242)
    assert m.read() is not None
    m.follow(9999)
    assert m.read() is None


def test_handle_fica_preso_entre_ciclos(sonda):
    """process_iter custa 72,7 ms e memory_info no handle aberto custa 0,005 ms."""
    proc = _Proc(4242, "cs2.exe", 1024 ** 2, 2 * 1024 ** 2)
    m = sonda(proc)
    m.follow(4242)
    for _ in range(5):
        m.read()
    assert proc.leituras == 5
    assert proc.nomeacoes == 1


def test_troca_de_jogo_nao_reaproveita_o_handle_antigo(sonda):
    """Fechar um jogo e abrir outro nao pode mostrar a RAM do que ja' morreu."""
    velho = _Proc(1, "antigo.exe", 1024 ** 2, 1024 ** 2)
    novo = _Proc(2, "novo.exe", 8 * 1024 ** 2, 9 * 1024 ** 2)
    m = sonda(velho, novo)
    m.follow(1)
    m.read()
    m.follow(2)
    d = m.read()
    assert d["game_name"] == "novo.exe"
    assert d["game_ram_private"] == 9.0


def test_sistema_sem_private_bytes_ainda_da_o_residente(monkeypatch):
    """Fora do Windows o memory_info nao tem .private; a chave some, o resto fica."""
    class _SoRss:
        rss = 4 * 1024 ** 2

    class _ProcSoRss:
        pid = 7

        def name(self):
            return "jogo"

        def memory_info(self):
            return _SoRss()

    monkeypatch.setattr(psutil, "Process", lambda pid: _ProcSoRss())
    m = _GameMemory()
    m.follow(7)
    d = m.read()
    assert d["game_ram_wset"] == 4.0
    assert "game_ram_private" not in d
