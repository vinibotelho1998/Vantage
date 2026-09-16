"""Varredura de jogos instalados: achar o executavel certo, sem trazer lixo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.platform import gamescan  # noqa: E402


def _exe(pasta, nome, tamanho=1024):
    alvo = pasta / nome
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(b"\0" * tamanho)
    return alvo


# ── escolha do executavel ────────────────────────────────────────────────────
def test_prefere_o_exe_com_o_nome_do_jogo(tmp_path):
    """O maior arquivo da pasta costuma ser motor ou ferramenta; o que se chama
    como o jogo quase sempre e' o jogo."""
    jogo = tmp_path / "Crimson Desert"
    _exe(jogo, "Launcher.exe", 90_000)
    _exe(jogo / "bin64", "CrimsonDesert.exe", 1_000)

    assert gamescan._melhor_exe(jogo, "Crimson Desert").name == "CrimsonDesert.exe"


def test_ignora_instalador_e_desinstalador(tmp_path):
    """Sem a lista de lixo, o palpite caia no redistribuivel da Microsoft."""
    jogo = tmp_path / "Jogo"
    _exe(jogo, "vcredist_x64.exe", 900_000)
    _exe(jogo, "unins000.exe", 800_000)
    _exe(jogo, "Jogo.exe", 100)

    assert gamescan._melhor_exe(jogo, "Jogo").name == "Jogo.exe"


def test_acha_exe_em_binaries_win64(tmp_path):
    """Layout da Unreal: o executavel fica tres niveis abaixo da pasta."""
    jogo = tmp_path / "It Takes Two"
    _exe(jogo / "Nuts" / "Binaries" / "Win64", "ItTakesTwo.exe")

    achado = gamescan._melhor_exe(jogo, "It Takes Two")
    assert achado is not None and achado.name == "ItTakesTwo.exe"


def test_tamanho_desempata_quando_nome_nao_ajuda(tmp_path):
    jogo = tmp_path / "Coisa"
    _exe(jogo, "aaa.exe", 10)
    _exe(jogo, "bbb.exe", 5_000)

    assert gamescan._melhor_exe(jogo, "Zzz").name == "bbb.exe"


def test_pasta_sem_executavel_devolve_none(tmp_path):
    vazia = tmp_path / "Vazia"
    vazia.mkdir()
    assert gamescan._melhor_exe(vazia, "Vazia") is None


def test_nao_desce_em_pasta_de_recurso(tmp_path):
    """`Content` e afins tem milhares de arquivos e nenhum executavel de jogo."""
    jogo = tmp_path / "Jogo"
    _exe(jogo / "Content" / "Paks", "Jogo.exe", 999_999)
    _exe(jogo, "Jogo.exe", 10)

    achado = gamescan._melhor_exe(jogo, "Jogo")
    assert achado.parent == jogo


# ── normalizacao de nome ─────────────────────────────────────────────────────
def test_normal_ignora_espaco_e_pontuacao():
    assert gamescan._normal("Crimson Desert") == gamescan._normal("CrimsonDesert.")


def test_normal_ignora_caixa():
    assert gamescan._normal("PALWORLD") == gamescan._normal("Palworld")


# ── deduplicacao ─────────────────────────────────────────────────────────────
def test_scan_nao_repete_jogo_que_ja_esta_na_lista(monkeypatch):
    monkeypatch.setattr(gamescan, "_do_steam",
                        lambda: [gamescan.Achado("Palworld", r"D:\g\Palworld.exe", "Steam")])
    monkeypatch.setattr(gamescan, "_da_area_de_trabalho", list)
    monkeypatch.setattr(gamescan, "_das_pastas", list)

    assert gamescan.scan([r"d:\g\palworld.exe"]) == []


def test_scan_nao_repete_o_mesmo_jogo_vindo_de_duas_fontes(monkeypatch):
    """O Steam acha o .exe e a area de trabalho acha o .url do MESMO jogo.

    Sao caminhos diferentes, entao comparar so' caminho deixava tudo em dobro.
    """
    monkeypatch.setattr(gamescan, "_do_steam",
                        lambda: [gamescan.Achado("Dota 2", r"D:\g\dota2.exe", "Steam")])
    monkeypatch.setattr(gamescan, "_da_area_de_trabalho",
                        lambda: [gamescan.Achado("Dota 2", r"C:\Desktop\Dota 2.url",
                                                 "atalho")])
    monkeypatch.setattr(gamescan, "_das_pastas", list)

    achados = gamescan.scan([])
    assert len(achados) == 1
    # O Steam vem primeiro e ganha: ele sabe o nome de verdade do jogo.
    assert achados[0].source == "Steam"


def test_scan_sobrevive_a_fonte_que_falha(monkeypatch):
    def explode():
        raise OSError("disco sumiu")

    monkeypatch.setattr(gamescan, "_do_steam", explode)
    monkeypatch.setattr(gamescan, "_da_area_de_trabalho",
                        lambda: [gamescan.Achado("X", r"C:\x.exe", "atalho")])
    monkeypatch.setattr(gamescan, "_das_pastas", list)

    assert [a.name for a in gamescan.scan([])] == ["X"]


def test_e_lixo_pega_variacoes():
    assert gamescan._e_lixo("UnityCrashHandler64")
    assert gamescan._e_lixo("unins000")
    assert not gamescan._e_lixo("Palworld")
