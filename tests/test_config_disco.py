"""Settings vindo do disco: perfis de tela, atalhos, botoes e o arquivo em si.

O settings.json guarda a biblioteca de jogos e os perfis de tela, que sao
trabalho do usuario. Um valor torto la dentro nao pode nem derrubar o app nem
virar comando torto na hora de abrir um jogo ou mexer nas telas.
"""
import json
import os

os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage import paths  # noqa: E402
from vantage.config import Settings  # noqa: E402


def _tela(**extra):
    base = {"device": r"\\.\DISPLAY1", "active": True}
    base.update(extra)
    return base


def _perfil(nome="TV", entradas=None, **extra):
    base = {"name": nome, "entries": entradas if entradas is not None else [_tela()]}
    base.update(extra)
    return base


# ── perfis de tela ───────────────────────────────────────────────────────────
def test_perfil_sem_tela_ligada_e_descartado():
    """Aplicar um perfil com tudo desligado deixaria a maquina sem imagem."""
    s = Settings.from_dict({"display_profiles": [
        _perfil(entradas=[_tela(active=False), _tela(device=r"\\.\DISPLAY2", active=False)]),
        _perfil(nome="Mesa"),
    ]})
    assert [p["name"] for p in s.display_profiles] == ["Mesa"]


def test_perfil_sem_nome_ou_que_nao_e_dicionario_e_descartado():
    s = Settings.from_dict({"display_profiles": [_perfil(nome="   "), "TV", None, 3]})
    assert s.display_profiles == []


def test_tela_sem_dispositivo_nao_entra_no_perfil():
    s = Settings.from_dict({"display_profiles": [
        _perfil(entradas=[_tela(), {"active": True}, "lixo"])]})
    assert len(s.display_profiles[0]["entries"]) == 1


def test_modo_da_tela_estragado_vira_nenhum_e_posicao_vira_origem():
    """Modo torto nao pode chegar a CCD API; sem modo, a tela fica no que esta."""
    s = Settings.from_dict({"display_profiles": [_perfil(entradas=[
        _tela(mode=["3840", 2160, "abc"], position=["x", 0]),
        _tela(device="B", mode=[1920, 1080], position=[1, 2, 3]),
        _tela(device="C", mode=["2560", "1440", "144"], position=["-1920", "0"]),
    ])]})
    a, b, c = s.display_profiles[0]["entries"]
    assert a["mode"] is None and a["position"] == [0, 0]
    assert b["mode"] is None and b["position"] == [0, 0]
    assert c["mode"] == [2560, 1440, 144] and c["position"] == [-1920, 0]


def test_nome_do_perfil_e_cortado_em_40():
    s = Settings.from_dict({"display_profiles": [_perfil(nome="x" * 100)]})
    assert s.display_profiles[0]["name"] == "x" * 40


def test_perfil_padrao_que_sumiu_deixa_de_ser_padrao():
    """Perfil padrao apontando para nome inexistente seria aplicado no vazio."""
    s = Settings.from_dict({"display_profiles": [_perfil(nome="Mesa")],
                            "display_default_profile": "TV"})
    assert s.display_default_profile == ""
    s = Settings.from_dict({"display_profiles": [_perfil(nome="TV")],
                            "display_default_profile": "TV"})
    assert s.display_default_profile == "TV"


def test_perfil_com_nome_nulo_nao_vira_perfil_chamado_none():
    s = Settings.from_dict({"display_profiles": [_perfil(nome=None)]})
    assert s.display_profiles == []


def test_atalho_de_teclado_nulo_do_perfil_fica_vazio():
    s = Settings.from_dict({"display_profiles": [_perfil(hotkey=None)]})
    assert s.display_profiles[0]["hotkey"] == ""


# ── atalhos de jogo ──────────────────────────────────────────────────────────
def test_atalho_com_caminho_nulo_e_descartado():
    """`null` no caminho virava um atalho para um executavel chamado 'None'."""
    s = Settings.from_dict({"launch_items": [{"name": "Forza", "path": None}]})
    assert s.launch_items == []


def test_atalho_com_campos_nulos_nao_passa_none_para_o_jogo():
    """Argumento 'None' iria de verdade na linha de comando do jogo."""
    s = Settings.from_dict({"launch_items": [{
        "path": r"C:\Games\forza.exe", "name": None, "args": None,
        "target": None, "image": None}]})
    item = s.launch_items[0]
    assert item["name"] == "forza"
    assert item["args"] == ""
    assert item["target"] == ""
    assert item["image"] == ""


def test_atalho_com_prioridade_inexistente_volta_ao_normal():
    s = Settings.from_dict({"launch_items": [
        {"path": "a.exe", "priority": "turbo"},
        {"path": "b.exe", "priority": " high "},
    ]})
    assert s.launch_items[0]["priority"] == ""
    assert s.launch_items[1]["priority"] == "high"


def test_atalho_guarda_alvo_de_perfil_e_bench_ligado_por_padrao():
    s = Settings.from_dict({"launch_items": [{"path": "a.exe", "target": "profile:TV"}]})
    item = s.launch_items[0]
    assert item["target"] == "profile:TV"
    assert item["bench"] is True and item["voltar_bp"] is False


