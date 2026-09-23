"""Onde o app le' e grava.

A valvula VANTAGE_DATA_DIR e' o que impede teste e script de gravar por cima do
settings.json de verdade; se ela parar de funcionar, o proximo preview apaga os
jogos do usuario.
"""
import sys

from vantage import paths


def test_valvula_aponta_os_dados_para_a_pasta_pedida(tmp_path, monkeypatch):
    alvo = tmp_path / "sandbox"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(alvo))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    assert paths.data_dir() == alvo
    assert alvo.is_dir()
    assert paths.config_file() == alvo / "settings.json"
    assert not (tmp_path / "appdata").exists()


def test_sem_valvula_os_dados_moram_em_appdata_vantage(tmp_path, monkeypatch):
    monkeypatch.delenv("VANTAGE_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "Vantage"
    assert paths.log_file() == tmp_path / "Vantage" / "logs" / "vantage.log"
    assert (tmp_path / "Vantage" / "logs").is_dir()


def test_empacotado_le_do_meipass(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.is_frozen()
    assert paths.base_dir() == tmp_path
    assert paths.asset("icons", "app.ico") == tmp_path / "assets" / "icons" / "app.ico"


def test_do_fonte_a_base_e_a_raiz_do_repositorio(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert (paths.base_dir() / "src" / "vantage" / "paths.py").exists()


def test_vendor_procura_primeiro_na_pasta_vendor(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    (tmp_path / "lhm").mkdir()
    assert paths.vendor_dir("lhm") == tmp_path / "lhm"
    (tmp_path / "vendor" / "lhm").mkdir(parents=True)
    assert paths.lhm_dir() == tmp_path / "vendor" / "lhm"


def test_vendor_ausente_devolve_o_caminho_esperado(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    assert paths.vendor_dir("nada") == tmp_path / "vendor" / "nada"


def test_presentmon_empacotado_tem_precedencia(tmp_path, monkeypatch):
    base = tmp_path / "app"
    dados = tmp_path / "dados"
    monkeypatch.setattr(paths, "base_dir", lambda: base)
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(dados))
    assert paths.presentmon_path() == dados / "tools" / "presentmon.exe"

    (base / "tools").mkdir(parents=True)
    (base / "tools" / "presentmon.exe").write_bytes(b"")
    assert paths.presentmon_path() == base / "tools" / "presentmon.exe"
