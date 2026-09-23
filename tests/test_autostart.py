"""Iniciar com o Windows, com um winreg falso: o registro de verdade fica intocado."""
import sys
import types

import pytest

from vantage.platform import autostart


class _Chave:
    pass


@pytest.fixture
def registro(monkeypatch):
    valores = {}
    falso = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU", KEY_SET_VALUE=2, REG_SZ=1, abertas=[], fechadas=[])

    def open_key(raiz, caminho, reservado, acesso):
        chave = _Chave()
        falso.abertas.append((raiz, caminho))
        return chave

    def set_value(chave, nome, reservado, tipo, valor):
        valores[nome] = valor

    def delete_value(chave, nome):
        if nome not in valores:
            raise FileNotFoundError(nome)
        del valores[nome]

    falso.OpenKey = open_key
    falso.SetValueEx = set_value
    falso.DeleteValue = delete_value
    falso.CloseKey = lambda chave: falso.fechadas.append(chave)
    falso.valores = valores
    monkeypatch.setitem(sys.modules, "winreg", falso)
    return falso


def test_ligar_grava_o_comando_na_chave_run(registro, monkeypatch):
    monkeypatch.setattr(autostart, "_command", lambda: '"C:\\app\\Vantage.exe"')
    autostart.set_enabled(True)
    assert registro.abertas == [("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")]
    assert registro.valores == {"Vantage": '"C:\\app\\Vantage.exe"'}
    assert len(registro.fechadas) == 1


def test_desligar_remove_e_desligar_de_novo_nao_quebra(registro, monkeypatch):
    """Desligar o que ja' esta' desligado e' normal, e nao falha para o log."""
    monkeypatch.setattr(autostart, "_command", lambda: "x")
    avisos = []
    monkeypatch.setattr(autostart._log, "warning", lambda *a: avisos.append(a))
    autostart.set_enabled(True)
    autostart.set_enabled(False)
    assert registro.valores == {}
    autostart.set_enabled(False)
    assert len(registro.fechadas) == 3
    assert avisos == []


def test_falha_no_registro_nao_derruba(registro):
    def recusa(*a):
        raise PermissionError("acesso negado")
    registro.OpenKey = recusa
    autostart.set_enabled(True)


def test_empacotado_abre_o_proprio_executavel(monkeypatch):
    monkeypatch.setattr(autostart.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Vantage\Vantage.exe")
    assert autostart._command() == r'"C:\Program Files\Vantage\Vantage.exe"'


def test_do_fonte_abre_sem_console(monkeypatch):
    """Com python.exe, o login do Windows abriria uma janela preta junto."""
    monkeypatch.setattr(autostart.paths, "is_frozen", lambda: False)
    monkeypatch.setattr(sys, "executable", r"C:\venv\Scripts\python.exe")
    assert autostart._command() == r'"C:\venv\Scripts\pythonw.exe" -m vantage'
