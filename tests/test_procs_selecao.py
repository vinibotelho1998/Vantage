"""A tela de processos agindo: selecao e dialogos, sem tocar em processo nenhum.

A tabela se reordena sozinha a cada 2,5 s. O destaque preso na linha pularia
para outro processo entre o olhar e o clique, e o botao Finalizar acertaria quem
nao devia; por isso a selecao segue o PID e as acoes leem a identidade guardada
na celula, nunca o indice da linha. Os dialogos entram no mesmo assunto: o que
eles devolvem tem de ser exatamente o que esta' marcado na tela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.sensors.procs import ProcInfo  # noqa: E402
from vantage.ui.views import processes  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Cfg:
    accent = "cyan"


class _Procs:
    def __init__(self, linhas):
        self.linhas = linhas

    def snapshot(self):
        return list(self.linhas)

    def totals(self):
        return len(self.linhas), 0


class _App:
    """So' a superficie que a tela de processos usa do controlador."""

    def __init__(self, linhas):
        self.settings = _Cfg()
        self.procs = _Procs(linhas)


def _linhas(cpu_do_jogo: float, com_jogo: bool = True):
    fora = [ProcInfo(10, "a.exe", 40.0, 100.0, 4), ProcInfo(30, "c.exe", 1.0, 50.0, 2)]
    if not com_jogo:
        return fora
    return [fora[0], ProcInfo(20, "jogo.exe", cpu_do_jogo, 200.0, 8, True), fora[1]]


def _tela(linhas):
    view = processes.ProcessesView(_App(linhas))
    view.on_system({})
    return view


def test_selecao_acompanha_o_processo_quando_a_ordem_muda():
    view = _tela(_linhas(20.0))
    view.table.selectRow(1)
    assert view._alvo() == (20, "jogo.exe")

    view.app.procs.linhas = _linhas(95.0)   # o jogo disparou e foi para o topo
    view.on_system({})

    assert view.table.currentRow() == 0
    assert view._alvo() == (20, "jogo.exe")


def test_processo_que_sai_da_lista_solta_a_selecao():
    """Herdar a selecao da linha vaga entregaria outro processo para as acoes."""
    view = _tela(_linhas(20.0))
    view.table.selectRow(1)

    view.app.procs.linhas = _linhas(0.0, com_jogo=False)
    view.on_system({})

    assert view._alvo() is None


def test_finalizar_usa_o_pid_e_o_nome_da_celula(monkeypatch):
    view = _tela(_linhas(20.0))
    view.table.selectRow(1)
    monkeypatch.setattr(processes, "confirmar", lambda *a, **k: True)
    recebido = {}
    monkeypatch.setattr(processes.P, "encerrar",
                        lambda pid, nome: (recebido.update(pid=pid, nome=nome), (True, "ok"))[1])

    view._finalizar()

    assert recebido == {"pid": 20, "nome": "jogo.exe"}


def test_finalizar_essencial_para_antes_de_perguntar(monkeypatch):
    """A recusa vem antes do popup: nao existe 'confirmar' matar o lsass.exe."""
    view = _tela([ProcInfo(700, "lsass.exe", 2.0, 30.0, 6)])
    view.table.selectRow(0)
    passos = []
    monkeypatch.setattr(processes, "confirmar",
                        lambda *a, **k: (passos.append("perguntou"), True)[1])
    monkeypatch.setattr(processes.P, "encerrar",
                        lambda *a: (passos.append("matou"), (True, "ok"))[1])

    view._finalizar()

    assert passos == []
    assert "essencial" in view.status.text()


def test_sem_selecao_as_acoes_so_pedem_para_escolher(monkeypatch):
    view = _tela(_linhas(20.0))
    passos = []
    monkeypatch.setattr(processes, "confirmar",
                        lambda *a, **k: (passos.append("perguntou"), True)[1])
    monkeypatch.setattr(processes.P, "encerrar",
                        lambda *a: (passos.append("matou"), (True, "ok"))[1])

    view._finalizar()

    assert passos == []
    assert "Escolha um processo" in view.status.text()


# ── dialogos (montados, nunca exibidos) ───────────────────────────────────────
def test_afinidade_ilegivel_comeca_com_tudo_marcado():
    """Marcar 'nada' viraria travar o processo num nucleo so' ao clicar em Aplicar."""
    dlg = processes.AfinidadeDialog("jogo.exe", 20, None, 8)
    assert dlg.nucleos() == list(range(8))


def test_afinidade_abre_com_o_que_o_processo_ja_usa():
    dlg = processes.AfinidadeDialog("jogo.exe", 20, [2, 3], 8)
    assert dlg.nucleos() == [2, 3]


def test_atalho_de_texto_marca_exatamente_o_que_foi_digitado():
    dlg = processes.AfinidadeDialog("jogo.exe", 20, [0, 1, 2, 3], 8)
    dlg._campo.setText("4-6")
    dlg._aplicar_texto()
    assert dlg.nucleos() == [4, 5, 6]


def test_texto_impossivel_nao_mexe_na_selecao():
    """Aplicar um palpite seria pior que nao aplicar: ninguem conferiria depois."""
    dlg = processes.AfinidadeDialog("jogo.exe", 20, [0, 1], 8)
    dlg._campo.setText("0-99")
    dlg._aplicar_texto()
    assert dlg.nucleos() == [0, 1]
    assert "0 a 7" in dlg._resumo.text()


def test_prioridade_ilegivel_abre_em_normal():
    dlg = processes.PrioridadeDialog("jogo.exe", 20, None)
    assert dlg.escolha() == "normal"


def test_prioridade_abre_na_faixa_atual_e_devolve_a_escolhida():
    dlg = processes.PrioridadeDialog("jogo.exe", 20, psutil.HIGH_PRIORITY_CLASS)
    assert dlg.escolha() == "high"
    dlg._botoes["idle"].setChecked(True)
    assert dlg.escolha() == "idle"


def test_aviso_de_tempo_real_so_aparece_ao_marcar_tempo_real():
    dlg = processes.PrioridadeDialog("jogo.exe", 20, None)
    assert dlg._alerta.text() == ""
    dlg._botoes["realtime"].setChecked(True)
    assert "mouse" in dlg._alerta.text()
    dlg._botoes["normal"].setChecked(True)
    assert dlg._alerta.text() == ""
