"""Temperatura dos pentes de DDR5: o dado existia e morria antes do dict.

O sensor chega na arvore do LHM (40,00 °C e 39,25 °C nesta maquina), mas o
_read_memory antigo devolvia sem ler tudo que nao se chamasse "Total Memory";
entao nenhum card conseguia mostrar. Os riscos cobertos: o dado atravessar ate' o
dict, o rotulo nao carregar o lixo binario que o SPD as vezes devolve, e a
conversa por SMBus (2,2 ms, mais cara que a CPU inteira) nao entrar no ciclo de
1 Hz sendo um sensor que nao mexeu 0,01 °C em 15 s.
"""
from vantage.sensors.lhm import LhmReader, _e_modulo_spd


class _Sensor:
    def __init__(self, tipo: str, nome: str, valor):
        self.SensorType = tipo
        self.Name = nome
        self.Value = valor


class _Modulo:
    """Um pente como o LHM entrega: temperatura mais os limites de fabrica."""

    HardwareType = "Memory"

    def __init__(self, nome: str, slot: str, temp: float):
        self.Name = nome
        self.updates = 0
        self.Sensors = [
            _Sensor("Temperature", slot, temp),
            _Sensor("Temperature", "Temperature Sensor Resolution", 0.25),
            _Sensor("Temperature", "Thermal Sensor Low Limit", 0.0),
            _Sensor("Temperature", "Thermal Sensor High Limit", 55.0),
            _Sensor("Temperature", "Thermal Sensor Critical Low Limit", 0.0),
            _Sensor("Temperature", "Thermal Sensor Critical High Limit", 85.0),
            _Sensor("Data", "Capacity", 16.0),
        ]

    def Update(self) -> None:
        self.updates += 1


def _ler(*modulos) -> dict:
    leitor = LhmReader.__new__(LhmReader)
    resultado: dict = {}
    for m in modulos:
        leitor._read_memory(m, resultado)
    return resultado


def test_temperatura_do_pente_chega_ao_dict_com_os_limites():
    """Limite de fabrica junto e' o que permite colorir sem chutar faixa."""
    d = _ler(_Modulo("A-DATA AX5U6000C3016G (#1)", "DIMM #1", 40.0))
    modulo = d["ram_modules"][0]
    assert modulo["slot"] == "DIMM #1"
    assert modulo["temp"] == 40.0
    assert modulo["high"] == 55.0
    assert modulo["critical"] == 85.0


def test_pente_mais_quente_e_o_numero_da_peca():
    """Media de dois pentes esconderia o que esta' perto do limite."""
    d = _ler(_Modulo("A-DATA (#1)", "DIMM #1", 40.0),
             _Modulo("A-DATA (#3)", "DIMM #3", 39.25))
    assert d["ram_temp"] == 40.0
    assert len(d["ram_modules"]) == 2


def test_nome_sujo_do_spd_nao_vira_rotulo():
    """O pente do slot #3 voltou com byte nulo no meio do modelo numa leitura."""
    d = _ler(_Modulo("A-DATA Technology - AX5U6000C3016G-DCLARBK>\x00} (#3)",
                     "DIMM #3", 39.25))
    assert d["ram_modules"][0]["model"] == "A-DATA Technology - AX5U6000C3016G-DCLARBK (#3)"


def test_hardware_de_memoria_sem_temperatura_nao_inventa_pente():
    """A Virtual Memory do LHM e' commit charge: nao e' pente e nao tem sensor."""
    virtual = _Modulo("Virtual Memory", "x", 0.0)
    virtual.Sensors = [_Sensor("Data", "Memory Used", 32.9)]
    d = _ler(virtual)
    assert "ram_modules" not in d
    assert "ram_temp" not in d


def test_totais_calculados_nao_sao_confundidos_com_pente():
    """So' o hardware do pente custa SMBus; o total sai de graca e nao pode parar."""
    assert _e_modulo_spd(_Modulo("A-DATA (#1)", "DIMM #1", 40.0))
    assert not _e_modulo_spd(_Modulo("Total Memory", "x", 0.0))
    assert not _e_modulo_spd(_Modulo("Virtual Memory", "x", 0.0))


def test_pente_nao_e_relido_a_cada_ciclo():
    """2,2 ms por segundo por um sensor parado ha' 15 s nao se justifica."""
    leitor = LhmReader.__new__(LhmReader)
    leitor._spd_at = 0.0
    assert leitor._spd_vencido() is True
    assert leitor._spd_vencido() is False
    assert leitor._spd_vencido() is False
