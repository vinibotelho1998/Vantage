"""Favoritos da aba Sensores: fixar sensor no topo sem perder o resto da lista.

A arvore do LibreHardwareMonitor tem centenas de linhas e muda de tamanho a cada
ciclo: sensor entra quando a peca acorda, some quando ela desliga, e o filtro
corta o meio. Tudo aqui gira em volta disso: a marca tem que sobreviver ao
fechamento do app, tem que ser presa a um sensor (nao a uma posicao de linha), e
o favorito de um hardware que nao esta' ligado agora nao pode virar linha morta
nem cabecalho orfao no topo da tela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage import theme  # noqa: E402
from vantage.config import Settings  # noqa: E402
from vantage.sensors.lhm import UNITS, LhmReader, SensorNode  # noqa: E402
from vantage.ui.views import sensors  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch, tmp_path):
    """Cada teste grava no proprio diretorio.

    Favoritar salva o settings de verdade; sem isolar, esses testes escreveriam
    por cima do settings.json compartilhado do conftest e mudariam o resultado
    de qualquer outro teste que o leia.
    """
    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path))

CPU = "AMD Ryzen 7 9800X3D"
GPU = "AMD Radeon RX 9070 XT"


def _node(hardware: str, kind: str, name: str, value: float = 50.0) -> SensorNode:
    """Um no' igual ao que lhm._collect_tree monta (mesma forma de chave)."""
    return SensorNode(key=f"{hardware}/{kind}/{name}", hardware=hardware,
                      hw_type="Cpu", name=name, kind=kind,
                      unit=UNITS.get(kind, ""), value=value)


def _arvore() -> list[SensorNode]:
    return [
        _node(CPU, "Temperature", "Core (Tctl/Tdie)", 62.0),
        _node(CPU, "Load", "CPU Total", 11.0),
        _node(GPU, "Temperature", "GPU Core", 48.0),
        _node(GPU, "Fan", "GPU Fan", 900.0),
    ]


class _Lhm:
    error = ""

    def __init__(self, nodes):
        self.nodes = list(nodes)

    def tree(self):
        return list(self.nodes)

    def start(self):
        pass


class _App:
    """So' a superficie que a aba de sensores usa do controlador."""

    def __init__(self, nodes, cfg=None):
        self.settings = cfg or Settings()
        self.lhm = _Lhm(nodes)
        self.stats: dict = {}
        self.salvou = 0

    def clear_stats(self):
        self.stats = {}

    def save_settings(self):
        # Espelha app.py: a view pede, o controlador grava no disco.
        self.salvou += 1
        self.settings.save()

    def notify(self, *_a):
        pass


def _tela(nodes=None, cfg=None):
    view = sensors.SensorsView(_App(nodes if nodes is not None else _arvore(), cfg))
    view.on_system({})
    return view


def _estrutura(view) -> list[tuple[str, int]]:
    """(titulo da secao, quantas linhas de sensor embaixo dela), de cima a baixo."""
    saida: list[list] = []
    for row in range(view.table.rowCount()):
        if view._chave_da_linha(row):
            if saida:
                saida[-1][1] += 1
        else:
            saida.append([view.table.item(row, sensors._COL_NAME).text(), 0])
    return [(titulo, n) for titulo, n in saida]


def _linha_de(view, key: str) -> int | None:
    for row in range(view.table.rowCount()):
        if view._chave_da_linha(row) == key:
            return row
    return None


def _favoritar(view, key: str) -> None:
    """Clica na estrela da primeira linha que mostra essa chave."""
    row = _linha_de(view, key)
    assert row is not None, f"{key} nao esta' na tabela"
    view._clique(row, sensors._COL_STAR)


# ── persistencia ──────────────────────────────────────────────────────────────
def test_favorito_sobrevive_a_ida_e_volta_do_disco(tmp_path):
    """Escolha que evapora ao fechar o app faz ninguem usar o recurso duas vezes."""
    view = _tela()
    alvo = f"{CPU}/Temperature/Core (Tctl/Tdie)"

    _favoritar(view, alvo)

    assert view.app.salvou == 1
    assert (tmp_path / "settings.json").exists()
    assert Settings.load().sensor_favorites == [alvo]


