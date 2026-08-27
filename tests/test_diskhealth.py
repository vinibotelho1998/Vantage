"""Saude de disco so' pode mostrar o que a maquina realmente reportou.

O risco coberto aqui e' o pior de todos nessa tela: inventar leitura. Um "0%" de
vida restante que na verdade era "o disco nao respondeu" faz trocar um SSD
saudavel; um "100%" chutado esconde um que esta' morrendo. Cada teste abaixo
trava um caminho pelo qual um numero poderia aparecer sem existir.
"""
from dbxstats.sensors import diskhealth
from dbxstats.sensors.lhm import SensorNode


def _no(hardware: str, kind: str, nome: str, valor: float,
         hw_type: str = "Storage") -> SensorNode:
    return SensorNode(key=f"{hardware}/{kind}/{nome}", hardware=hardware,
                      hw_type=hw_type, name=nome, kind=kind, unit="", value=valor)


# ── LibreHardwareMonitor ─────────────────────────────────────────────────────
def test_desgaste_nvme_vira_vida_restante():
    """NVMe publica 'Percentage Used'; a tela fala em vida restante."""
    d = diskhealth.from_lhm_tree([
        _no("Samsung SSD 990 PRO", "Level", "Percentage Used", 4.0),
    ])
    assert d[0]["life"] == 96.0


def test_vida_ja_pronta_nao_e_recalculada():
    """SSD SATA publica 'Remaining Life' direto: inverter de novo seria erro."""
    d = diskhealth.from_lhm_tree([
        _no("Crucial MX500", "Level", "Remaining Life", 91.0),
    ])
    assert d[0]["life"] == 91.0


def test_limite_de_alarme_nao_e_confundido_com_reserva():
    """'Available Spare Threshold' e' o gatilho do alarme, nao a reserva atual."""
    d = diskhealth.from_lhm_tree([
        _no("NVMe X", "Level", "Available Spare", 100.0),
        _no("NVMe X", "Level", "Available Spare Threshold", 10.0),
    ])
    assert d[0]["spare"] == 100.0


def test_temperatura_composta_ganha_do_sensor_por_chip():
    """Varios NVMe expoem um sensor por chip; o composto representa o disco."""
    d = diskhealth.from_lhm_tree([
        _no("NVMe X", "Temperature", "Temperature 1", 71.0),
        _no("NVMe X", "Temperature", "Composite Temperature", 44.0),
        _no("NVMe X", "Temperature", "Temperature 2", 68.0),
    ])
    assert d[0]["temp"] == 44.0


def test_escrita_e_leitura_acumuladas_sao_separadas():
    d = diskhealth.from_lhm_tree([
        _no("NVMe X", "Data", "Data Written", 12345.6),
        _no("NVMe X", "Data", "Data Read", 999.4),
        _no("NVMe X", "Factor", "Power On Hours", 4210.0),
    ])
    assert d[0]["written_gb"] == 12345.6
    assert d[0]["read_gb"] == 999.4
    assert d[0]["hours"] == 4210.0


def test_sensor_de_outra_peca_nao_entra_como_disco():
    """A arvore do LHM traz CPU, GPU e placa junto; so' Storage interessa aqui."""
    assert diskhealth.from_lhm_tree([
        _no("AMD Ryzen 7 9800X3D", "Temperature", "Core (Tctl/Tdie)", 62.0, "Cpu"),
    ]) == []


def test_sensor_sem_leitura_nao_vira_campo():
    """Valor None do LHM significa 'nao consegui ler', nao 'zero'."""
    d = diskhealth.from_lhm_tree([
        _no("NVMe X", "Level", "Percentage Used", None),
        _no("NVMe X", "Data", "Data Written", 10.0),
    ])
    assert "life" not in d[0]
    assert d[0]["written_gb"] == 10.0


def test_disco_sem_nenhum_dado_util_e_reconhecido():
    """Disco que so' tem nome nao merece um card cheio de travessoes."""
    assert not diskhealth.tem_dado({"name": "HD antigo"})
    assert diskhealth.tem_dado({"name": "HD antigo", "hours": 5.0})


