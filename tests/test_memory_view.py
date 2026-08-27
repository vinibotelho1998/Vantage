"""A tela de Memória & Disco mostrando saúde: buraco de dado nao pode virar numero.

O card de saude e' alimentado por duas fontes que quase sempre respondem pela
metade: o LHM nao le' disco atras de adaptador USB, e o Storage Spaces so'
entrega os contadores de confiabilidade com elevacao. O que esta' em jogo aqui e'
a linha que sobra: ela precisa sumir, e nao virar "0" nem "—" enfileirado.

Os outros dois testes cobrem o caminho de erro do benchmark (a recusa tem de
chegar escrita na tela, nao num log) e o encerramento (fechar o app precisa
cancelar o teste, senao fica thread escrevendo e arquivo de 1 GB na unidade).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbxstats.config import Settings  # noqa: E402
from dbxstats.core.series import Accumulator, History  # noqa: E402
from dbxstats.sensors import diskbench  # noqa: E402
from dbxstats.sensors.lhm import SensorNode  # noqa: E402
from dbxstats.ui.views import memory  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Lhm:
    def __init__(self, nodes=()):
        self._nodes = list(nodes)

    def tree(self):
        return list(self._nodes)


class _App:
    """So' a superficie que a tela de memoria usa do controlador."""

    def __init__(self, nodes=()):
        self.settings = Settings()
        self.stats = Accumulator()
        self.history = History(60)
        self.lhm = _Lhm(nodes)


def _no(kind: str, nome: str, valor: float) -> SensorNode:
    return SensorNode(key=f"NVMe/{kind}/{nome}", hardware="Samsung SSD 990 PRO",
                      hw_type="Storage", name=nome, kind=kind, unit="", value=valor)


def _view(nodes=()) -> memory.MemoryView:
    return memory.MemoryView(_App(nodes))


def _texto(coluna, chave: str) -> str:
    return coluna["rows"].row(chave)._value.text()


def test_maquina_sem_smart_avisa_em_vez_de_mostrar_card_vazio():
    """Sem nenhuma leitura, um card de travessoes parece app quebrado."""
    v = _view()
    v._sync_saude()
    assert v.saude_aviso.isVisibleTo(v)
    assert not [c for c in v._saude_widgets if c["root"].isVisibleTo(v)]


def test_linha_sem_leitura_some_e_a_que_existe_fica():
    """O disco reporta vida util e mais nada; as outras seis linhas saem."""
    v = _view([_no("Level", "Percentage Used", 4.0)])
    v._sync_saude()
    col = v._saude_widgets[0]
    assert col["rows"].row("life").isVisibleTo(v)
    for ausente in ("written", "read", "hours", "temp", "errors", "spare", "cycles"):
        assert not col["rows"].row(ausente).isVisibleTo(v), ausente


def test_o_que_o_disco_reporta_chega_formatado_na_tela():
    v = _view([
        _no("Level", "Percentage Used", 4.0),
        _no("Data", "Data Written", 2048.0),
        _no("Temperature", "Composite Temperature", 44.0),
        _no("Factor", "Power On Hours", 4800.0),
    ])
    v._sync_saude()
    col = v._saude_widgets[0]
    assert _texto(col, "life") == "96%"
    assert _texto(col, "written") == "2.00 TB"
    assert _texto(col, "temp").startswith("44 °C")
    assert _texto(col, "hours") == "4800 h  (200 dias)"


def test_disco_some_da_lista_quando_o_sensor_para_de_responder():
    """A coluna sobra reaproveitada nao pode continuar mostrando o dado antigo."""
    v = _view([_no("Level", "Percentage Used", 4.0)])
    v._sync_saude()
    assert v._saude_widgets[0]["root"].isVisibleTo(v)
    v.app.lhm = _Lhm([])
    v._sync_saude()
    assert not v._saude_widgets[0]["root"].isVisibleTo(v)


def test_benchmark_recusado_explica_o_motivo_na_propria_tela():
    """Recusa que so' vai para o log deixa o usuario achando que o botao quebrou."""
    v = _view()
    v._bench.iniciar = lambda *_a, **_k: (False, "Espaço livre insuficiente.")
    v._iniciar_bench("Z:\\")
    assert "insuficiente" in v.bench_aviso.text()
    assert not v.btn_cancelar.isVisibleTo(v)


