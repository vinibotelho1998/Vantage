"""Volumes e sensores sinteticos: nenhum disco ou WMI real e' consultado."""
from types import SimpleNamespace
import sys

import pytest

from vantage.sensors import collector
from vantage.sensors.lhm import LhmReader


PHYSICAL_0 = r"\\.\PHYSICALDRIVE0"
PHYSICAL_1 = r"\\.\PHYSICALDRIVE1"


def _partition(letter):
    return {"device": letter + "\\", "mount": letter + "\\", "fstype": "NTFS"}


def _sensor(device, *, name="SSD mesmo modelo", temp=40, life=95):
    return {"name": name, "physical_device": device, "temp": temp, "life": life}


def _collector(monkeypatch, partitions, mapping):
    c = collector.Collector.__new__(collector.Collector)
    c._disk_cache = []
    c._disk_cache_at = float("-inf")
    c._disk_volume_devices = {}
    monkeypatch.setattr(collector, "_partitions", lambda: partitions)
    monkeypatch.setattr(collector, "_disk_volume_devices", lambda: mapping)
    monkeypatch.setattr(collector, "_safe_usage", lambda _mount: (10, 100, 10))
    return c


def test_dois_volumes_do_mesmo_disco_compartilham_sensor_com_ordem_invertida(monkeypatch):
    c = _collector(monkeypatch, [_partition("C:"), _partition("D:"), _partition("E:")],
                   {"C:": PHYSICAL_0, "D:": PHYSICAL_0, "E:": PHYSICAL_1})
    disks = c._disks({"disks_lhm": [_sensor(PHYSICAL_1, temp=62, life=80),
                                   _sensor(PHYSICAL_0, temp=40, life=95)]})
    assert [(d["temp"], d["life"]) for d in disks] == [(40, 95), (40, 95), (62, 80)]
    assert all((d["used"], d["total"], d["pct"]) == (10, 100, 10) for d in disks)


def test_disco_sem_temperatura_nao_desloca_sensor_do_outro(monkeypatch):
    c = _collector(monkeypatch, [_partition("C:"), _partition("D:")],
                   {"C:": PHYSICAL_0, "D:": PHYSICAL_1})
    cold = _sensor(PHYSICAL_0, name="SSD A", life=97)
    cold.pop("temp")
    disks = c._disks({"disks_lhm": [cold, _sensor(PHYSICAL_1, name="SSD B", temp=62)]})
    assert [(d["temp"], d["life"], d["model"]) for d in disks] == [(None, 97, "SSD A"), (62, 95, "SSD B")]


@pytest.mark.parametrize("sensors", [
    [{"name": "SSD mesmo modelo", "identifier": "/hdd/0", "temp": 40}],
    [_sensor(PHYSICAL_0), _sensor(PHYSICAL_0, temp=80)],
    [_sensor(r"\\.\PHYSICALDRIVE99")],
])
def test_identidade_ausente_duplicada_ou_diferente_nao_e_adivinhada(monkeypatch, sensors):
    c = _collector(monkeypatch, [_partition("C:")], {"C:": PHYSICAL_0})
    disk = c._disks({"disks_lhm": sensors})[0]
    assert disk["temp"] is disk["life"] is disk["model"] is None


def test_volume_desconhecido_nao_recebe_sensor_por_ordem(monkeypatch):
    c = _collector(monkeypatch, [_partition("C:")], {})
    disk = c._disks({"disks_lhm": [_sensor(PHYSICAL_0)]})[0]
    assert disk["temp"] is disk["life"] is disk["model"] is None


@pytest.mark.parametrize("part", [
    {"device": "C:\\", "mount": "C:\\mounted\\", "fstype": "NTFS"},
    {"device": "D:\\", "mount": "C:\\", "fstype": "NTFS"},
    {"device": r"\\server\data", "mount": r"\\server\data", "fstype": "NTFS"},
])
def test_pasta_montada_device_inconsistente_ou_unc_nao_herda_sensor(monkeypatch, part):
    c = _collector(monkeypatch, [part], {"C:": PHYSICAL_0, "D:": PHYSICAL_0})
    assert c._disks({"disks_lhm": [_sensor(PHYSICAL_0)]})[0]["temp"] is None


