"""Inventario de controles conectados, incluindo os que o XInput nao enxerga.

O `gamepad.py` le entrada por XInput, e o XInput so' expoe dispositivos
Xbox-compativeis. Um DualSense pareado direto por Bluetooth aparece para o
Windows como HID generico e fica invisivel la' — o que da' a impressao de que o
app "nao reconhece o controle" quando na verdade ele nunca foi oferecido.

Esta tela conta a verdade: varre a lista de interfaces HID pelo SetupAPI, filtra
o que se declara joystick ou gamepad, e marca quais o app consegue de fato ler.
Assim um controle que nao serve para o modo mouse ainda aparece, com o motivo.

Nada aqui e' derivado de codigo de terceiros: sai direto da documentacao do
Win32 (SetupAPI + HIDsdi), o que mantem o projeto em MIT.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .. import log

_log = log.get("pads")

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3

USAGE_PAGE_GENERIC = 0x01
USAGES_PAD = (0x04, 0x05, 0x08)
"""Joystick, gamepad e controle multi-eixo. E' o que conta como controle."""


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD),
                ("Reserved", ctypes.POINTER(wintypes.ULONG))]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    """Struct de tamanho variavel; o caminho vem colado no fim.

    O buffer fixo evita a dupla chamada de sondagem. 512 wchars cobre com folga
    qualquer caminho de dispositivo que o Windows gere.
    """
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", wintypes.WCHAR * 512)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    """Only Usage/UsagePage interessam, mas a struct inteira precisa existir:
    `HidP_GetCaps` escreve tudo, e um buffer curto seria estouro de pilha."""
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17),
                ("NumberLinkCollectionNodes", wintypes.USHORT),
                ("NumberInputButtonCaps", wintypes.USHORT),
                ("NumberInputValueCaps", wintypes.USHORT),
                ("NumberInputDataIndices", wintypes.USHORT),
                ("NumberOutputButtonCaps", wintypes.USHORT),
                ("NumberOutputValueCaps", wintypes.USHORT),
                ("NumberOutputDataIndices", wintypes.USHORT),
                ("NumberFeatureButtonCaps", wintypes.USHORT),
                ("NumberFeatureValueCaps", wintypes.USHORT),
                ("NumberFeatureDataIndices", wintypes.USHORT)]


def _setup_prototypes() -> None:
    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
    hid.HidD_GetHidGuid.restype = None
    hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
    hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
    hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetProductString.restype = wintypes.BOOLEAN
    hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                               wintypes.ULONG]
    hid.HidD_GetManufacturerString.restype = wintypes.BOOLEAN
    hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    hid.HidP_GetCaps.restype = wintypes.LONG

    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                              wintypes.HWND, wintypes.DWORD]
    setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
        ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
        ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


_setup_prototypes()


# Nomes bonitos para o que o proprio dispositivo nao sabe dizer. Muito controle
# devolve string de produto vazia ou generica ("Wireless Controller"), e ai' a
# tela viraria uma lista de numeros.
_KNOWN: dict[tuple[int, int], str] = {
    (0x054C, 0x0BA0): "DualShock 4 (dongle sem fio)",
    (0x054C, 0x05C4): "DualShock 4",
    (0x054C, 0x09CC): "DualShock 4 (v2)",
    (0x054C, 0x0CE6): "DualSense (PS5)",
    (0x054C, 0x0DF2): "DualSense Edge (PS5)",
    (0x045E, 0x028E): "Xbox 360",
    (0x045E, 0x02D1): "Xbox One",
    (0x045E, 0x02DD): "Xbox One (firmware 2015)",
    (0x045E, 0x02EA): "Xbox One S",
    (0x045E, 0x02FD): "Xbox One S (Bluetooth)",
    (0x045E, 0x0B12): "Xbox Series X|S",
    (0x045E, 0x0B13): "Xbox Series X|S (Bluetooth)",
    (0x045E, 0x0B20): "Xbox Elite Series 2",
    (0x057E, 0x2009): "Joy-Con / Switch Pro",
    (0x057E, 0x2006): "Joy-Con (L)",
    (0x057E, 0x2007): "Joy-Con (R)",
    (0x28DE, 0x1102): "Steam Controller",
    (0x28DE, 0x1142): "Steam Controller (dongle)",
}

_VENDORS: dict[int, str] = {
    0x045E: "Microsoft", 0x054C: "Sony", 0x057E: "Nintendo", 0x28DE: "Valve",
    0x0079: "DragonRise", 0x2DC8: "8BitDo", 0x0F0D: "HORI", 0x146B: "BigBen",
    0x24C6: "PowerA", 0x1532: "Razer", 0x0E6F: "PDP", 0x3285: "Nacon",
}

_BT_SERVICE = "{00001124-0000-1000-8000-00805f9b34fb}"
"""GUID do servico HID sobre Bluetooth. Se o caminho tem isso, veio pelo ar."""

SONY = 0x054C
SONY_HID = {0x0CE6, 0x0DF2, 0x09CC, 0x05C4, 0x0BA0}
"""Controles da Sony que o app le' direto por HID, sem passar pelo XInput.

