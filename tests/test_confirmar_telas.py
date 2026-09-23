"""Confirmar ou desfazer a mudanca de telas.

Mexer em resolucao ou topologia pode deixar a maquina sem imagem; o relogio que
desfaz sozinho e' a saida de emergencia. Nenhum dialogo e' exibido aqui: o
relogio e' avancado na mao e o `ask` e' trocado por um falso.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402

from vantage.ui import confirm  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_relogio_no_fim_desfaz_sem_ninguem_clicar():
    dlg = confirm.ConfirmRevertDialog("1920x1080 na TV", 3)
    recusas = []
    dlg.rejected.connect(lambda: recusas.append(1))
    dlg._timer.start(1000)
    dlg._tick()
    dlg._tick()
    assert recusas == []
    assert "1s" in dlg._count.text()
    dlg._tick()
    assert recusas == [1]
    assert dlg._kept is False
    assert not dlg._timer.isActive()


def test_contagem_aparece_no_texto_e_na_barra():
    dlg = confirm.ConfirmRevertDialog("x", 15)
    assert "15s" in dlg._count.text()
    dlg._tick()
    assert "14s" in dlg._count.text()
    assert dlg._bar.value() == 14


def test_manter_marca_como_mantido_e_para_o_relogio():
    dlg = confirm.ConfirmRevertDialog("x", 10)
    aceites = []
    dlg.accepted.connect(lambda: aceites.append(1))
    dlg._timer.start(1000)
    dlg._keep()
    assert dlg._kept is True
    assert not dlg._timer.isActive()
    assert aceites == [1]


def test_segundos_zerados_ainda_dao_um_segundo_de_relogio():
    dlg = confirm.ConfirmRevertDialog("x", 0)
    assert dlg._total == 1


def test_sem_resposta_chama_o_desfazer(monkeypatch):
    monkeypatch.setattr(confirm.ConfirmRevertDialog, "ask", lambda self: False)
    desfeitos = []
    assert confirm.confirm_or_revert("x", 15, lambda: desfeitos.append(1)) is False
    assert desfeitos == [1]


def test_mantido_nao_desfaz(monkeypatch):
    monkeypatch.setattr(confirm.ConfirmRevertDialog, "ask", lambda self: True)
    desfeitos = []
    assert confirm.confirm_or_revert("x", 15, lambda: desfeitos.append(1)) is True
    assert desfeitos == []


def test_confirmacao_desligada_nao_abre_dialogo_nem_desfaz(monkeypatch):
    def nao_pode(*a, **k):
        raise AssertionError("dialogo aberto com a confirmacao desligada")
    monkeypatch.setattr(confirm, "ConfirmRevertDialog", nao_pode)
    desfeitos = []
    assert confirm.confirm_or_revert("x", 0, lambda: desfeitos.append(1)) is True
    assert desfeitos == []


def test_enter_no_sim_ou_nao_cai_no_cancelar():
    """Acao destrutiva nunca e' o que acontece quando alguem so' aperta Enter."""
    dlg = confirm.ConfirmDialog("Apagar?", "Some de vez.", "Apagar", perigo=True)
    padrao = [b for b in dlg.findChildren(QPushButton) if b.isDefault()]
    assert [b.text() for b in padrao] == ["Cancelar"]
    perigoso = [b for b in dlg.findChildren(QPushButton) if b.text() == "Apagar"]
    assert perigoso[0].objectName() == "Danger"


def test_confirmar_so_e_verdade_com_aceite(monkeypatch):
    monkeypatch.setattr(confirm.ConfirmDialog, "exec",
                        lambda self: QDialog.DialogCode.Rejected)
    assert confirm.confirmar("t", "x") is False
    monkeypatch.setattr(confirm.ConfirmDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    assert confirm.confirmar("t", "x") is True