def test_desmarcar_tira_da_secao_e_do_settings():
    """Estrela que so' liga e nunca desliga deixa o topo entulhado para sempre."""
    view = _tela()
    alvo = f"{GPU}/Fan/GPU Fan"
    _favoritar(view, alvo)
    assert _estrutura(view)[0] == (sensors._TITULO_FAVORITOS, 1)

    _favoritar(view, alvo)   # a primeira linha com a chave agora e' a da secao

    assert view.cfg.sensor_favorites == []
    assert sensors._TITULO_FAVORITOS not in [t for t, _ in _estrutura(view)]


def test_badge_conta_os_favoritos_no_ato_do_clique():
    """Barra dizendo so' '4 sensores' com a secao ja' desenhada e' contradicao.

    O contador so' era refeito no tick do coletor; ate' 2 s de atraso no
    intervalo mais lento, tempo de sobra para a pessoa achar que nao pegou.
    """
    view = _tela()
    assert "favoritos" not in view.count_badge.text()

    _favoritar(view, f"{GPU}/Fan/GPU Fan")

    assert "1 favoritos" in view.count_badge.text()


def test_clique_de_verdade_na_estrela_marca_o_sensor():
    """Prova a ligacao do sinal: a tabela e' NoSelection/NoFocus e ainda assim clica."""
    view = _tela()
    view.resize(1200, 700)
    view.show()
    alvo = f"{CPU}/Load/CPU Total"
    row = _linha_de(view, alvo)
    celula = view.table.item(row, sensors._COL_STAR)

    QTest.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.table.visualItemRect(celula).center())

    assert view.cfg.sensor_favorites == [alvo]


# ── chave estavel ─────────────────────────────────────────────────────────────
class _SensorFalso:
    def __init__(self, name, kind, value):
        self.Name, self.SensorType, self.Value = name, kind, value


class _HardwareFalso:
    HardwareType = "Cpu"
    SubHardware: list = []

    def __init__(self, name, sensores):
        self.Name, self.Sensors = name, sensores


def test_chave_do_sensor_nao_muda_quando_a_arvore_reordena():
    """Chave por posicao marcaria o vizinho na abertura seguinte.

    O LHM nao promete ordem nem quantidade entre execucoes: um sensor que
    aparece antes empurra todos os outros para baixo. A chave e' o texto
    hardware/tipo/nome justamente para nao depender disso.
    """
    leitor = LhmReader()
    a = _SensorFalso("Core (Tctl/Tdie)", "Temperature", 62.0)
    b = _SensorFalso("CPU Total", "Load", 11.0)
    c = _SensorFalso("Package", "Power", 88.0)

    primeira: list = []
    leitor._collect_tree(_HardwareFalso(CPU, [a, b, c]), primeira)
    segunda: list = []
    leitor._collect_tree(_HardwareFalso(CPU, [c, b, a]), segunda)

    por_nome = {n.name: n.key for n in primeira}
    assert por_nome["CPU Total"] == f"{CPU}/Load/CPU Total"
    assert {n.name: n.key for n in segunda} == por_nome
    # e a posicao mudou de verdade, senao o teste nao provaria nada
    assert [n.name for n in primeira] != [n.name for n in segunda]


def test_estrela_le_a_chave_da_celula_e_nao_o_indice():
    """A lista sobe de posicao sozinha; a linha N de agora nao e' a de antes.

    Guardar "linha 4 = GPU Core" numa lista paralela marcaria o vizinho assim
    que um sensor acima sumisse. A chave viaja dentro da celula, entao ela
    sempre bate com o que esta' desenhado ali.
    """
    view = _tela()
    alvo = f"{GPU}/Temperature/GPU Core"
    linha_antes = _linha_de(view, alvo)

    # um sensor la' de cima sumiu: todo mundo abaixo dele subiu uma linha
    view.app.lhm.nodes = [n for n in _arvore() if n.name != "Core (Tctl/Tdie)"]
    view.on_system({})
    assert _linha_de(view, alvo) == linha_antes - 1

    view._clique(linha_antes, sensors._COL_STAR)

    # marcou o que esta' escrito nessa linha agora, nao o que estava antes
    assert view.cfg.sensor_favorites == [f"{GPU}/Fan/GPU Fan"]
    assert _linha_de(view, alvo) != _linha_de(view, f"{GPU}/Fan/GPU Fan")


