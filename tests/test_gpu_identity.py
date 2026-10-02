"""Identidade entre fontes: sem NVML/WMI reais, processos ou acesso a hardware."""
import sys
from types import SimpleNamespace

import pytest

from vantage.core.series import Ema
from vantage.sensors.collector import Collector, _mesma_gpu
from vantage.sensors.gpu import GpuReader


class _Gpu:
    nvml_ok = True
    static = {"name": "NVIDIA RTX 2080", "power_limit": 215, "driver": "nvml-driver"}
    identity = {"name": "NVIDIA RTX 2080", "uuid": "GPU-zero",
                "names": ("NVIDIA RTX 2080",)}

    def __init__(self):
        self.calls = []
        self.watts = 120

    def read_nvml(self):
        return {"name": "NVIDIA RTX 2080", "usage": 70, "temp": 60,
                "freq": 1800, "vram_used": 100, "vram_total": 8192,
                "watts": self.watts, "throttle": ["Limite de potencia"]}

    def watts_smi(self):
        self.calls.append("smi")
        return 110

    def watts_estimate(self, *_):
        self.calls.append("estimate")
        return 100

    def vram(self):
        self.calls.append("vram")
        return (100, 8192)

    def reset_estimate(self):
        self.calls.append("reset")


def _collector(gpu=None):
    # Constructor coleta contadores e metadados da maquina; esse teste exercita
    # somente a fusao, com todas as fontes explicitamente substituidas.
    c = Collector.__new__(Collector)
    c._gpu = gpu or _Gpu()
    c._gpu_identity = None
    c._gpu_watts_ema = Ema(0.35)
    c._gpu_wmi = {}
    c._gpu_wmi_info = lambda _name: {}
    return c


def _lhm(name="NVIDIA RTX 2080", **updates):
    return {"gpu_ok": True, "gpu_name": name, "gpu_list": [name], "_gpu_type": "GpuNvidia",
            **updates}


def test_amd_nao_recebe_vram_limite_static_throttle_ou_watts_da_nvidia():
    c = _collector()
    gpu = c._collect_gpu(_lhm("AMD RX 7900 XTX", gpu_usage=99, gpu_temp=75,
                              gpu_vram_used=16000, gpu_vram_total=24576))
    assert gpu["name"] == "AMD RX 7900 XTX"
    assert gpu["usage"] == 99 and gpu["temp"] == 75
    assert (gpu["vram_used"], gpu["vram_total"]) == (16000, 24576)
    assert gpu["power_limit"] is None and gpu["static"] == {}
    assert not gpu["throttle_supported"] and gpu["throttle"] == []
    assert gpu["watts"] is None and not gpu["watts_estimated"]
    assert not ({"smi", "estimate", "vram"} & set(c._gpu.calls))


def test_segunda_nvidia_nao_recebe_campos_do_indice_zero():
    c = _collector()
    c._gpu.identity = dict(c._gpu.identity, names=("NVIDIA RTX 2080", "NVIDIA RTX 5090"))
    gpu = c._collect_gpu(_lhm("NVIDIA RTX 5090", gpu_vram_total=32768))
    assert gpu["vram_total"] == 32768
    assert gpu["vram_used"] is None and gpu["freq"] is None
    assert gpu["power_limit"] is None and gpu["static"] == {}


def test_placa_de_outro_vendor_com_nome_editado_nao_autoriza_fusao():
    c = _collector()
    gpu = c._collect_gpu(_lhm(_gpu_type="GpuAmd"))
    assert gpu["vram_total"] is None and gpu["power_limit"] is None


@pytest.mark.parametrize("nomes_nvml,nomes_lhm", [
    (("NVIDIA RTX 2080", "NVIDIA RTX 2080"), ["NVIDIA RTX 2080"]),
    (("NVIDIA RTX 2080",), ["NVIDIA RTX 2080", "NVIDIA RTX 2080"]),
    (None, ["NVIDIA RTX 2080"]), (("NVIDIA RTX 2080",), None),
])
def test_modelo_duplicado_ou_inventario_incompleto_nao_autoriza_fusao(nomes_nvml, nomes_lhm):
    lhm = _lhm(gpu_list=nomes_lhm)
    identity = {"name": "NVIDIA RTX 2080", "names": nomes_nvml}
    assert not _mesma_gpu(lhm, identity)


def test_mesma_placa_unica_completa_somente_campos_ausentes_preservando_zero():
    c = _collector()
    gpu = c._collect_gpu(_lhm(gpu_usage=0, gpu_freq=0, gpu_fan_pct=0,
                              gpu_vram_used=0, gpu_watts=0))
    assert gpu["usage"] == gpu["freq"] == gpu["fan_pct"] == gpu["vram_used"] == 0
    assert gpu["watts"] == 0 and not gpu["watts_estimated"]
    assert gpu["vram_total"] == 8192 and gpu["temp"] == 60
    assert gpu["power_limit"] == 215 and gpu["throttle_supported"]


def test_sem_lhm_nvml_zero_continua_fonte_integral():
    c = _collector()
    gpu = c._collect_gpu({})
    assert gpu["name"] == "NVIDIA RTX 2080"
    assert (gpu["vram_used"], gpu["vram_total"]) == (100, 8192)
    assert gpu["power_limit"] == 215 and gpu["static"]["name"] == gpu["name"]