def _wmi_disk(device, volumes, *, fail=False):
    def logicals(**kwargs):
        assert kwargs == {"wmi_association_class": "Win32_LogicalDiskToPartition"}
        if fail:
            raise OSError("associacao indisponivel")
        return [SimpleNamespace(DeviceID=volume) for volume in volumes]

    def partitions(**kwargs):
        assert kwargs == {"wmi_association_class": "Win32_DiskDriveToDiskPartition"}
        return [SimpleNamespace(associators=logicals)]

    return SimpleNamespace(DeviceID=device, associators=partitions)


def _install_wmi(monkeypatch, disks):
    monkeypatch.setitem(sys.modules, "wmi", SimpleNamespace(
        WMI=lambda: SimpleNamespace(Win32_DiskDrive=lambda: disks)))


def test_mapa_wmi_usa_associacoes_e_nao_ordem_modelo_ou_indice(monkeypatch):
    _install_wmi(monkeypatch, [_wmi_disk(PHYSICAL_1.lower(), ["E:"]),
                               _wmi_disk(PHYSICAL_0, ["C:", "D:"])])
    assert collector._disk_volume_devices() == {"C:": PHYSICAL_0, "D:": PHYSICAL_0, "E:": PHYSICAL_1}


@pytest.mark.parametrize("other_device", [PHYSICAL_1, "disco virtual sem identidade"])
def test_volume_distribuido_ou_com_extent_desconhecido_nao_tem_disco_unico(monkeypatch, other_device):
    _install_wmi(monkeypatch, [_wmi_disk(PHYSICAL_0, ["C:", "F:"]),
                               _wmi_disk(other_device, ["F:"])])
    assert collector._disk_volume_devices() == {"C:": PHYSICAL_0}


def test_erro_wmi_parcial_descarta_mapa_incompleto(monkeypatch):
    _install_wmi(monkeypatch, [_wmi_disk(PHYSICAL_0, ["F:"]),
                               _wmi_disk(PHYSICAL_1, ["F:"], fail=True)])
    assert collector._disk_volume_devices() == {}


@pytest.mark.parametrize("empty", [False, True])
def test_cache_de_volumes_e_mapa_inclusive_vazio_dura_vinte_segundos(monkeypatch, empty):
    partitions = [] if empty else [_partition("C:")]
    c = _collector(monkeypatch, partitions, {"C:": PHYSICAL_0})
    now, calls = [0.0], []
    monkeypatch.setattr(collector.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(collector, "_partitions", lambda: calls.append("part") or partitions)
    monkeypatch.setattr(collector, "_disk_volume_devices", lambda: calls.append("map") or {"C:": PHYSICAL_0})
    c._disks({})
    now[0] = 19.99
    c._disks({})
    assert calls == ["part", "map"]
    now[0] = 20.0
    c._disks({})
    assert calls == ["part", "map", "part", "map"]


def test_lhm_publica_dispositivo_fisico_real_e_nao_interpreta_identifier():
    hw = SimpleNamespace(Name="SSD", Identifier="/nvme/77",
                         Storage=SimpleNamespace(PhysicalPath=r"\\.\PhysicalDrive2"),
                         Sensors=[SimpleNamespace(SensorType="Temperature", Name="Composite Temperature", Value=41),
                                  SimpleNamespace(SensorType="Level", Name="Life", Value=97)])
    result = {}
    LhmReader()._read_storage(hw, result)
    disk = result["disks_lhm"][0]
    assert disk["identifier"] == "/nvme/77"
    assert disk["physical_device"] == r"\\.\PhysicalDrive2"
    assert (disk["temp"], disk["life"]) == (41, 97)


def test_lhm_sem_storage_preserva_sensor_sem_inventar_unidade():
    hw = SimpleNamespace(Name="SSD", Identifier="/hdd/0",
                         Sensors=[SimpleNamespace(SensorType="Temperature", Name="Temperature", Value=44)])
    result = {}
    LhmReader()._read_storage(hw, result)
    assert result["disks_lhm"][0]["temp"] == 44
    assert result["disks_lhm"][0]["physical_device"] == ""
