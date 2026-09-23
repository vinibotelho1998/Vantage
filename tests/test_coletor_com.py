"""Consultas WMI feitas de dentro da thread do coletor.

O WMI e' COM, e COM recusa thread que nao se apresentou a ele. O modulo `wmi`
aqui e' um duble: nenhuma peca da maquina e' consultada. O que ele faz de
verdade e' criar um objeto COM trivial do proprio Windows (o dicionario do
Scripting), que falha exatamente como o WMI falharia numa thread sem COM.
"""
import sys
import types

# Como no app: o `wmi` de verdade e' importado primeiro na thread principal, e o
# pythoncom apresenta ao COM so' a thread que o importou. Importado pela primeira
# vez dentro da thread do coletor, ele mascararia a falha.
import win32com.client

from vantage.sensors.collector import Collector


class _Lhm:
    ready = True

    def read(self) -> dict:
        return {}


class _Gpu:
    nvml_ok = False
    static: dict = {}


class _Ping:
    def read(self) -> dict:
        return {}


class _WmiFalso:
    def Win32_Processor(self):
        return []

    def Win32_PhysicalMemory(self):
        win32com.client.Dispatch("Scripting.Dictionary")
        return [types.SimpleNamespace(ConfiguredClockSpeed=6000, Speed=6000,
                                      Manufacturer="A-DATA", PartNumber="AX5U6000",
                                      SMBIOSMemoryType=34)]


def test_frequencia_da_ram_e_lida_de_dentro_da_thread_do_coletor(monkeypatch):
    """Sem apresentar a thread ao COM, a consulta falhava com "CoInitialize nao
    foi chamado", o erro ia para o log de depuracao e o cache guardava a falha:
    a frequencia da RAM e o driver da GPU nunca apareciam."""
    modulo = types.ModuleType("wmi")
    modulo.WMI = _WmiFalso
    monkeypatch.setitem(sys.modules, "wmi", modulo)

    coletor = Collector(_Lhm(), _Gpu(), _Ping())
    visto = {}

    def _uma_volta() -> dict:
        visto["freq"] = coletor._ram_freq_mhz()
        coletor._stop.set()
        return {}

    coletor._collect = _uma_volta
    coletor.start()
    coletor._thread.join(10.0)

    assert visto.get("freq") == 6000
    assert coletor._ram_info["type"] == "DDR5"