Mora aqui, e nao no leitor, porque identificar dispositivo e' o assunto deste
modulo — e porque a tela precisa saber quem e' legivel antes de qualquer leitor
existir. Ver `dualsense.py`, que consome esta lista.
"""


@dataclass(frozen=True)
class Pad:
    """Um controle visto pelo Windows."""

    name: str
    vid: int
    pid: int
    bus: str
    """"USB", "Bluetooth" ou "—" quando o caminho nao denuncia."""
    xinput: bool
    """O app consegue ler este aqui. Falso = aparece, mas nao comanda nada."""
    slot: int | None
    """Slot XInput, quando houver. E' o que o `rumble` endereca."""
    path: str

    @property
    def readable(self) -> bool:
        """O app consegue ler este controle, por qualquer caminho.

        Separado de `xinput` de proposito. `xinput` e' o fato tecnico — se o
        Windows expoe o controle naquela API — e continua valendo para a
        vibracao, que so' existe la'. Legibilidade e' outra coisa desde que o app
        passou a ler os controles da Sony direto por HID: um DualSense e'
        `xinput=False` e legivel ao mesmo tempo. Confundir os dois e' o que
        fazia a tela dizer "o app nao le" sobre um controle que estava, naquele
        mesmo instante, movendo o cursor.
        """
        return self.xinput or (self.vid == SONY and self.pid in SONY_HID)

    @property
    def how(self) -> str:
        """Por onde ele e' lido, para a tela poder explicar a diferenca."""
        if self.xinput:
            return "XInput"
        return "HID" if self.readable else ""

    @property
    def vendor(self) -> str:
        return _VENDORS.get(self.vid, "")

    @property
    def ids(self) -> str:
        return f"VID {self.vid:04X} · PID {self.pid:04X}"


def _wide(handle, fn) -> str:
    """Le uma string HID. Buffer de 126 wchars e' o maximo que o HIDsdi aceita."""
    buf = ctypes.create_unicode_buffer(126)
    if not fn(handle, buf, ctypes.sizeof(buf)):
        return ""
    return buf.value.strip()


def _is_pad(handle) -> bool:
    """O dispositivo se declara controle no proprio descritor de relatorio?

    Filtrar por VID/PID conhecido nao serve: cada controle generico de mercado
    livre tem um par proprio. O descritor e' a fonte que o Windows usa, entao e'
    a que concorda com o que aparece em Dispositivos e Impressoras.
    """
    pre = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(handle, ctypes.byref(pre)):
        return False
    try:
        caps = HIDP_CAPS()
        if hid.HidP_GetCaps(pre, ctypes.byref(caps)) < 0:
            return False
        return caps.UsagePage == USAGE_PAGE_GENERIC and caps.Usage in USAGES_PAD
    finally:
        hid.HidD_FreePreparsedData(pre)


def _open(path: str):
    """Abre so' para consulta.

    Acesso zero e' de proposito: um controle ja' aberto em modo exclusivo por um
    jogo recusaria leitura, e a tela ficaria mentindo que ele sumiu. Sem pedir
    acesso, o Windows entrega o handle mesmo assim — da' para perguntar VID, PID
    e nome, que e' tudo que esta tela precisa.
    """
    handle = kernel32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  None, OPEN_EXISTING, 0, None)
    return None if handle == INVALID_HANDLE_VALUE else handle


def _bus(path: str) -> str:
    low = path.lower()
    if _BT_SERVICE in low:
        return "Bluetooth"
    if "hid#vid" in low or "usb" in low:
        return "USB"
    return "—"


def _unwrap(produto: str) -> str:
    """Desembrulha o "Controller (Nome De Verdade)" que o Windows monta.

    O driver de joystick generico embrulha o nome do fabricante nesse formato, e
    o miolo e' sempre mais informativo que a casca. So' vale quando ha' miolo:
    um "Controller ()" vazio deve continuar sendo "Controller".
    """
    inicio, fim = produto.find("("), produto.rfind(")")
    if 0 <= inicio < fim:
        miolo = produto[inicio + 1:fim].strip()
        if miolo:
            return miolo
    return produto


def _name(handle, vid: int, pid: int) -> str:
    """Nome de exibicao, do mais especifico para o mais generico.

    A tabela vem antes da string do dispositivo de proposito: um DualSense se
    apresenta como "Wireless Controller", que nao ajuda ninguem a saber qual
    dos controles em cima da mesa e' aquele.
    """
    conhecido = _KNOWN.get((vid, pid))
    if conhecido:
        return conhecido
    produto = _unwrap(_wide(handle, hid.HidD_GetProductString))
    if produto:
        fabricante = _wide(handle, hid.HidD_GetManufacturerString)
        if fabricante and not produto.lower().startswith(fabricante.lower()):
            return f"{fabricante} {produto}"
        return produto
    vendor = _VENDORS.get(vid)
    return f"Controle {vendor}" if vendor else "Controle desconhecido"


