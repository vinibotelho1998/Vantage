"""Voltagem que a maquina entrega, nao a que ela pede.

O risco coberto aqui e' o pior tipo de erro de sensor: o numero plausivel e
errado. Nesta maquina o "Core #N VID" marcou 0,463 V com o processador em 98 W e
5225 MHz — impossivel — e o app publicava exatamente isso como "voltagem da CPU".
Um travessao seria honesto; 0,46 V com cara de medida nao e'. Os testes fixam que
VID nunca vira Vcore, que o rail anonimo da placa so' e' adotado depois de provar
que acompanha a carga, e que a procedencia viaja junto do numero.
"""
from dbxstats.sensors.lhm import LhmReader


class _Sensor:
    def __init__(self, tipo: str, nome: str, valor):
        self.SensorType = tipo
        self.Name = nome
        self.Value = valor


class _Hardware:
    def __init__(self, nome: str, sensores, subs=()):
        self.Name = nome
        self.Sensors = sensores
        self.SubHardware = list(subs)

    def Update(self) -> None:
        pass


def _leitor() -> LhmReader:
    leitor = LhmReader.__new__(LhmReader)
    leitor._rails = {}
    return leitor


def _cpu(sensores, leitor=None, resultado=None) -> dict:
    resultado = {} if resultado is None else resultado
    (leitor or _leitor())._read_cpu(_Hardware("AMD Ryzen 7 9800X3D", sensores), resultado)
    return resultado


def _placa(rails_por_ciclo, leitor=None) -> list[dict]:
    """Roda um ciclo por lista de rails e devolve o resultado de cada um."""
    leitor = leitor or _leitor()
    saidas = []
    for rails in rails_por_ciclo:
        resultado: dict = {}
        sub = _Hardware("ITE IT8696E",
                        [_Sensor("Voltage", nome, valor) for nome, valor in rails])
        leitor._read_motherboard(_Hardware("Gigabyte X870M", [], [sub]), resultado)
        saidas.append(resultado)
    return saidas


def test_vid_do_ryzen_nao_vira_voltagem_da_cpu():
    """0,463 V com o pacote em 98 W nao existe: VID e' pedido, nao entrega."""
    d = _cpu([
        _Sensor("Voltage", "Core #1 VID", 0.463),
        _Sensor("Voltage", "Core #2 VID", 0.450),
        _Sensor("Power", "Package", 98.2),
    ])
    assert "cpu_volts" not in d
    assert d["cpu_vid"] == 0.463


def test_sensor_de_nucleo_com_nome_proprio_vale_como_voltagem():
    """Intel publica 'CPU Core' de verdade; recusar isso perderia a medida."""
    d = _cpu([_Sensor("Voltage", "CPU Core", 1.184)])
    assert d["cpu_volts"] == 1.184
    assert d["cpu_volts_src"] == "cpu"


def test_rail_sem_nome_so_entra_depois_de_se_mexer():
    """Placa sem perfil no LHM da' sete numeros anonimos; chutar um e' inventar."""
    leitor = _leitor()
    parado = [("Voltage #1", 1.068), ("Voltage #5", 1.248), ("Voltage #7", 1.440)]
    primeiro, segundo = _placa([parado, parado], leitor)
    assert "cpu_volts" not in primeiro
    assert "cpu_volts" not in segundo

    andou = [("Voltage #1", 1.128), ("Voltage #5", 1.248), ("Voltage #7", 1.440)]
    terceiro = _placa([andou], leitor)[0]
    assert terceiro["cpu_volts"] == 1.128
    assert terceiro["cpu_volts_src"] == "rail"
    assert terceiro["cpu_volts_rail"] == "Voltage #1"


def test_rail_fora_da_faixa_de_vcore_nao_e_candidato():
    """2,0 V nao e' Vcore de nenhum desktop; movimento ali e' outro circuito."""
    leitor = _leitor()
    saidas = _placa([[("Voltage #3", 2.040)], [("Voltage #3", 2.100)]], leitor)
    assert "cpu_volts" not in saidas[-1]


def test_rail_nomeado_dispensa_a_espera():
    """Placa com perfil diz 'Vcore' na cara; nao ha por que exigir movimento."""
    d = _placa([[("Vcore", 1.164), ("Voltage #5", 1.248)]])[0]
    assert d["cpu_volts"] == 1.164
    assert d["cpu_volts_src"] == "vcore"
    assert "cpu_volts_rail" not in d


def test_vcore_da_placa_ganha_do_sensor_da_cpu_nas_duas_ordens():
    """Qual hardware o LHM entrega primeiro varia; o numero escolhido nao pode."""
    def _ler(primeiro_a_placa: bool) -> dict:
        leitor, resultado = _leitor(), {}
        placa = _Hardware("Gigabyte X870M", [], [
            _Hardware("ITE", [_Sensor("Voltage", "Vcore", 1.164)])])
        passos = [lambda: leitor._read_motherboard(placa, resultado),
                  lambda: _cpu([_Sensor("Voltage", "CPU Core", 1.184)], leitor, resultado)]
        for passo in (passos if primeiro_a_placa else passos[::-1]):
            passo()
        return resultado

    for resultado in (_ler(True), _ler(False)):
        assert resultado["cpu_volts"] == 1.164
        assert resultado["cpu_volts_src"] == "vcore"


def test_voltagem_da_gpu_sai_do_rail_do_nucleo():
    """A tensao da GPU e' a metrica sadia da maquina — nao pode se perder."""
    leitor = _leitor()
    gpus: list[dict] = []
    leitor._read_gpu(_Hardware("AMD Radeon RX 9070 XT", [
        _Sensor("Voltage", "GPU Core", 0.638),
        _Sensor("Temperature", "GPU Memory", 67.0),
    ]), "GpuAmd", gpus)
    assert gpus[0]["volts"] == 0.638
    assert gpus[0]["temp_vram"] == 67


def test_voltagem_de_outro_rail_da_gpu_nao_se_passa_por_nucleo():
    """SoC e VRAM tem tensao propria; publicar uma delas como 'GPU' e' mentira."""
    leitor = _leitor()
    gpus: list[dict] = []
    leitor._read_gpu(_Hardware("GPU", [_Sensor("Voltage", "GPU SoC", 0.900)]),
                     "GpuAmd", gpus)
    assert "volts" not in gpus[0]
