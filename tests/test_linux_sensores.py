"""Sensores e telas do Linux contra um sysfs falso: nenhum arquivo de verdade e' lido."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="integracoes Linux")


def _escrever(caminho, texto):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto)


@pytest.fixture
def sysfs(tmp_path):
    """Uma placa AMD, o CPU com k10temp e uma placa-mae sem rotulos nos canais."""
    sys_ = tmp_path / "sys"
    pci = sys_ / "devices/pci0000:00/0000:03:00.0"
    _escrever(pci / "gpu_busy_percent", "7\n")
    _escrever(pci / "mem_busy_percent", "3\n")
    _escrever(pci / "mem_info_vram_used", str(2048 * 2**20) + "\n")
    _escrever(pci / "mem_info_vram_total", str(16384 * 2**20) + "\n")
    _escrever(pci / "product_name", "Radeon de teste\n")
    _escrever(pci / "vbios_version", "113-TESTE-001\n")
    _escrever(pci / "current_link_speed", "16.0 GT/s PCIe\n")
    _escrever(pci / "current_link_width", "16\n")
    (sys_ / "class/drm").mkdir(parents=True)
    (sys_ / "class/drm/card1").symlink_to(pci.parent / "card1", target_is_directory=True)
    (pci.parent / "card1").mkdir(parents=True, exist_ok=True)
    (pci.parent / "card1/device").symlink_to(pci, target_is_directory=True)
    drivers = sys_ / "bus/pci/drivers/amdgpu"
    drivers.mkdir(parents=True)
    (pci / "driver").symlink_to(drivers, target_is_directory=True)
    # hwmon da placa: fica dentro do dispositivo e e' apontado por class/hwmon.
    gpu_hw = pci / "hwmon/hwmon3"
    _escrever(gpu_hw / "name", "amdgpu\n")
    _escrever(gpu_hw / "temp1_input", "44000\n")
    _escrever(gpu_hw / "temp1_label", "edge\n")
    _escrever(gpu_hw / "temp1_crit", "100000\n")
    _escrever(gpu_hw / "temp2_input", "46000\n")
    _escrever(gpu_hw / "temp2_label", "junction\n")
    _escrever(gpu_hw / "power1_average", "50000000\n")
    _escrever(gpu_hw / "power1_cap", "304000000\n")
    _escrever(gpu_hw / "fan1_input", "1200\n")
    _escrever(gpu_hw / "fan1_max", "3000\n")
    _escrever(gpu_hw / "in0_input", "702\n")
    _escrever(gpu_hw / "in0_label", "vddgfx\n")
    (gpu_hw / "device").symlink_to(pci, target_is_directory=True)
    (sys_ / "class/hwmon").mkdir(parents=True)
    (sys_ / "class/hwmon/hwmon3").symlink_to(gpu_hw, target_is_directory=True)
    cpu_hw = sys_ / "devices/platform/k10temp/hwmon/hwmon1"
    _escrever(cpu_hw / "name", "k10temp\n")
    _escrever(cpu_hw / "temp1_input", "56500\n")
    _escrever(cpu_hw / "temp1_label", "Tctl\n")
    (sys_ / "class/hwmon/hwmon1").symlink_to(cpu_hw, target_is_directory=True)
    placa = sys_ / "devices/platform/gigabyte_wmi/hwmon/hwmon2"
    _escrever(placa / "name", "gigabyte_wmi\n")
    _escrever(placa / "temp3_input", "56000\n")
    (sys_ / "class/hwmon/hwmon2").symlink_to(placa, target_is_directory=True)
    _escrever(sys_ / "class/dmi/id/board_name", "Placa de teste\n")
    proc = tmp_path / "proc"
    _escrever(proc / "cpuinfo", "processor\t: 0\nmodel name\t: CPU de teste\n")
    return sys_, proc


def _ler(sysfs):
    from vantage.sensors.linux import LinuxSensors

    leitor = LinuxSensors(sys_root=sysfs[0], proc_root=sysfs[1])
    return leitor, leitor.read()


def test_placa_amd_traz_driver_pcie_vbios_e_limites(sysfs):
    _, dados = _ler(sysfs)
    assert dados["gpu_static"] == {"driver": "amdgpu", "vbios": "113-TESTE-001", "pcie_gen": 4,
                                   "pcie_width": 16, "power_limit": 304.0, "temp_slowdown": 100.0}
    assert dados["gpu_volts"] == pytest.approx(0.702)
    assert dados["gpu_mem_ctrl"] == 3
    assert dados["gpu_fan_pct"] == pytest.approx(40.0)
    assert dados["gpu_temp"] == 44 and dados["gpu_temp_hotspot"] == 46
    assert dados["gpu_watts"] == 50


def test_chips_ganham_titulo_legivel_e_canais_sem_rotulo_ganham_nome(sysfs):
    leitor, _ = _ler(sysfs)
    nos = {(n.hardware, n.name): n for n in leitor.tree()}
    # a assinatura de SensorNode guarda o titulo do chip primeiro; checa pelos textos
    titulos = {n.hardware for n in leitor.tree()}
    assert "CPU AMD (k10temp)" in titulos
    assert "Placa-mãe (gigabyte_wmi)" in titulos
    assert "Radeon de teste" in titulos
    assert any(nome == "Temperatura 3" for _, nome in nos)


def test_gpu_sem_sysfs_de_pcie_nao_inventa_nada(tmp_path):
    from vantage.sensors.linux import LinuxSensors

    assert LinuxSensors._gpu_static(tmp_path) == {}


def test_titulo_do_chip_desconhecido_fica_cru():
    from vantage.sensors.linux import titulo_do_chip

    assert titulo_do_chip("chip_que_ninguem_conhece") == "chip_que_ninguem_conhece"
    assert titulo_do_chip("r8169_0_b00:00") == "Ethernet (r8169_0_b00:00)"


def test_so_controle_de_verdade_aparece_na_lista(tmp_path):
    from vantage.ui.views.linux_devices import listar_controles

    def porta(n, nome, teclas):
        base = tmp_path / f"js{n}/device"
        _escrever(base / "name", nome + "\n")
        _escrever(base / "capabilities/key", teclas + "\n")

    def mapa(*codigos):
        """Como o kernel escreve o mapa de teclas: palavras de 64 bits, a mais alta primeiro."""
        valor = sum(1 << c for c in codigos)
        return " ".join(f"{valor >> (64 * i) & (2**64 - 1):x}" for i in reversed(range(12)))

    gamepad = mapa(0x130, 0x131)      # BTN_SOUTH e BTN_EAST, como num gamepad
    mouse = mapa(0x110, 0x111)        # BTN_LEFT e BTN_RIGHT: ponteiro virtual do keyd
    porta(0, "Controle de teste", gamepad)
    porta(1, "keyd virtual pointer", mouse)
    assert listar_controles(tmp_path) == ["Controle de teste"]


def test_nome_da_placa_usa_o_nome_de_vitrine_do_lspci(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    from vantage.sensors.linux import LinuxSensors

    saidas = {
        "03:00.0": "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 48 "
                   "[Radeon RX 9070/9070 XT/9070 GRE] (rev c0)",
        "01:00.0": "01:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3090] (rev a1)",
        "00:02.0": "00:02.0 VGA compatible controller: Intel Corporation Alder Lake GT1",
    }
    monkeypatch.setattr(subprocess, "run", lambda args, **k: SimpleNamespace(stdout=saidas[args[2]]))
    for slot, esperado in (("03:00.0", "Radeon RX 9070/9070 XT/9070 GRE"), ("01:00.0", "GeForce RTX 3090"),
                           ("00:02.0", "Intel Corporation Alder Lake GT1")):
        pasta = tmp_path / slot
        pasta.mkdir(exist_ok=True)
        assert LinuxSensors._gpu_name(pasta) == esperado