# ── Storage Spaces / PowerShell ──────────────────────────────────────────────
def test_campo_nulo_do_cim_nao_vira_zero():
    """Sem elevacao o contador de confiabilidade volta nulo em tudo."""
    d = diskhealth.parse_physical(
        '[{"id":"0","nome":"SSD M.2 NVME 2TB","tamanho":2048408248320,'
        '"saude":"Healthy","temp":null,"horas":null,"desgaste":null,'
        '"erros_leitura":null,"letras":["C:","D:"]}]')
    assert d[0]["name"] == "SSD M.2 NVME 2TB"
    assert d[0]["letters"] == ["C:", "D:"]
    assert d[0]["health"] == "Healthy"
    for ausente in ("temp", "hours", "life", "errors_read"):
        assert ausente not in d[0]


def test_zero_em_contador_de_erro_e_leitura_valida():
    """Aqui zero e' boa noticia e precisa aparecer; nao e' ausencia de dado."""
    d = diskhealth.parse_physical(
        '[{"id":"0","nome":"NVMe","erros_leitura":0,"erros_escrita":0,"horas":9000}]')
    assert d[0]["errors_read"] == 0.0
    assert d[0]["errors_write"] == 0.0
    assert d[0]["hours"] == 9000.0


def test_desgaste_do_windows_tambem_vira_vida_restante():
    d = diskhealth.parse_physical('[{"id":"0","nome":"NVMe","desgaste":7}]')
    assert d[0]["life"] == 93.0


def test_json_quebrado_nao_derruba_a_tela():
    assert diskhealth.parse_physical("") == []
    assert diskhealth.parse_physical("nao e json") == []
    assert diskhealth.parse_physical("null") == []


def test_um_disco_so_vem_como_objeto_e_nao_como_lista():
    """ConvertTo-Json com um item so' devolve objeto; a tela nao pode sumir."""
    d = diskhealth.parse_physical('{"id":"0","nome":"NVMe","horas":12}')
    assert len(d) == 1 and d[0]["hours"] == 12.0


# ── fusao das duas fontes ────────────────────────────────────────────────────
def test_modelo_com_espaco_extra_ainda_casa():
    """Windows e LHM escrevem o mesmo modelo com pontuacao diferente."""
    juntos = diskhealth.combinar(
        [{"id": "0", "name": "SSD M.2  NVME 2TB", "health": "Healthy",
          "letters": ["C:"]}],
        [{"name": "SSD M.2 NVME 2TB", "life": 97.0, "written_gb": 4200.0}])
    assert len(juntos) == 1
    assert juntos[0]["life"] == 97.0
    assert juntos[0]["letters"] == ["C:"]
    assert juntos[0]["name"] == "SSD M.2  NVME 2TB"


def test_nome_diferente_cai_para_a_ordem_quando_as_contas_fecham():
    """Adaptador USB e RAID renomeiam o disco; a ordem das duas APIs coincide."""
    juntos = diskhealth.combinar(
        [{"id": "0", "name": "Disco A"}, {"id": "1", "name": "Disco B"}],
        [{"name": "Modelo X", "life": 90.0}, {"name": "Modelo Y", "life": 50.0}])
    assert [x["life"] for x in juntos] == [90.0, 50.0]


def test_contas_que_nao_fecham_nao_casam_por_chute():
    """Dois discos no Windows e um no LHM: nao da' para saber de qual e' a vida."""
    juntos = diskhealth.combinar(
        [{"id": "0", "name": "Disco A"}, {"id": "1", "name": "Disco B"}],
        [{"name": "Modelo X", "life": 90.0}])
    assert "life" not in juntos[0]
    assert "life" not in juntos[1]
    assert juntos[-1]["life"] == 90.0        # entra sozinho, sem dono


def test_sem_powershell_o_lhm_sozinho_ainda_aparece():
    """Maquina sem os comandos de armazenamento nao pode perder a vida util."""
    juntos = diskhealth.combinar([], [{"name": "NVMe X", "life": 88.0}])
    assert juntos == [{"name": "NVMe X", "life": 88.0}]


def test_dado_do_windows_nao_e_sobrescrito_pelo_lhm():
    """Quando as duas fontes tem o campo, a que ja' estava fica."""
    juntos = diskhealth.combinar(
        [{"id": "0", "name": "NVMe X", "temp": 41.0}],
        [{"name": "NVMe X", "temp": 99.0, "life": 95.0}])
    assert juntos[0]["temp"] == 41.0
    assert juntos[0]["life"] == 95.0