def test_fallback_de_potencia_so_roda_para_mesmo_adaptador():
    c = _collector()
    c._gpu.watts = None
    gpu = c._collect_gpu(_lhm())
    assert gpu["watts"] == 110 and "smi" in c._gpu.calls
    c._gpu.watts_smi = lambda: None
    gpu = c._collect_gpu(_lhm())
    assert gpu["watts_estimated"] and "estimate" in c._gpu.calls


def test_media_de_potencia_nao_cruza_troca_de_placa_ou_sensor_ausente():
    c = _collector()
    assert c._collect_gpu(_lhm(gpu_watts=200))["watts"] == 200
    assert c._collect_gpu(_lhm("AMD RX 7900 XTX", gpu_watts=30))["watts"] == 30
    assert c._collect_gpu(_lhm("AMD RX 7900 XTX"))["watts"] is None
    assert c._collect_gpu(_lhm("AMD RX 7900 XTX", gpu_watts=60))["watts"] == 60


def test_placas_lhm_de_nome_igual_nao_compartilham_media():
    c = _collector()
    lhm = _lhm(gpu_list=["NVIDIA RTX 2080", "NVIDIA RTX 2080"], gpu_watts=200)
    assert c._collect_gpu(lhm)["watts"] == 200
    lhm["gpu_watts"] = 30
    assert c._collect_gpu(lhm)["watts"] == 30


def test_perda_de_identidade_nvml_limpa_media_anterior():
    c = _collector()
    assert c._collect_gpu(_lhm(gpu_watts=200))["watts"] == 200
    c._gpu.identity = dict(c._gpu.identity, names=("NVIDIA RTX 2080", "NVIDIA RTX 2080"))
    assert c._collect_gpu(_lhm(gpu_watts=30))["watts"] == 30


def test_wmi_cache_por_nome_exato_e_nao_por_ultimo_token(monkeypatch):
    calls = []
    placas = [SimpleNamespace(Name=name, DriverVersion=driver,
                              VideoModeDescription="1920 x 1080 x 32", CurrentRefreshRate=60)
              for name, driver in [("AMD RX 7900 XTX", "amd-driver"),
                                   ("NVIDIA RTX 2080", "nvidia-driver")]]
    def controllers():
        calls.append(1)
        return placas
    monkeypatch.setitem(sys.modules, "wmi", SimpleNamespace(WMI=lambda: SimpleNamespace(Win32_VideoController=controllers)))
    c = Collector.__new__(Collector)
    c._gpu_wmi = {}
    assert c._gpu_wmi_info("AMD RX 7900 XTX")["driver"] == "amd-driver"
    assert c._gpu_wmi_info("NVIDIA RTX 2080")["driver"] == "nvidia-driver"
    assert c._gpu_wmi_info("NVIDIA RTX 2080 Ti") == {}
    assert c._gpu_wmi_info("amd rx 7900 xtx")["driver"] == "amd-driver"
    assert len(calls) == 3


def test_wmi_modelos_duplicados_nao_recebem_modo_de_outra_placa(monkeypatch):
    placas = [SimpleNamespace(Name="NVIDIA RTX 2080") for _ in range(2)]
    monkeypatch.setitem(sys.modules, "wmi", SimpleNamespace(WMI=lambda: SimpleNamespace(Win32_VideoController=lambda: placas)))
    c = Collector.__new__(Collector)
    c._gpu_wmi = {}
    assert c._gpu_wmi_info("NVIDIA RTX 2080") == {}


def test_identidade_nvml_preserva_uuid_pci_e_modelos_repetidos():
    class Nvml:
        def nvmlDeviceGetCount(self): return 2
        def nvmlDeviceGetHandleByIndex(self, index): return index
        def nvmlDeviceGetName(self, handle): return b"NVIDIA RTX 2080"
        def nvmlDeviceGetUUID(self, handle): return b"GPU-zero"
        def nvmlDeviceGetPciInfo(self, handle): return SimpleNamespace(busId=b"00000000:01:00.0")
    g = GpuReader.__new__(GpuReader)
    g._pynvml, g._hdl, g._name = Nvml(), 0, "NVIDIA RTX 2080"
    g._load_identity()
    assert g.identity["index"] == 0 and g.identity["uuid"] == "GPU-zero"
    assert g.identity["pci_bus_id"] == "00000000:01:00.0"
    assert g.identity["names"] == ("NVIDIA RTX 2080", "NVIDIA RTX 2080")


def test_nvml_nao_expoe_inventario_parcial_como_completo():
    class Nvml:
        def nvmlDeviceGetCount(self): return 2
        def nvmlDeviceGetHandleByIndex(self, index): return index
        def nvmlDeviceGetName(self, handle):
            if handle == 1: raise RuntimeError("placa indisponivel")
            return b"NVIDIA RTX 2080"
    g = GpuReader.__new__(GpuReader)
    g._pynvml, g._hdl, g._name = Nvml(), 0, "NVIDIA RTX 2080"
    g._load_identity()
    assert g.identity["names"] is None
