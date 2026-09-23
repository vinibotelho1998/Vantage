"""Varredura do LHM com sensor que devolve numero que nao e' numero.

O LHM publica float anulavel, e ha' sensor que entrega NaN ou infinito enquanto
o driver ainda nao tem leitura (divisao por zero na conta de dentro dele). O
hardware aqui e' todo de mentira: nenhuma peca da maquina e' consultada.
"""
from vantage.sensors.lhm import LhmReader

NAN = float("nan")
INF = float("inf")


class _Sensor:
    def __init__(self, tipo, nome, valor):
        self.SensorType = tipo
        self.Name = nome
        self.Value = valor


class _Hardware:
    def __init__(self, nome, sensores, tipo):
        self.Name = nome
        self.Sensors = sensores
        self.HardwareType = tipo
        self.SubHardware = []

    def Update(self):
        pass


def _leitor(*hardware) -> LhmReader:
    leitor = LhmReader()
    leitor._ready = True
    leitor._computer = type("C", (), {"Hardware": list(hardware)})()
    return leitor


def _cpu(clock):
    return _Hardware("Ryzen 7 9800X3D", [
        _Sensor("Clock", "Cores (Average)", clock),
        _Sensor("Clock", "Core #1", clock),
        _Sensor("Temperature", "Core (Tctl/Tdie)", 71.5),
    ], "Cpu")


def _gpu(clock):
    return _Hardware("AMD Radeon RX 9070 XT", [
        _Sensor("Temperature", "GPU Core", 55.0),
        _Sensor("Clock", "GPU Core", clock),
        _Sensor("Load", "GPU Core", 97.0),
    ], "GpuAmd")


def test_clock_nan_na_cpu_nao_apaga_o_resto_da_maquina():
    """Um int(nan) no meio da varredura derrubava o ciclo inteiro: a GPU, a
    temperatura e a arvore da aba Sensores sumiam, a cada leitura."""
    leitor = _leitor(_cpu(NAN), _gpu(2500.0))

    d = leitor.read()

    assert d["cpu_temp"] == 71.5
    assert "cpu_mhz_avg" not in d
    assert d["gpu_temp"] == 55
    assert d["gpu_freq"] == 2500
    assert any(n.name == "GPU Core" for n in leitor.tree())


def test_infinito_na_gpu_nao_vira_leitura():
    leitor = _leitor(_cpu(5225.0), _gpu(INF))

    d = leitor.read()

    assert d["cpu_mhz_avg"] == 5225
    assert d["gpu_usage"] == 97
    assert "gpu_freq" not in d
    assert all(n.value == n.value and abs(n.value) != INF for n in leitor.tree())