def test_resultado_do_teste_chega_mesmo_com_a_aba_no_fundo():
    """O teste dura segundos; trocar de aba no meio nao pode engolir o resultado.

    Perguntar `isVisible()` ao botao parecia equivalente a guardar o estado, mas
    uma tela que nao esta' na frente responde False: o resultado nunca seria
    desenhado e o botao ficaria preso em "Testando…" para sempre.
    """
    v = _view()
    v._bench.iniciar = lambda *_a, **_k: (True, "")
    v._iniciar_bench("D:\\")
    v.setVisible(False)
    v._bench.estado = lambda: {
        "ativo": False, "unidade": "D:\\", "fase": "concluído", "progresso": 1.0,
        "erro": "", "resultado": diskbench.Resultado(unidade="D:\\", leitura_seq=2.8e9)}
    v._tick_tarefas()
    assert "GB/s" in v.bench_rows.row("rseq")._value.text()
    assert v.btn_testar.text() == "Testar unidade"
    assert not v._timer.isActive()


def test_fechar_o_app_cancela_o_teste_em_andamento():
    """Sem isso sobra thread escrevendo e um arquivo de 1 GB na unidade."""
    v = _view()
    pedidos = []
    v._bench.cancelar = lambda esperar=3.0: pedidos.append(esperar)
    v._encerrar()
    assert pedidos and not v._timer.isActive()


# ── opcoes do teste de disco ─────────────────────────────────────────────────
def test_o_tamanho_escolhido_chega_ao_motor():
    """A opcao so' vale se o motor receber: e' ela que dimensiona o arquivo e a
    checagem de espaco livre. Escolher 4 GiB e testar 1 GiB seria pior que nada."""
    v = _view()
    v.cfg.diskbench_size_mib = 4096
    v._sync_opcoes_bench()
    pedidos = []
    v._bench.iniciar = lambda mount, opcoes=None: (pedidos.append((mount, opcoes)), (True, ""))[1]
    v._iniciar_bench("D:\\")
    mount, opcoes = pedidos[0]
    assert mount == "D:\\"
    assert opcoes.tamanho == 4096 * diskbench.MIB


def test_a_unidade_escolhida_manda_no_botao_de_testar():
    """Antes o botao abria um menu; agora ele roda na unidade que esta' na tela."""
    v = _view()
    v.on_system({"disks": [{"mount": "C:\\"}, {"mount": "D:\\"}]})
    v._set_unidade("D:\\")
    assert v.cfg.diskbench_drive == "D:\\"
    pedidos = []
    v._bench.iniciar = lambda mount, opcoes=None: (pedidos.append(mount), (True, ""))[1]
    v._iniciar_bench()
    assert pedidos == ["D:\\"]


def test_desmarcar_a_ultima_fase_e_ignorado():
    """Teste sem fase nenhuma criaria o arquivo na unidade para nao medir nada."""
    v = _view()
    v.cfg.diskbench_phases = ["rseq"]
    v._sync_opcoes_bench()
    v._alternar_fase("rseq")
    assert v.cfg.diskbench_phases == ["rseq"]


def test_fase_desmarcada_nao_deixa_travessao_no_resultado():
    """Travessao numa fase que ninguem pediu se le' como 'o teste falhou aqui'."""
    v = _view()
    v._bench.iniciar = lambda *_a, **_k: (True, "")
    v._iniciar_bench("D:\\")
    v._bench.estado = lambda: {
        "ativo": False, "unidade": "D:\\", "fase": "concluído", "progresso": 1.0,
        "erro": "", "resultado": diskbench.Resultado(unidade="D:\\", leitura_seq=2.8e9,
                                                     fases=("rseq",))}
    v._tick_tarefas()
    assert v.bench_rows.row("rseq").isVisibleTo(v)
    for ausente in ("wseq", "ralea", "walea", "iops"):
        assert not v.bench_rows.row(ausente).isVisibleTo(v), ausente


def test_iops_de_uma_fase_so_diz_qual_fase_foi_medida():
    """"9k / —" não diz se o que sobrou na linha é leitura ou escrita."""
    v = _view()
    v._mostrar_bench({"erro": "", "resultado": diskbench.Resultado(
        unidade="D:\\", leitura_alea=4e7, iops_leitura=9000.0, fases=("ralea",))})
    linha = v.bench_rows.row("iops")
    assert "leitura" in linha._label.text()
    assert "/" not in linha._value.text()


def test_o_resumo_mostra_o_espaco_que_o_teste_vai_exigir():
    """E' o motivo mais comum de recusa; ver a conta antes evita a surpresa."""
    v = _view()
    v.cfg.diskbench_size_mib = 4096
    v._sync_opcoes_bench()
    assert "4 GiB" in v.bench_resumo.text()
    assert "livres" in v.bench_resumo.text()


def test_so_leitura_marcada_avisa_que_o_arquivo_e_gravado_antes():
    """O usuario precisa saber que 'só leitura' ainda grava: o disco vai ser escrito."""
    v = _view()
    v.cfg.diskbench_phases = ["rseq"]
    v._sync_opcoes_bench()
    assert "gravado antes" in v.bench_resumo.text()
