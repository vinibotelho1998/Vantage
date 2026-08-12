"""Gerenciamento de telas: listar, ligar, desligar, trocar modo e definir primaria.

Tudo via API nativa do Windows com ctypes, no mesmo padrao do `win.py`:
`EnumDisplayDevicesW` e `EnumDisplaySettingsExW` para ler, `ChangeDisplaySettingsExW`
para aplicar. O nome amigavel sai do EDID no registro, porque o `DeviceString` do
driver devolve "Generic PnP Monitor" para todo mundo.

Desligar uma tela aqui e' desanexar do desktop, que e' a camada de topologia. Nao
tem relacao com desabilitar o dispositivo no Gerenciador de Dispositivos: aquilo
deixa a saida de video ativa com o no de monitor em erro e quebra o app de
Configuracoes do Windows.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

from .. import log
from . import ccd

_log = log.get("displays")

user32 = ctypes.WinDLL("user32", use_last_error=True)

CCHDEVICENAME = 32
CCHFORMNAME = 32

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001

ENUM_CURRENT_SETTINGS = -1

DM_DISPLAYORIENTATION = 0x00000080
DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000

CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002

DMDO_DEFAULT = 0
DMDO_90 = 1
DMDO_180 = 2
DMDO_270 = 3
ROTATIONS = ((DMDO_DEFAULT, "Normal"), (DMDO_90, "90°"),
             (DMDO_180, "180°"), (DMDO_270, "270°"))

DISP_CHANGE_SUCCESSFUL = 0
_DISP_ERRORS = {
    0: "ok",
    1: "precisa reiniciar",
    -1: "falhou",
    -2: "modo invalido para essa tela",
    -3: "nao gravou no registro",
    -4: "flags invalidas",
    -5: "parametro invalido",
    -6: "conflito de dualview",
}


class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DEVMODE_POS(ctypes.Structure):
    _fields_ = [("dmPosition", POINTL),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD)]


class _DEVMODE_UNION(ctypes.Union):
    _fields_ = [("dmPos", _DEVMODE_POS), ("_pad", ctypes.c_byte * 16)]


class DEVMODEW(ctypes.Structure):
    """Variante de display do DEVMODEW. O layout tem que bater byte a byte."""

    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * CCHDEVICENAME),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("u", _DEVMODE_UNION),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * CCHFORMNAME),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


def _setup_prototypes() -> None:
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL
    user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
    user32.EnumDisplaySettingsExW.restype = wintypes.BOOL
    user32.EnumDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                              ctypes.POINTER(DEVMODEW), wintypes.DWORD]
    user32.ChangeDisplaySettingsExW.restype = wintypes.LONG
    user32.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW),
                                                wintypes.HWND, wintypes.DWORD, wintypes.LPVOID]


_setup_prototypes()


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: int
    bpp: int = 32

    @property
    def label(self) -> str:
        return f"{self.width} x {self.height} @ {self.refresh} Hz"

    def as_key(self) -> tuple[int, int, int]:
        return (self.width, self.height, self.refresh)


@dataclass
class Display:
    device: str
    """Nome do adaptador, tipo \\\\.\\DISPLAY1."""
    name: str
    """Nome amigavel vindo do EDID, com fallback para o DeviceString."""
    hardware_id: str
    monitor_id: str
    active: bool
    primary: bool
    mode: Mode | None
    position: tuple[int, int]
    rotation: int = DMDO_DEFAULT
    native: tuple[int, int] | None = None
    """Resolucao nativa do painel, lida do timing detalhado do EDID."""
    modes: list[Mode] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.active:
            return "desligada"
        return self.mode.label if self.mode else "ligada"

    def is_upscaled(self, mode: Mode) -> bool:
        """True quando o modo passa da resolucao fisica do painel.

        A GPU aceita esses modos e reduz na entrega, o que na AMD e' o Virtual
        Super Resolution. Serve como antisserrilhado, mas nao e' resolucao real,
        e a interface precisa deixar isso claro.
        """
        if not self.native:
            return False
        return mode.width > self.native[0] or mode.height > self.native[1]


# ── leitura ──────────────────────────────────────────────────────────────────
def _new_devmode() -> DEVMODEW:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm


def _current_mode(device: str) -> tuple[Mode | None, tuple[int, int], int]:
    dm = _new_devmode()
    if not user32.EnumDisplaySettingsExW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm), 0):
        return None, (0, 0), DMDO_DEFAULT
    pos = (dm.u.dmPos.dmPosition.x, dm.u.dmPos.dmPosition.y)
    rot = int(dm.u.dmPos.dmDisplayOrientation)
    if not dm.dmPelsWidth or not dm.dmPelsHeight:
        return None, pos, rot
    mode = Mode(int(dm.dmPelsWidth), int(dm.dmPelsHeight),
                int(dm.dmDisplayFrequency), int(dm.dmBitsPerPel))
    return mode, pos, rot


def set_rotation(device: str, orientation: int) -> tuple[bool, str]:
    """Gira a tela.

    Ao passar de retrato para paisagem, ou o contrario, largura e altura precisam
    trocar de lugar no DEVMODE. Sem isso o driver recusa, porque o modo pedido
    nao existe na orientacao nova.
    """
    if orientation not in (DMDO_DEFAULT, DMDO_90, DMDO_180, DMDO_270):
        return False, "orientacao invalida"
    dm = _new_devmode()
    if not user32.EnumDisplaySettingsExW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm), 0):
        return False, "nao consegui ler o modo atual"
    atual = int(dm.u.dmPos.dmDisplayOrientation)
    if atual == orientation:
        return True, "ja estava assim"
    if atual % 2 != orientation % 2:
        dm.dmPelsWidth, dm.dmPelsHeight = dm.dmPelsHeight, dm.dmPelsWidth
    dm.u.dmPos.dmDisplayOrientation = orientation
    dm.dmFields = (DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT
                   | DM_BITSPERPEL | DM_DISPLAYFREQUENCY)
    rc = user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None,
                                         CDS_UPDATEREGISTRY, None)
    if rc != DISP_CHANGE_SUCCESSFUL:
        return False, _DISP_ERRORS.get(rc, f"codigo {rc}")
    return True, "ok"


def _supported_modes(device: str) -> list[Mode]:
    """Modos do driver, nao do EDID.

    Essa distincao importa: o EDID de algumas TVs declara menos blocos de extensao
    do que realmente tem, e o Windows para de ler antes dos modos de alta taxa. O
    driver enxerga tudo, entao 4K 144 aparece aqui mesmo quando some das
    Configuracoes do Windows.
    """
    seen: dict[tuple[int, int, int], Mode] = {}
    index = 0
    while True:
        dm = _new_devmode()
        if not user32.EnumDisplaySettingsExW(device, index, ctypes.byref(dm), 0):
            break
        index += 1
        if int(dm.dmBitsPerPel) < 32:
            continue
        mode = Mode(int(dm.dmPelsWidth), int(dm.dmPelsHeight),
                    int(dm.dmDisplayFrequency), int(dm.dmBitsPerPel))
        if mode.width and mode.height and mode.refresh > 1:
            seen.setdefault(mode.as_key(), mode)
        if index > 8000:
            break
    return sorted(seen.values(), key=lambda m: (m.width, m.height, m.refresh), reverse=True)


def _monitor_info(device: str) -> tuple[str, str, str]:
    """Devolve (hardware_id, device_string, device_path) do monitor no adaptador.

    Pedimos o nome de interface porque ele sai no mesmo formato que a CCD usa em
    `monitorDevicePath`, e e' assim que as duas camadas se reconhecem sem
    heuristica. Fica algo como
    \\\\?\\DISPLAY#TCL9653#7&33d31197&0&UID268#{e6f07b5f-...}.
    """
    dd = DISPLAY_DEVICEW()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    if not user32.EnumDisplayDevicesW(device, 0, ctypes.byref(dd),
                                      EDD_GET_DEVICE_INTERFACE_NAME):
        return "", "", ""
    parts = dd.DeviceID.split("#")
    return (parts[1] if len(parts) > 2 else ""), dd.DeviceString, dd.DeviceID


def list_displays(with_modes: bool = True) -> list[Display]:
    """Lista as telas fisicas, ativas ou nao.

    Duas limpezas acontecem aqui, e as duas vieram de caso real nesta maquina:

    Saidas sem monitor sao descartadas. Drivers de tela virtual, como o do Parsec,
    registram dezenas de adaptadores vazios que poluiriam a lista.

    Saidas repetidas sao deduplicadas pelo id do monitor. Uma GPU expoe a mesma
    tela desconectada em mais de uma saida, e sem isso a mesma TV aparece tres
    vezes.
    """
    out: list[Display] = []
    seen_monitors: dict[str, int] = {}
    index = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(dd), 0):
            break
        index += 1
        if dd.StateFlags & DISPLAY_DEVICE_MIRRORING_DRIVER:
            continue
        device = dd.DeviceName
        hardware_id, device_string, monitor_id = _monitor_info(device)
        if not hardware_id or not monitor_id:
            continue
        active = bool(dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP)

        previous = seen_monitors.get(monitor_id)
        if previous is not None:
            if active and not out[previous].active:
                out[previous].device = device
                out[previous].active = True
            continue

        mode, position, rotation = _current_mode(device)
        seen_monitors[monitor_id] = len(out)
        out.append(Display(
            device=device,
            name=edid_name(hardware_id) or device_string or device,
            hardware_id=hardware_id,
            monitor_id=monitor_id,
            active=active,
            primary=bool(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE),
            mode=mode,
            rotation=rotation,
            native=edid_native(hardware_id),
            position=position,
            modes=_supported_modes(device) if with_modes else [],
        ))
    return out


# ── nome real do monitor ─────────────────────────────────────────────────────
_edid_cache: dict[str, bytes] = {}


def _edid_blob(hardware_id: str) -> bytes:
    """Le o EDID cru que o Windows guardou no registro para esse monitor."""
    if not hardware_id:
        return b""
    if hardware_id in _edid_cache:
        return _edid_cache[hardware_id]
    blob = b""
    try:
        import winreg

        base = rf"SYSTEM\CurrentControlSet\Enum\DISPLAY\{hardware_id}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                inst = winreg.EnumKey(key, i)
                try:
                    with winreg.OpenKey(key, rf"{inst}\Device Parameters") as params:
                        raw, _ = winreg.QueryValueEx(params, "EDID")
                except OSError:
                    continue
                if raw and len(raw) >= 128:
                    blob = bytes(raw)
                    break
    except OSError as e:
        _log.debug("EDID de %s indisponivel: %s", hardware_id, e)
    _edid_cache[hardware_id] = blob
    return blob


def edid_name(hardware_id: str) -> str:
    """Nome do monitor pelo descritor 0xFC.

    O driver devolve "Generic PnP Monitor" para todos, entao o nome util so existe
    dentro do EDID.
    """
    blob = _edid_blob(hardware_id)
    for chunk in _descriptors(blob):
        if chunk[3] == 0xFC:
            return chunk[5:18].split(b"\x0a")[0].decode("ascii", errors="ignore").strip()
    return ""


def edid_native(hardware_id: str) -> tuple[int, int] | None:
    """Resolucao fisica do painel, pelo primeiro timing detalhado do EDID.

    E' a unica fonte confiavel: a lista de modos do driver inclui modos
    escalonados que passam do que o painel realmente tem.
    """
    blob = _edid_blob(hardware_id)
    if len(blob) < 128:
        return None
    for i in range(4):
        offset = 54 + i * 18
        chunk = blob[offset:offset + 18]
        if len(chunk) < 18 or (not chunk[0] and not chunk[1]):
            continue
        width = chunk[2] | ((chunk[4] & 0xF0) << 4)
        height = chunk[5] | ((chunk[7] & 0xF0) << 4)
        if width and height:
            return width, height
    return None


def _descriptors(blob: bytes):
    """Descritores de texto do bloco 0, ou seja os que nao sao timing."""
    if len(blob) < 128:
        return
    for i in range(4):
        offset = 54 + i * 18
        chunk = blob[offset:offset + 18]
        if len(chunk) == 18 and not chunk[0] and not chunk[1]:
            yield chunk


# ── escrita ──────────────────────────────────────────────────────────────────
def set_mode(device: str, mode: Mode) -> tuple[bool, str]:
    """Troca resolucao e taxa de uma tela ja' ligada.

    Aqui o caminho legado continua correto e suportado, porque nao mexe em
    topologia. Aplica direto, sem CDS_NORESET: encenar sem aplicar deixa
    transacao pendente no registro que outra chamada acaba commitando sozinha.
    """
    dm = _new_devmode()
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL | DM_DISPLAYFREQUENCY
    dm.dmPelsWidth = mode.width
    dm.dmPelsHeight = mode.height
    dm.dmBitsPerPel = mode.bpp
    dm.dmDisplayFrequency = mode.refresh

    rc = user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None,
                                         CDS_UPDATEREGISTRY, None)
    if rc != DISP_CHANGE_SUCCESSFUL:
        return False, _DISP_ERRORS.get(rc, f"codigo {rc}")
    return True, "ok"


def set_enabled(device: str, enabled: bool) -> tuple[bool, str]:
    """Liga ou desliga uma tela no desktop, sem tocar no dispositivo PnP.

    Vai pela CCD. O caminho legado foi tentado e recusa a gravacao no Windows 11,
    o detalhe esta' registrado no cabecalho de `ccd.py`.
    """
    current = next((d for d in list_displays(with_modes=False) if d.device == device), None)
    if current is None:
        return False, "tela nao encontrada"
    if current.active == enabled:
        return True, "ja estava assim"
    if not enabled and _active_count() <= 1:
        return False, "e' a unica tela ligada"
    if not current.monitor_id:
        return False, "nao consegui identificar o monitor"

    ok, err = ccd.set_active(current.monitor_id, enabled)
    if not ok or not enabled:
        return ok, err

    # A CCD escolhe um modo conservador ao anexar, que numa TV 4K costuma ser
    # 60 Hz. Como a lista do driver conhece o nativo em taxa cheia, subimos para
    # ele. Falhar aqui nao invalida a operacao: a tela ja' esta' ligada.
    best = _best_mode(current.device)
    if best is not None:
        applied, why = set_mode(current.device, best)
        if not applied:
            _log.info("tela ligada mas ficou no modo padrao: %s", why)
    return True, err


def set_primary(device: str) -> tuple[bool, str]:
    """Define a tela primaria, tambem pela CCD."""
    target = next((d for d in list_displays(with_modes=False) if d.device == device), None)
    if target is None:
        return False, "tela nao encontrada"
    if not target.active:
        return False, "tela desligada"
    if not target.monitor_id:
        return False, "nao consegui identificar o monitor"
    return ccd.make_primary(target.monitor_id)


def _active_count() -> int:
    return sum(1 for d in list_displays(with_modes=False) if d.active)


def _best_mode(device: str) -> Mode | None:
    """Melhor modo para ligar uma tela: o nativo do painel, na maior taxa.

    O maior modo da lista do driver nao serve. Ele costuma ser escalonado, e numa
    TV 4K vira 4096x2160 a 60 Hz em vez do 3840x2160 a 144 que o painel realmente
    tem. So caimos no maior da lista quando nao ha' EDID para consultar.
    """
    modes = _supported_modes(device)
    if not modes:
        return None
    hardware_id, _, _ = _monitor_info(device)
    native = edid_native(hardware_id)
    if native:
        exact = [m for m in modes if (m.width, m.height) == native]
        if exact:
            return max(exact, key=lambda m: m.refresh)
    return modes[0]


def apply_profile(entries: list[dict]) -> tuple[bool, str]:
    """Aplica um perfil inteiro: topologia, depois primaria, depois modos.

    A ordem importa. A topologia entra numa unica chamada CCD, para a tela nao
    piscar por monitor. So' com as telas certas ligadas faz sentido escolher a
    primaria, e so' entao vale ajustar resolucao e taxa, que e' o unico passo em
    que o caminho legado ainda serve.
    """
    wanted_on = [e for e in entries if e.get("active")]
    if not wanted_on:
        return False, "o perfil precisa de pelo menos uma tela ligada"

    present = list_displays(with_modes=False)
    by_path = {d.monitor_id: d for d in present if d.monitor_id}
    paths = [e.get("monitor_id") for e in wanted_on
             if e.get("monitor_id") and e["monitor_id"] in by_path]
    if not paths:
        return False, "nenhuma tela do perfil esta conectada"

    ok, err = ccd.set_topology(paths)
    if not ok:
        return False, err

    primary = next((e for e in wanted_on if e.get("primary")), None)
    if primary and primary.get("monitor_id") in by_path:
        ok, err = ccd.make_primary(primary["monitor_id"])
        if not ok:
            _log.warning("primaria do perfil nao aplicou: %s", err)

    present = list_displays(with_modes=False)
    by_path = {d.monitor_id: d for d in present if d.monitor_id}
    for entry in wanted_on:
        raw = entry.get("mode")
        disp = by_path.get(entry.get("monitor_id", ""))
        if not raw or disp is None or not disp.active:
            continue
        mode = Mode(*raw)
        if disp.mode and disp.mode.as_key() == mode.as_key():
            continue
        ok, err = set_mode(disp.device, mode)
        if not ok:
            _log.warning("modo de %s nao aplicou: %s", disp.name, err)
    return True, "ok"


def _entry(disp: Display, active: bool, primary: bool, mode: Mode | None) -> dict:
    return {
        "device": disp.device,
        "monitor_id": disp.monitor_id,
        "name": disp.name,
        "active": active,
        "primary": primary,
        "position": list(disp.position) if active else [0, 0],
        "mode": [mode.width, mode.height, mode.refresh] if mode else None,
    }


def suggested_profiles() -> list[dict]:
    """Monta perfis uteis a partir do que esta' conectado agora.

    Sao tres familias: o estado atual como ponto de retorno, uma tela sozinha
    para cada monitor, e todas ligadas. "Sozinha" e' o caso que importa quando ha'
    uma TV noutro comodo, porque leva o desktop inteiro para la'.
    """
    found = list_displays()
    if not found:
        return []
    profiles: list[dict] = []

    active = [d for d in found if d.active]
    if active:
        profiles.append({
            "name": "Trabalho",
            "hotkey": "",
            "entries": [_entry(d, d.active, d.primary, d.mode) for d in found],
        })

    for disp in found:
        best = _best_mode(disp.device) or disp.mode
        profiles.append({
            "name": f"Só {disp.name}",
            "hotkey": "",
            "entries": [_entry(d, d is disp, d is disp, best if d is disp else None)
                        for d in found],
        })

    if len(found) > 1:
        profiles.append({
            "name": "Todas as telas",
            "hotkey": "",
            "entries": [_entry(d, True, d.primary, _best_mode(d.device) or d.mode)
                        for d in found],
        })
    return profiles


def snapshot() -> list[dict]:
    """Estado atual num formato serializavel, pronto pro settings.json."""
    return [
        {
            "device": d.device,
            "monitor_id": d.monitor_id,
            "name": d.name,
            "active": d.active,
            "primary": d.primary,
            "position": list(d.position),
            "mode": [d.mode.width, d.mode.height, d.mode.refresh] if d.mode else None,
        }
        for d in list_displays(with_modes=False)
    ]