def _hid_pads() -> list[Pad]:
    """Todo dispositivo HID presente que se declara controle."""
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if devs == INVALID_HANDLE_VALUE:
        _log.warning("SetupDiGetClassDevsW falhou: %s", ctypes.get_last_error())
        return []

    achados: list[Pad] = []
    vistos: set[str] = set()
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid),
                                                        index, ctypes.byref(iface)):
                break
            index += 1

            detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
            # cbSize aqui e' o da CABECA da struct, nao o do buffer inteiro. E'
            # a pegadinha classica do SetupAPI: passar sizeof(struct) faz a
            # chamada falhar com ERROR_INVALID_USER_BUFFER.
            detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                    devs, ctypes.byref(iface), ctypes.byref(detail),
                    ctypes.sizeof(detail), None, None):
                continue

            path = detail.DevicePath
            if not path or path.lower() in vistos:
                continue

            handle = _open(path)
            if handle is None:
                continue
            try:
                if not _is_pad(handle):
                    continue
                attrs = HIDD_ATTRIBUTES()
                attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
                if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                    continue
                vistos.add(path.lower())
                achados.append(Pad(
                    name=_name(handle, attrs.VendorID, attrs.ProductID),
                    vid=attrs.VendorID, pid=attrs.ProductID,
                    bus=_bus(path),
                    # "ig_" no caminho e' a marca de dispositivo XInput. E' o
                    # mesmo teste que a documentacao do XInput manda usar para
                    # separar os dois mundos.
                    xinput="ig_" in path.lower(),
                    slot=None, path=path))
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(devs)
    return achados


def _xinput_slots() -> list[int]:
    """Slots XInput ocupados agora, perguntando ao proprio XInput."""
    from . import gamepad as G

    if not G.available():
        return []
    slots = []
    for slot in range(4):
        state = G.XINPUT_STATE()
        if G._xinput.XInputGetState(slot, ctypes.byref(state)) == G.ERROR_SUCCESS:
            slots.append(slot)
    return slots


def list_pads() -> list[Pad]:
    """Todos os controles conectados, os legiveis e os nao legiveis.

    Duas fontes, porque nenhuma sozinha ve' tudo: a varredura HID acha o que o
    XInput ignora (DualSense por Bluetooth, controles DirectInput), e o proprio
    XInput garante os controles Xbox de driver XUSB, que nem sempre publicam
    interface HID. O casamento entre as duas e' por ordem, que e' o unico laco
    disponivel: o XInput nao revela VID, PID nem caminho do dispositivo.

    Legiveis primeiro na lista — sao os que respondem quando o usuario aperta.
    """
    try:
        pads = _hid_pads()
    except OSError as e:
        _log.warning("varredura HID falhou: %s", e)
        pads = []

    slots = _xinput_slots()
    marcados = [p for p in pads if p.xinput]

    # Cada slot ocupado recebe um dos HID marcados com IG_; o que sobrar de slot
    # e' controle que nao publicou interface HID, e entra como entrada propria.
    saida: list[Pad] = []
    for pad in pads:
        if pad.xinput and marcados:
            idx = marcados.index(pad)
            slot = slots[idx] if idx < len(slots) else None
            pad = Pad(pad.name, pad.vid, pad.pid, pad.bus, True, slot, pad.path)
        saida.append(pad)

    for extra in range(len(marcados), len(slots)):
        saida.append(Pad(name="Controle XInput", vid=0, pid=0, bus="—",
                         xinput=True, slot=slots[extra], path=""))

    saida.sort(key=lambda p: (not p.xinput, p.name.lower()))
    return saida


def input_report_length(path: str) -> int:
    """Tamanho do relatorio de entrada do dispositivo, em bytes.

    Quem le' precisa do numero exato: `ReadFile` num HID recusa buffer menor que
    o relatorio, e um chute grande demais nao ajuda porque o driver so' entrega
    de relatorio inteiro em relatorio inteiro. O DualSense por Bluetooth usa 78,
    e o mesmo controle por USB usa 64 — nao da' para fixar.
    """
    handle = _open(path)
    if handle is None:
        return 0
    try:
        pre = ctypes.c_void_p()
        if not hid.HidD_GetPreparsedData(handle, ctypes.byref(pre)):
            return 0
        try:
            caps = HIDP_CAPS()
            if hid.HidP_GetCaps(pre, ctypes.byref(caps)) < 0:
                return 0
            return int(caps.InputReportByteLength)
        finally:
            hid.HidD_FreePreparsedData(pre)
    finally:
        kernel32.CloseHandle(handle)


def summary() -> tuple[int, int]:
    """(quantos ao todo, quantos o app consegue ler). Para os KPIs."""
    pads = list_pads()
    return len(pads), sum(1 for p in pads if p.xinput)
