"""Reserva do nvidia-smi: so' quando a NVML nao entrega o consumo.

Nada aqui fala com placa nenhuma: a NVML e o nvidia-smi sao dubles.
"""
import threading

import vantage.sensors.gpu as gpumod
from vantage.sensors.gpu import GpuReader


class _Parar:
    """Deixa o laco dar exatamente `voltas` voltas, sem esperar de verdade."""

    def __init__(self, voltas: int):
        self.voltas = voltas

    def is_set(self) -> bool:
        self.voltas -= 1
        return self.voltas < 0

    def wait(self, _segundos) -> bool:
        return False


class _Nvml:
    def __init__(self, miliwatts):
        self.miliwatts = miliwatts

    def nvmlDeviceGetPowerUsage(self, _h):
        if self.miliwatts is None:
            raise RuntimeError("NVML_ERROR_NOT_SUPPORTED")
        return self.miliwatts


def _leitor(miliwatts, voltas=2) -> GpuReader:
    g = GpuReader.__new__(GpuReader)
    g._ok = True
    g._hdl = object()
    g._pynvml = _Nvml(miliwatts)
    g._smi_lock = threading.Lock()
    g._smi_watts = None
    g._stop = _Parar(voltas)
    return g


def _smi_falso(monkeypatch, chamadas):
    monkeypatch.setattr(gpumod.shutil, "which", lambda _n: r"C:\falso\nvidia-smi.exe")
    monkeypatch.setattr(gpumod.os.path, "exists", lambda _p: True)

    def _check_output(cmd, **_kw):
        chamadas.append(cmd)
        return b"187.30\n"

    monkeypatch.setattr(gpumod.subprocess, "check_output", _check_output)


def test_com_consumo_pela_nvml_o_nvidia_smi_nao_sobe(monkeypatch):
    """Um processo a cada dois segundos, a partida inteira, para um numero que a
    NVML ja' entrega: e' custo no pior momento, com o jogo rodando."""
    chamadas = []
    _smi_falso(monkeypatch, chamadas)
    g = _leitor(215_000)

    g._smi_loop()

    assert chamadas == []
    assert g.watts_smi() is None


def test_sem_consumo_pela_nvml_a_reserva_continua_valendo(monkeypatch):
    chamadas = []
    _smi_falso(monkeypatch, chamadas)
    g = _leitor(None)

    g._smi_loop()

    assert len(chamadas) == 2
    assert all("--id=0" in cmd for cmd in chamadas)
    assert g.watts_smi() == 187.3


def test_leitura_smi_que_falha_nao_mantem_consumo_antigo(monkeypatch):
    chamadas = []
    _smi_falso(monkeypatch, chamadas)
    respostas = iter([b"187.30\n", None])
    def check_output(cmd, **kwargs):
        resultado = next(respostas)
        if resultado is None:
            raise RuntimeError("driver nao respondeu")
        return resultado
    monkeypatch.setattr(gpumod.subprocess, "check_output", check_output)
    g = _leitor(None)
    g._smi_loop()
    assert g.watts_smi() is None


def test_leitura_smi_nao_suportada_nao_mantem_consumo_antigo(monkeypatch):
    chamadas = []
    _smi_falso(monkeypatch, chamadas)
    respostas = iter([b"187.30\n", b"[Not Supported]\n"])
    monkeypatch.setattr(gpumod.subprocess, "check_output", lambda *a, **kw: next(respostas))
    g = _leitor(None)
    g._smi_loop()
    assert g.watts_smi() is None