def test_clique_no_cabecalho_de_grupo_nao_favorita_nada():
    """Cabecalho nao tem chave; favoritar 'Processador' so' sujaria o settings."""
    view = _tela()

    view._clique(0, sensors._COL_STAR)

    assert view.cfg.sensor_favorites == []


def test_clique_fora_da_coluna_da_estrela_nao_marca():
    """A tabela inteira viraria um alvo de favoritar por acidente."""
    view = _tela()
    row = _linha_de(view, f"{CPU}/Load/CPU Total")

    view._clique(row, sensors._COL_NAME)

    assert view.cfg.sensor_favorites == []


# ── sensor que sumiu ──────────────────────────────────────────────────────────
def test_favorito_de_sensor_que_sumiu_nao_vira_linha_fantasma():
    """Placa desconectada deixaria uma linha de travessao eterno no topo."""
    cfg = Settings()
    cfg.sensor_favorites = [f"{GPU}/Fan/GPU Fan", "Placa fantasma/Temperature/Sumida"]
    view = _tela(cfg=cfg)

    assert _estrutura(view)[0] == (sensors._TITULO_FAVORITOS, 1)
    assert _linha_de(view, "Placa fantasma/Temperature/Sumida") is None
    # a chave continua guardada: o favorito volta sozinho quando a peca voltar
    assert "Placa fantasma/Temperature/Sumida" in view.cfg.sensor_favorites


def test_secao_some_inteira_quando_nenhum_favorito_esta_presente():
    """Cabecalho 'Favoritos' sozinho parece defeito de renderizacao."""
    cfg = Settings()
    cfg.sensor_favorites = ["Sumiu/Load/Nada", "Sumiu tambem/Fan/Nada"]
    view = _tela(cfg=cfg)

    assert [t for t, _ in _estrutura(view)] == [CPU, GPU]


def test_favorito_volta_ao_topo_quando_o_hardware_reaparece():
    """Remarcar tudo depois de religar a maquina e' o atrito que mata o recurso."""
    cfg = Settings()
    cfg.sensor_favorites = [f"{GPU}/Fan/GPU Fan"]
    view = _tela(nodes=[n for n in _arvore() if n.hardware != GPU], cfg=cfg)
    assert [t for t, _ in _estrutura(view)] == [CPU]

    view.app.lhm.nodes = _arvore()
    view.on_system({})

    assert _estrutura(view)[0] == (sensors._TITULO_FAVORITOS, 1)


# ── a secao e' atalho, nao mudanca de endereco ────────────────────────────────
def test_favorito_continua_aparecendo_no_grupo_de_hardware():
    """Arrancar a linha do grupo deixaria um buraco silencioso na peca."""
    view = _tela()
    _favoritar(view, f"{CPU}/Temperature/Core (Tctl/Tdie)")

    assert _estrutura(view) == [(sensors._TITULO_FAVORITOS, 1), (CPU, 2), (GPU, 2)]


def test_valor_e_estatisticas_chegam_nas_duas_copias_da_linha():
    """Uma copia congelaria num numero velho e as duas se contradiriam na tela.

    Cobre tambem o deslocamento das colunas: a estrela empurrou atual/mín/méd/máx
    uma casa para a direita, e escrever no indice antigo poria o valor no rotulo.
    """
    view = _tela()
    alvo = f"{CPU}/Temperature/Core (Tctl/Tdie)"
    _favoritar(view, alvo)

    view.app.lhm.nodes = [_node(CPU, "Temperature", "Core (Tctl/Tdie)", 91.0)
                          if n.key == alvo else n for n in _arvore()]
    view.app.stats[alvo] = (40.0, 60.0, 91.0)
    view.on_system({})

    linhas = view._rows[alvo]
    assert len(linhas) == 2
    for row in linhas:
        celulas = [view.table.item(row, c).text()
                   for c in range(sensors._COL_NOW, view.table.columnCount())]
        assert celulas == ["91.0 °C", "40.0 °C", "60.0 °C", "91.0 °C"]
        assert view.table.item(row, sensors._COL_NAME).text().strip().endswith(
            "Core (Tctl/Tdie)")


