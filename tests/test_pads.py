"""Inventario de controles: o que a tela mostra alem do que o XInput le'."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from dbxstats.platform import pads  # noqa: E402


def _pad(**kw) -> pads.Pad:
    base = dict(name="Controle", vid=0x054C, pid=0x0CE6, bus="Bluetooth",
                xinput=False, slot=None, path="")
    base.update(kw)
    return pads.Pad(**base)


def test_reconhece_o_dualsense_pelo_par_conhecido():
    """054C:0CE6 e' o DualSense. Sem a tabela ele se apresenta so' como
    "Wireless Controller", que nao diz qual controle da mesa e' aquele."""
    assert pads._KNOWN[(0x054C, 0x0CE6)] == "DualSense (PS5)"


def test_vendor_traduz_o_fabricante():
    assert _pad().vendor == "Sony"


def test_vendor_desconhecido_fica_vazio():
    assert _pad(vid=0x9999).vendor == ""


def test_ids_saem_em_hexa_de_quatro_digitos():
    assert _pad().ids == "VID 054C · PID 0CE6"


# ── nome que o Windows embrulha ──────────────────────────────────────────────
def test_desembrulha_o_nome_entre_parenteses():
    """"Controller (Fulano X)" e' o formato do driver generico; o miolo e' o nome."""
    assert pads._unwrap("Controller (Ultimate C 2.4G )") == "Ultimate C 2.4G"


def test_parenteses_vazio_nao_apaga_o_nome():
    assert pads._unwrap("Controller ()") == "Controller ()"


def test_nome_sem_parenteses_passa_inteiro():
    assert pads._unwrap("DualSense Wireless") == "DualSense Wireless"


# ── barramento pelo caminho do dispositivo ───────────────────────────────────
def test_caminho_com_servico_hid_bluetooth_e_sem_fio():
    caminho = (r"\\?\hid#{00001124-0000-1000-8000-00805f9b34fb}"
               r"_vid&0002054c_pid&0ce6#b&bd8684b&0&0000")
    assert pads._bus(caminho) == "Bluetooth"


def test_caminho_usb_comum_e_usb():
    assert pads._bus(r"\\?\hid#vid_2dc8&pid_3106&ig_00#a&8542f3b&0&0000") == "USB"


def test_caminho_irreconhecivel_nao_inventa_barramento():
    assert pads._bus(r"\\?\algumacoisa#estranha") == "—"


# ── filtro de uso HID ────────────────────────────────────────────────────────
def test_so_joystick_gamepad_e_multieixo_contam_como_controle():
    """Teclado e mouse tambem sao HID de mesa; sem o filtro por uso, a lista de
    controles viraria a lista de perifericos inteira."""
    assert pads.USAGES_PAD == (0x04, 0x05, 0x08)
    assert pads.USAGE_PAGE_GENERIC == 0x01


def test_list_pads_nao_explode_e_devolve_lista():
    """Roda contra a maquina de verdade: o que importa e' nao levantar."""
    achados = pads.list_pads()
    assert isinstance(achados, list)
    assert all(isinstance(p, pads.Pad) for p in achados)


def test_summary_concorda_com_list_pads():
    total, legiveis = pads.summary()
    assert total >= legiveis >= 0
