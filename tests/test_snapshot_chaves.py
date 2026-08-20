"""As chaves novas atravessando o coletor ate' o snapshot.

Cada sensor ja' tem teste proprio; o risco que sobra e' o de sempre nesta
arquitetura: o dado ser lido corretamente e nunca chegar na UI, porque o dict de
saida do coletor e' montado a mao e uma chave esquecida ali some sem erro nenhum
— foi exatamente assim que a temperatura dos pentes ficou invisivel.
"""
import psutil
import pytest

from dbxstats.sensors.collector import Collector

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
