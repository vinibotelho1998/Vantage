"""Duas temperaturas por peca: a de trabalho e o ponto quente.

Uma so' sempre mente para algum lado: a media esconde throttle e o pico
assusta a toa. O overlay mostra as duas, entao o leitor precisa separa-las.
"""
from vantage.sensors.lhm import LhmReader


class _Sensor:
    def __init__(self, tipo: str, nome: str, valor):
        self.SensorType = tipo
        self.Name = nome
        self.Value = valor


class _Hardware:
    def __init__(self, nome: str, sensores):
        self.Name = nome
        self.Sensors = sensores


def _ler(sensores) -> dict:
    leitor = LhmReader.__new__(LhmReader)
    resultado: dict = {}
    leitor._read_cpu(_Hardware("Ryzen 7 9800X3D", sensores), resultado)
    return resultado


def test_ryzen_separa_pacote_da_media_dos_ccds():
    """Ryzen nao publica nucleo a nucleo; o detalhe que existe e' por CCD."""
    d = _ler([
        _Sensor("Temperature", "Core (Tctl/Tdie)", 78.2),
        _Sensor("Temperature", "CCD1 (Tdie)", 60.0),
        _Sensor("Temperature", "CCD2 (Tdie)", 62.0),
    ])
    assert d["cpu_temp_package"] == 78.2
    assert d["cpu_temp_cores"] == 61.0


def test_nucleo_a_nucleo_vira_a_media_quando_existe():
    d = _ler([
        _Sensor("Temperature", "CPU Package", 70.0),
        _Sensor("Temperature", "CPU Core #1", 64.0),
        _Sensor("Temperature", "CPU Core #2", 66.0),
    ])
    assert d["cpu_temp_package"] == 70.0
    assert d["cpu_temp_cores"] == 65.0


def test_maquina_sem_detalhe_nao_inventa_media():
    """Sem sensor por die nem por nucleo, sobra so' o pacote, e tudo bem."""
    d = _ler([_Sensor("Temperature", "CPU Package", 70.0)])
    assert d["cpu_temp_package"] == 70.0
    assert "cpu_temp_cores" not in d


def test_sensor_zerado_nao_entra_na_conta():
    """Sensor sem leitura devolve 0 e puxaria a media para baixo."""
    d = _ler([
        _Sensor("Temperature", "Core (Tctl/Tdie)", 75.0),
        _Sensor("Temperature", "CCD1 (Tdie)", 60.0),
        _Sensor("Temperature", "CCD2 (Tdie)", 0.0),
    ])
    assert d["cpu_temp_cores"] == 60.0
