"""As chaves novas atravessando o coletor ate' o snapshot.

Cada sensor ja' tem teste proprio; o risco que sobra e' o de sempre nesta
arquitetura: o dado ser lido corretamente e nunca chegar na UI, porque o dict de
saida do coletor e' montado a mao e uma chave esquecida ali some sem erro nenhum;
foi exatamente assim que a temperatura dos pentes ficou invisivel.
"""
import psutil
import pytest

from vantage.sensors.collector import Collector

_LHM = {
    "cpu_volts": 1.128, "cpu_volts_src": "rail", "cpu_volts_rail": "Voltage #1",
    "cpu_vid": 0.463,
    "ram_temp": 40.0,
    "ram_modules": [{"slot": "DIMM #1", "temp": 40.0, "high": 55.0, "critical": 85.0,
                     "model": "A-DATA (#1)"}],
    "gpu_ok": True, "gpu_name": "AMD Radeon RX 9070 XT",
    "gpu_volts": 0.638, "gpu_temp_vram": 67, "gpu_temp": 48,
    "gpu_vram_used": 2512, "gpu_vram_total": 16304,
}


class _Lhm:
    ready = True

    def read(self) -> dict:
        return dict(_LHM)


class _Gpu:
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


class _Ping:
    def read(self) -> dict:
        return {}


class _Proc:
    pid = 4242

    def name(self) -> str:
        return "cs2.exe"

    def memory_info(self):
        return type("m", (), {"rss": 4890.1 * 1024 ** 2,
                              "private": 6123.4 * 1024 ** 2})()


@pytest.fixture
def coletor():
    c = Collector(_Lhm(), _Gpu(), _Ping())
    # WMI e' consulta de segundos e nao tem nada a ver com o que se mede aqui.
    c._gpu_wmi = {}
    c._ram_freq = 0
    return c


def test_voltagens_e_temperaturas_novas_chegam_no_snapshot(coletor):
    d = coletor._collect()
    assert d["cpu_volts"] == 1.128
    assert d["cpu_volts_src"] == "rail"
    assert d["cpu_volts_rail"] == "Voltage #1"
    assert d["cpu_vid"] == 0.463
    assert d["ram_temp"] == 40.0
    assert d["ram_modules"][0]["slot"] == "DIMM #1"
    assert d["gpu"]["volts"] == 0.638
    assert d["gpu"]["temp_vram"] == 67


def test_ram_do_jogo_entra_e_sai_com_o_jogo(coletor, monkeypatch):
    """Chave presente com valor velho e' pior que chave ausente."""
    assert "game_ram_private" not in coletor._collect()

    monkeypatch.setattr(psutil, "Process", lambda pid: _Proc())
    coletor.set_game_pid(4242)
    d = coletor._collect()
    assert d["game_pid"] == 4242
    assert d["game_name"] == "cs2.exe"
    assert d["game_ram_private"] == 6123.4
    assert d["game_ram_wset"] == 4890.1

    coletor.set_game_pid(0)
    fechado = coletor._collect()
    assert "game_pid" not in fechado
    assert "game_ram_private" not in fechado
    assert "game_ram_wset" not in fechado


_IGPU = {"gpu_ok": True, "gpu_name": "AMD Radeon(TM) Graphics", "gpu_usage": 7,
         "gpu_temp": 44}
"""Placa que o LHM enxerga mas cujos sensores de memoria nao existem com esses
nomes: e' o caso das iGPUs, que publicam "D3D Dedicated Memory Used" em vez de
"GPU Memory Used"."""


def test_gpu_sem_sensor_de_memoria_nao_inventa_um_total_de_1_mib(coletor):
    """Sentinela numerica derrota as guardas de "esta maquina nao mede isso".

    Um total de 1 MiB e' truthy: passa por todo `if vram_total` escrito para
    esconder a VRAM em maquina sem GPU dedicada, e o painel exibia "0.0 / 0.0 GB"
    com "Livre 1 MB" embaixo: numeros que ninguem mediu, com cara de medida.
    Mesma armadilha no zero de carga e de clock.
    """
    gpu = coletor._collect_gpu(dict(_IGPU))
    assert gpu["vram_used"] is None
    assert gpu["vram_total"] is None
    assert gpu["vram_pct"] is None
    assert gpu["freq"] is None
    assert gpu["mem_freq"] is None
    # O que a placa realmente publica continua chegando inteiro.
    assert gpu["usage"] == 7
    assert gpu["temp"] == 44


def test_gpu_com_sensor_de_memoria_continua_calculando_a_porcentagem(coletor):
    """A correcao nao pode custar a leitura de quem tem o sensor."""
    gpu = coletor._collect_gpu(dict(_LHM))
    assert gpu["vram_used"] == 2512
    assert gpu["vram_total"] == 16304
    assert 15.0 < gpu["vram_pct"] < 16.0


def test_interface_de_rede_que_some_nao_vira_taxa_negativa(coletor, monkeypatch):
    """O contador do psutil e' a soma de todas as interfaces.

    Desligar a VPN (ou o Wi-Fi) tira os bytes dela da soma de uma vez, e a
    diferenca contra o ciclo anterior saia negativa: o painel mostrava download
    de "-40 MB/s" e o grafico mergulhava abaixo do zero. O disco ja' tinha essa
    trava; a rede nao.
    """
    from collections import namedtuple

    rede = namedtuple("rede", "bytes_sent bytes_recv")
    coletor._prev_net = rede(9_000_000, 50_000_000)
    monkeypatch.setattr(psutil, "net_io_counters", lambda: rede(1_000_000, 2_000_000))

    d = coletor._collect()

    assert d["net_dl"] == 0.0
    assert d["net_ul"] == 0.0
