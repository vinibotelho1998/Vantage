"""Historicos gravados em disco: partidas, corridas cronometradas e o ultimo resultado.

Tudo aqui roda numa pasta temporaria, nunca na pasta de dados de verdade.
"""
import json
import pathlib

import pytest

import vantage.app as appmod


@pytest.fixture(autouse=True)
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    return tmp_path


def _disco_cheio(self, *_a, **_k):
    """Como o Windows se comporta sem espaco: o "w" ja' truncou, a escrita nao cabe."""
    with open(self, "w", encoding="utf-8"):
        pass
    raise OSError(28, "No space left on device")


def test_disco_cheio_nao_apaga_as_partidas_ja_gravadas(pasta, monkeypatch):
    """Escrever direto no arquivo trunca antes de gravar. Com o disco cheio (ou
    o app derrubado no meio) o historico ficava vazio, a abertura seguinte lia
    lista nenhuma, e a proxima gravacao confirmava a perda por cima."""
    antigas = [{"game": "Forza", "frames": 90000, "fps_avg": 120.0}]
    appmod._save_session_history(antigas)

    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "write_text", _disco_cheio)
        appmod._save_session_history(antigas + [{"game": "CS2", "frames": 5000}])

    assert appmod._load_session_history() == antigas


def test_disco_cheio_nao_apaga_as_corridas_cronometradas(pasta, monkeypatch):
    antigas = [{"time": "01/09 20:00", "game": "Forza", "avg": 120.0}]
    appmod._save_bench_history(antigas)

    with monkeypatch.context() as m:
        m.setattr(pathlib.Path, "write_text", _disco_cheio)
        appmod._save_bench_history(antigas + [{"game": "CS2"}])

    assert appmod._load_bench_history() == antigas


def test_gravacao_nao_deixa_temporario_para_tras(pasta):
    appmod._save_session_history([{"game": "Forza"}])
    assert sorted(p.name for p in pasta.iterdir()) == ["sessoes.json"]


def test_historico_que_nao_e_lista_vira_lista_vazia(pasta):
    """Um texto qualquer no lugar da lista virava a propria string: o fatiamento
    funciona em texto, e o `append` da proxima partida derrubava o app."""
    (pasta / "sessoes.json").write_text(json.dumps("estragado"), encoding="utf-8")
    (pasta / "benchmarks.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

    assert appmod._load_session_history() == []
    assert appmod._load_bench_history() == []


def test_registro_que_nao_e_dicionario_fica_de_fora(pasta):
    (pasta / "sessoes.json").write_text(json.dumps([{"game": "Forza"}, 3, "x", None]),
                                        encoding="utf-8")
    assert appmod._load_session_history() == [{"game": "Forza"}]


@pytest.mark.parametrize("conteudo", ["[]", "null", '{"system": {"cpu": 5}}',
                                      '{"metrics": [1, 2]}'])
def test_ultimo_benchmark_estranho_nao_impede_o_app_de_abrir(pasta, conteudo):
    """Esta leitura roda no construtor do App: qualquer excecao aqui era o app
    que nao abria mais, ate' alguem achar e apagar o arquivo na mao."""
    (pasta / "ultimo-benchmark.json").write_text(conteudo, encoding="utf-8")
    assert appmod._load_last_bench() is None


def _ler_csv(caminho) -> list[list[str]]:
    import csv

    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def test_exportar_o_benchmark_que_voltou_do_disco_nao_sai_vazio(pasta):
    """O ultimo resultado volta com o app sem as amostras cruas, so' com os
    frametimes. Exportar dele gravava um CSV so' com o cabecalho, e a tela ainda
    dizia "Benchmark exportado"."""
    from vantage.core import frames as fr

    appmod._save_last_bench({"game": "Forza", "metrics": fr.FrameMetrics(),
                             "frametimes": [8.0, 8.5, 9.0], "system": {}})
    app = appmod.App.__new__(appmod.App)
    app._bench_result = appmod._load_last_bench()

    linhas = _ler_csv(app.benchmark_export())

    assert len(linhas) == 1 + 3
    assert [linha[1] for linha in linhas[1:]] == ["8,000", "8,500", "9,000"]
    assert linhas[-1][0] == "0,0255"          # tempo acumulado, em segundos
    assert linhas[1][2] == ""                 # o que so' a captura ao vivo tinha


def test_benchmark_sem_frametime_nenhum_nao_exporta_arquivo_vazio(pasta):
    app = appmod.App.__new__(appmod.App)
    app._bench_result = {"game": "Forza", "samples": [], "frametimes": []}
    assert app.benchmark_export() is None
    assert not (pasta / "reports").exists() or not list((pasta / "reports").iterdir())