def test_secao_de_favoritos_diz_de_qual_peca_e_o_sensor():
    """'GPU Core' fora do grupo nao diz nada: existe temperatura assim em tudo."""
    view = _tela()
    _favoritar(view, f"{GPU}/Temperature/GPU Core")

    texto = view.table.item(1, sensors._COL_NAME).text()
    assert GPU in texto and "GPU Core" in texto


def test_estrela_marcada_e_visivelmente_diferente_da_vazia():
    """Sem estado visivel, favoritar vira adivinhacao."""
    view = _tela()
    alvo = f"{CPU}/Load/CPU Total"
    _favoritar(view, alvo)
    outra = _linha_de(view, f"{GPU}/Fan/GPU Fan")

    marcada = view.table.item(_linha_de(view, alvo), sensors._COL_STAR)
    vazia = view.table.item(outra, sensors._COL_STAR)

    assert marcada.text() == sensors._ESTRELA_CHEIA
    assert vazia.text() == sensors._ESTRELA_VAZIA
    assert marcada.foreground().color().name().upper() == theme.WARN.upper()
    assert "favoritos" in marcada.toolTip().lower()


def test_filtro_corta_tambem_a_secao_de_favoritos():
    """Favorito que ignora o filtro faz o contador brigar com o que esta' na tela."""
    view = _tela()
    _favoritar(view, f"{GPU}/Fan/GPU Fan")
    view.filter.setText("temperature")
    view.on_system({})

    assert [t for t, _ in _estrutura(view)] == [CPU, GPU]


# ── lixo no arquivo de configuracao ───────────────────────────────────────────
def test_lixo_no_settings_vira_lista_vazia():
    """settings.json editado a mao nao pode derrubar o app na abertura."""
    for lixo in ("uma string", 42, None, {"a": 1}, [1, 2], [None], [""], ["   "]):
        assert Settings.from_dict({"sensor_favorites": lixo}).sensor_favorites == []


def test_favoritos_guardam_so_o_que_e_texto_util():
    s = Settings.from_dict({"sensor_favorites": ["cpu/Load/Total", 7, "", "gpu/Fan/1"]})
    assert s.sensor_favorites == ["cpu/Load/Total", "gpu/Fan/1"]


def test_chave_repetida_no_arquivo_entra_uma_vez_so():
    """Repetido viraria linha duplicada dentro da propria secao de favoritos."""
    s = Settings.from_dict({"sensor_favorites": ["a/Load/x", "a/Load/x", "b/Fan/y"]})
    assert s.sensor_favorites == ["a/Load/x", "b/Fan/y"]


def test_arquivo_absurdo_nao_vira_secao_de_mil_linhas():
    s = Settings.from_dict({"sensor_favorites": [f"h/Load/{i}" for i in range(5000)]})
    assert len(s.sensor_favorites) == 200


def test_sem_favoritos_e_estado_valido_e_nao_vira_padrao_cheio():
    """Diferente de dashboard_plots: lista vazia aqui e' escolha, nao arquivo estragado."""
    assert Settings().sensor_favorites == []
    c = Settings()
    c.sensor_favorites = []
    c.sanitize()
    assert c.sensor_favorites == []


def test_settings_sem_o_campo_nao_derruba_a_aba():
    """Um app de teste (ou settings de versao antiga) nao pode quebrar a tela."""
    class _CfgVelho:
        accent = "cyan"

    view = sensors.SensorsView(_App(_arvore(), _CfgVelho()))
    view.on_system({})

    assert [t for t, _ in _estrutura(view)] == [CPU, GPU]
