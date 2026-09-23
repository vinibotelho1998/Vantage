"""CSV de sensores, de quadros e de benchmark.

A planilha e' aberta num Excel em portugues: separador ponto e virgula, virgula
decimal e vazio onde nao houve medicao. Numero com ponto vira texto la dentro,
e zero no lugar de "nao medido" vira media errada.
"""
import csv
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.core import export  # noqa: E402
from vantage.core import frames as fr  # noqa: E402


@pytest.fixture(autouse=True)
def _pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    return tmp_path


def _ler(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def test_numero_sai_com_virgula_decimal():
    assert export._num(3.14159) == "3,14"
    assert export._num(2, 3) == "2,000"
    assert export._num("7.5") == "7,50"


def test_sem_medicao_sai_vazio():
    assert export._num(None) == ""
    assert export._num("") == ""
    assert export._num(float("nan")) == ""


def test_texto_que_nao_e_numero_passa_como_esta():
    assert export._num("GPU 0") == "GPU 0"


def test_csv_de_sensores_leva_minimo_medio_e_maximo(tmp_path):
    no_a = SimpleNamespace(key="a", hardware="CPU", name="Package", kind="Temperature",
                           unit="°C", value=61.25)
    no_b = SimpleNamespace(key="b", hardware="GPU", name="Hot Spot", kind="Temperature",
                           unit="°C", value=None)
    caminho = export.export_sensors([no_a, no_b], {"a": (40.0, 55.5, 80.125)})
    assert caminho.parent == tmp_path / "reports"
    cab, a, b = _ler(caminho)
    assert cab[0] == "Hardware" and len(cab) == 8
    assert a == ["CPU", "Package", "Temperature", "°C", "61,25", "40,00", "55,50", "80,12"]
    assert b[4:] == ["", "", "", ""]


def test_csv_de_quadros_na_ordem_das_colunas():
    amostra = [0.0] * 8
    amostra[fr.T] = 1.23456
    amostra[fr.FT] = 6.9444
    amostra[fr.CPU_BUSY] = 3.5
    amostra[fr.GPU_BUSY] = 6.1
    amostra[fr.GPU_TIME] = 6.2
    amostra[fr.DISP_LAT] = 12.0
    amostra[fr.DISPLAYED] = 6.95
    caminho = export.export_frames([tuple(amostra)], "forza.exe")
    cab, linha = _ler(caminho)
    assert cab[:2] == ["Tempo (s)", "Frametime (ms)"]
    assert linha == ["1,2346", "6,944", "3,500", "6,100", "6,200", "12,000", "6,950"]


def test_nome_do_jogo_nao_escapa_da_pasta_de_relatorios(tmp_path):
    caminho = export.export_frames([], r"..\..\Windows\evil.exe")
    assert caminho.parent == tmp_path / "reports"
    assert "\\" not in caminho.name and "/" not in caminho.name
    caminho = export.export_benchmark({}, "////")
    assert caminho.name.startswith("benchmark-sessao-")


def test_benchmark_so_leva_metricas_numericas():
    caminho = export.export_benchmark(
        {"fps_avg": 142.456, "game": "forza.exe", "low_1": 98, "lista": [1, 2]}, "forza")
    linhas = _ler(caminho)
    assert linhas == [["Métrica", "Valor"], ["fps_avg", "142,46"], ["low_1", "98,00"]]


def test_disco_recusando_devolve_nenhum(monkeypatch, tmp_path):
    """A tela precisa saber que falhou para nao dizer 'salvo' sem arquivo."""
    bloqueio = tmp_path / "reports"
    bloqueio.mkdir()
    monkeypatch.setattr(export, "_stamp", lambda: "fixo")
    (bloqueio / "benchmark-x-fixo.csv").mkdir()
    assert export.export_benchmark({"a": 1}, "x") is None