# ── botoes do controle ───────────────────────────────────────────────────────
def test_botao_ou_acao_desconhecidos_sao_descartados():
    s = Settings.from_dict({"gamepad_bindings": {
        "A": "click_right", "Z": "click_left", "B": "voar", "X": None}})
    assert s.gamepad_bindings == {"A": "click_right"}


def test_botoes_que_nao_sao_dicionario_viram_vazio():
    assert Settings.from_dict({"gamepad_bindings": ["A", "B"]}).gamepad_bindings == {}


# ── listas com lixo dentro ───────────────────────────────────────────────────
def test_lista_de_metricas_com_item_nao_texto_nao_joga_o_arquivo_fora():
    """JSON valido com um item torto nao pode ir para a quarentena de ilegivel.

    Um `[]` dentro da lista de metricas derrubava o from_dict, o load tratava o
    arquivo inteiro como ilegivel e o app subia com os padroes, sem jogos e sem
    perfis de tela.
    """
    s = Settings.from_dict({"overlay_metrics": ["fps", ["cpu"], {"x": 1}, "cpu"],
                            "dash_cards": [{}, "cpu", ["gpu"]],
                            "launch_items": [{"path": "a.exe"}]})
    assert s.overlay_metrics == ["fps", "cpu"]
    assert s.dash_cards == ["cpu"]
    assert len(s.launch_items) == 1


def test_campos_de_escolha_com_tipo_errado_voltam_ao_padrao():
    s = Settings.from_dict({"accent": ["x"], "start_view": {}, "overlay_corner": [1]})
    assert (s.accent, s.start_view, s.overlay_corner) == ("cyan", "dashboard", "top-left")


def test_favoritos_repetidos_e_vazios_somem_na_ordem():
    s = Settings.from_dict({"sensor_favorites": [" a ", "b", "a", "", 3, None, "b"]})
    assert s.sensor_favorites == ["a", "b"]


def test_favoritos_tem_teto():
    s = Settings.from_dict({"sensor_favorites": [f"s{i}" for i in range(500)]})
    assert len(s.sensor_favorites) == 200


def test_alvo_do_big_picture_so_aceita_tela():
    assert Settings.from_dict({"bigpicture_target": "screen:TV"}).bigpicture_target == "screen:TV"
    assert Settings.from_dict({"bigpicture_target": "profile:TV"}).bigpicture_target == ""
    assert Settings.from_dict({"bigpicture_target": None}).bigpicture_target == ""


# ── o arquivo ────────────────────────────────────────────────────────────────
def test_salvar_e_carregar_devolve_o_mesmo(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    c = Settings()
    c.accent = "green"
    c.launch_items = [{"path": r"C:\Games\forza.exe"}]
    c.display_profiles = [_perfil()]
    c.sanitize()
    c.save()
    assert Settings.load().as_dict() == c.as_dict()


def test_salvar_nao_deixa_temporario_e_grava_texto_acentuado(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    c = Settings()
    c.launch_items = [{"path": "a.exe", "name": "Coração"}]
    c.sanitize()
    c.save()
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["settings.json"]
    assert "Coração" in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_sem_arquivo_nenhum_nasce_com_padroes(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "legacy_config_file", lambda: tmp_path / "nao-existe.json")
    assert Settings.load().as_dict() == Settings().as_dict()


def test_arquivo_da_pasta_antiga_e_migrado_para_a_nova(tmp_path, monkeypatch):
    """Quem veio da versao que salvava ao lado do executavel nao perde nada."""
    dados = tmp_path / "dados"
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(dados))
    antigo = tmp_path / "antigo.json"
    antigo.write_text(json.dumps({"accent": "purple"}), encoding="utf-8")
    monkeypatch.setattr(paths, "legacy_config_file", lambda: antigo)

    assert Settings.load().accent == "purple"
    gravado = json.loads((dados / "settings.json").read_text(encoding="utf-8"))
    assert gravado["accent"] == "purple"


def test_arquivo_novo_tem_precedencia_sobre_o_antigo(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"accent": "green"}), encoding="utf-8")
    antigo = tmp_path / "antigo.json"
    antigo.write_text(json.dumps({"accent": "purple"}), encoding="utf-8")
    monkeypatch.setattr(paths, "legacy_config_file", lambda: antigo)
    assert Settings.load().accent == "green"


def test_arquivo_que_e_lista_vai_para_a_quarentena(tmp_path, monkeypatch):
    """JSON valido que nao e' objeto nao tem como virar configuracao."""
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "legacy_config_file", lambda: tmp_path / "nao-existe.json")
    (tmp_path / "settings.json").write_text("[1, 2]", encoding="utf-8")
    assert Settings.load().as_dict() == Settings().as_dict()
    assert list(tmp_path.glob("settings.json.ilegivel-*"))


def test_falha_ao_salvar_nao_derruba(tmp_path, monkeypatch):
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json.tmp").mkdir()
    Settings().save()
    assert not (tmp_path / "settings.json").exists()
