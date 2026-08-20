"""As medidas novas atravessando ate' as telas grandes, e sumindo quando faltam.

O risco desta camada nao e' quebrar — e' mostrar. Uma linha com travessao fixo
(tensao numa placa que nao publica rail, temperatura de pente sem elevacao,
memoria do jogo sem jogo, temperatura de VRAM numa maquina AMD sem NVML) parece
defeito do app, e o usuario nao tem como saber que o sensor e' que nao existe.

O ultimo teste guarda a migracao: sem ela, quem ja' tem settings salvo estreia o
redesenho sem nenhuma das metricas novas — que e' justamente o dono da maquina.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbxstats import theme  # noqa: E402
from dbxstats.config import OVERLAY_DEFAULT, Settings  # noqa: E402
from dbxstats.core.series import Accumulator, History  # noqa: E402
from dbxstats.sensors.collector import Collector  # noqa: E402
from dbxstats.ui import components  # noqa: E402
from dbxstats.ui.views import cpu as cpu_view  # noqa: E402
from dbxstats.ui.views import dashboard as dash_view  # noqa: E402
from dbxstats.ui.views import gpu as gpu_view  # noqa: E402
from dbxstats.ui.views import memory as mem_view  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Procs:
    def totals(self):
        return 0, 0

    def snapshot(self):
        return []


class _Lhm:
    def tree(self):
        return []


class _App:
    def __init__(self) -> None:
        self.settings = Settings()
        self.stats = Accumulator()
        self.history = History(60)
        self.procs = _Procs()
        self.lhm = _Lhm()

    def active_stream(self):
        return None

    def fps_hint(self):
        return "nenhum jogo"


def _dados(**mudancas) -> dict:
    d = {
        "lhm_ok": True, "static": {"cpu_name": "Ryzen 7 9800X3D"},
        "cpu_pct": 38.0, "cpu_mhz": 5200, "cpu_temp": 82.0, "cpu_watts": 71.0,
        "cpu_volts": 1.118, "cpu_volts_src": "rail", "cpu_volts_rail": "Voltage #1",
        "cpu_vid": 1.05,
        "ram_used": 27.9, "ram_total": 31.6, "ram_avail": 3.7, "ram_pct": 88.0,
        "ram_freq": 6000, "ram_temp": 47.0,
        "ram_modules": [{"slot": "DIMM #1", "temp": 47.0, "high": 55.0,
                         "critical": 85.0, "model": "A-DATA (#1)"},
                        {"slot": "DIMM #3", "temp": 45.5, "high": 55.0,
                         "critical": 85.0, "model": "A-DATA (#3)"}],
        "game_pid": 4242, "game_name": "jogo.exe",
        "game_ram_private": 14950.0, "game_ram_wset": 12390.0,
        "swap_used": 2.0, "swap_total": 8.0, "swap_pct": 25.0,
        "disk_used": 780.0, "disk_total": 1863.0, "disk_pct": 42.0,
        "disk_r": 0.0, "disk_w": 0.0, "disks": [],
        "net_dl": 0.0, "net_ul": 0.0, "ping_ms": 23.0,
        "gpu": {"usage": 99.0, "freq": 2440, "volts": 0.928, "watts": 289.0,
                "temp": 81, "temp_hotspot": 104, "temp_vram": 101, "mem_ctrl": 94.0,
                "vram_used": 15810, "vram_total": 16384, "vram_pct": 96.5,
                "static": {}, "throttle": []},
    }
    d.update(mudancas)
    return d


def _linha(lista, chave):
    return lista.row(chave)


# ── painel ───────────────────────────────────────────────────────────────────
def test_painel_mostra_tensao_e_temperatura_de_memoria():
    v = dash_view.DashboardView(_App())
    v.on_system(_dados())
    assert _linha(v.cpu_rows, "volts")._value.text() == "1.118 V"
    assert _linha(v.gpu_rows, "volts")._value.text() == "0.928 V"
    assert not _linha(v.gpu_rows, "vram_temp").isHidden()
    assert _linha(v.ram_rows, "temp")._value.text() == "47 °C"


def test_painel_apaga_a_linha_quando_o_sensor_nao_existe():
    """Nesta maquina AMD nao ha' NVML: temperatura de VRAM simplesmente nao vem."""
    d = _dados(cpu_volts=None, ram_temp=None)
    d["gpu"] = dict(d["gpu"], volts=None, temp_vram=None)
    d.pop("game_ram_private")
    v = dash_view.DashboardView(_App())
    v.on_system(d)
    for lista, chave in ((v.cpu_rows, "volts"), (v.gpu_rows, "volts"),
                         (v.gpu_rows, "vram_temp"), (v.ram_rows, "temp"),
                         (v.ram_rows, "jogo")):
        assert _linha(lista, chave).isHidden(), chave


def test_linha_do_jogo_leva_o_nome_do_processo():
    """"Jogo em foco: 14,6 GB" nao diz de qual jogo quando ha' launcher junto."""
    v = dash_view.DashboardView(_App())
    v.on_system(_dados())
    assert _linha(v.ram_rows, "jogo")._label.text() == "jogo.exe"


