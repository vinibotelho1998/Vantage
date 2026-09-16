"""Exportacao das sessoes de jogo.

O relatorio de uma partida e' o que se leva para comparar com alguem, entao ele
precisa abrir direito numa planilha, inclusive quando as sessoes foram gravadas
por versoes diferentes do app.
"""
import csv
import os

os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.core import export  # noqa: E402

_ANTIGA = {"quando": "01/01 10:00", "game": "jogo_velho.exe", "duracao_s": 600,
           "frames": 90000, "fps_avg": 120.0, "low_1": 80.0}
_NOVA = {"quando": "20/08 11:20", "game": "forza.exe", "duracao_s": 3720,
         "frames": 512000, "fps_avg": 142.5, "fps_min": 61.0, "fps_max": 240.0,
         "low_1": 98.4, "ft_avg": 7.02, "ft_max": 16.4, "hitches": 3,
         "stutters": 420, "stutter_pct": 0.08, "cpu": 38.2, "gpu": 97.5}


def _ler(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh, delimiter=";"))


def test_cabecalho_e_fixo_mesmo_com_sessao_antiga():
    """Sessao gravada antes de uma metrica existir nao pode entortar a planilha.

    Se o cabecalho saisse das chaves de cada linha, uma sessao velha produziria
    menos colunas que a nova e a planilha abriria desalinhada.
    """
    caminho = export.export_sessions([_NOVA, _ANTIGA], "misto")
    linhas = _ler(caminho)
    assert len(linhas) == 3
    assert len(linhas[1]) == len(linhas[0])
    assert len(linhas[2]) == len(linhas[0])


def test_o_que_falta_sai_vazio_e_nao_zero():
    """Zero se le' como medicao; vazio se le' como 'nao medido'."""
    caminho = export.export_sessions([_ANTIGA], "antiga")
    cab, linha = _ler(caminho)
    valores = dict(zip(cab, linha))
    assert valores["Travadas"] == ""
    assert valores["FPS médio"] == "120.0"


def test_nome_de_jogo_perigoso_nao_vira_caminho():
    """O nome vem do executavel, e caminho relativo ali escreveria fora da pasta."""
    caminho = export.export_sessions([_NOVA], "..\\..\\windows\\system32")
    assert "reports" in str(caminho)
    assert ".." not in caminho.name


def test_lista_vazia_ainda_gera_o_cabecalho():
    caminho = export.export_sessions([], "nada")
    assert len(_ler(caminho)) == 1