# ── CPU ──────────────────────────────────────────────────────────────────────
def test_tela_da_cpu_separa_vcore_do_vid():
    """Por muito tempo esta tela mostrou o VID como se fosse a tensao entregue."""
    v = cpu_view.CpuView(_App())
    v.on_system(_dados())
    assert _linha(v.info, "volts")._value.text() == "1.118 V"
    assert _linha(v.info, "vid")._value.text() == "1.050 V"
    assert "rail" in _linha(v.info, "volts")._stat.text()


def test_vid_travado_sem_elevacao_nao_aparece():
    """Sem admin o VID crava em 1,550 V — topo da codificacao, nao medida."""
    v = cpu_view.CpuView(_App())
    v.on_system(_dados(cpu_vid=1.55, cpu_volts=None))
    assert _linha(v.info, "vid").isHidden()
    assert _linha(v.info, "volts").isHidden()


# ── GPU ──────────────────────────────────────────────────────────────────────
def test_tela_da_gpu_mostra_tensao_e_esconde_temp_de_vram_ausente():
    v = gpu_view.GpuView(_App())
    v.on_system(_dados())
    assert _linha(v.info, "volts")._value.text() == "0.928 V"
    assert not _linha(v.vram_rows, "temp").isHidden()

    d = _dados()
    d["gpu"] = dict(d["gpu"], volts=None, temp_vram=None)
    v.on_system(d)
    assert _linha(v.info, "volts").isHidden()
    assert _linha(v.vram_rows, "temp").isHidden()


# ── memoria ──────────────────────────────────────────────────────────────────
def test_tela_de_memoria_lista_um_pente_por_linha_com_o_limite_de_fabrica():
    v = mem_view.MemoryView(_App())
    v.on_system(_dados())
    assert _linha(v.mod_rows, "m0")._label.text() == "DIMM #1"
    assert _linha(v.mod_rows, "m1")._value.text() == "46 °C"
    assert "55" in _linha(v.mod_rows, "m1")._stat.text()
    assert _linha(v.mod_rows, "m2").isHidden()


def test_tela_de_memoria_sem_sensor_de_pente_nao_deixa_linha_orfa():
    v = mem_view.MemoryView(_App())
    v.on_system(_dados(ram_temp=None, ram_modules=None))
    assert _linha(v.mod_rows, "m0").isHidden()
    assert _linha(v.ram_rows, "temp").isHidden()
    assert "temp" in v.kpi._ocultos


# ── faixa de cor ─────────────────────────────────────────────────────────────
def test_pente_usa_a_faixa_do_spd_e_nao_a_faixa_geral():
    """47 graus e' verde num processador e ja' e' amarelo num pente de DDR5.

    A escala geral do app (65/82/92) pintaria de verde um modulo a 60 graus, que
    o proprio fabricante marca como acima do limite.
    """
    quente = {"ram_temp": 60.0,
              "ram_modules": [{"temp": 60.0, "high": 55.0, "critical": 85.0}]}
    assert components.dimm_color(quente) != theme.OK
    assert components.dimm_color({"ram_temp": 40.0, "ram_modules": []}) == theme.OK


# ── coletor ──────────────────────────────────────────────────────────────────
class _LhmTemps:
    ready = True

    def read(self) -> dict:
        return {"cpu_temp_cores": 69.0, "cpu_temp_package": 82.0, "cpu_temp": 82.0}


class _GpuMudo:
    nvml_ok = False
    static: dict = {}

    def read_nvml(self):
        return None

    def watts_smi(self):
        return None

    def watts_estimate(self, *_):
        return None

    def vram(self):
        return None


class _PingMudo:
    def read(self) -> dict:
        return {}


def test_as_duas_temperaturas_da_cpu_chegam_no_snapshot():
    """O overlay poe media e pico lado a lado; sem estas chaves ele so' tem uma.

    Elas eram lidas do LHM e nunca copiadas para o dict do coletor — a celula
    dupla existia no codigo e nao aparecia em maquina nenhuma.
    """
    c = Collector(_LhmTemps(), _GpuMudo(), _PingMudo())
    c._gpu_wmi = {}
    c._ram_freq = 0
    d = c._collect()
    assert d["cpu_temp_cores"] == 69.0
    assert d["cpu_temp_package"] == 82.0


# ── migracao ─────────────────────────────────────────────────────────────────
def test_metrica_nova_nasce_ligada_para_quem_nunca_mexeu_na_lista():
    """`sanitize` so' filtra; sem migracao o redesenho estreia invisivel.

    Quem tem settings salvo carrega a lista da versao antiga, e nenhuma chave
    nova entraria nela — o overlay novo apareceria igual ao velho.
    """
    antigo = {"overlay_metrics": ["fps", "graph", "low1", "frametime", "cpu", "gpu",
                                  "ram", "vram", "ping", "watts", "clock"]}
    s = Settings.from_dict(antigo)
    assert s.overlay_metrics == OVERLAY_DEFAULT
    assert "volts" in s.overlay_metrics


def test_migracao_respeita_quem_escolheu_o_que_ver():
    """Lista mexida a mao e' escolha, e escolha nao se sobrescreve."""
    s = Settings.from_dict({"overlay_metrics": ["fps", "cpu"]})
    assert s.overlay_metrics == ["fps", "cpu"]


def test_arquivo_ja_migrado_nao_e_mexido_de_novo():
    """Depois de migrar, desmarcar tudo menos FPS tem que continuar valendo."""
    s = Settings.from_dict({"settings_version": 2, "overlay_metrics": ["fps"]})
    assert s.overlay_metrics == ["fps"]
