"""CCD API: `QueryDisplayConfig` e `SetDisplayConfig`, a camada moderna de telas.

E' a API que o proprio app de Configuracoes do Windows usa, e a unica confiavel
para ligar, desligar e reordenar telas no Windows 10 e 11.

O caminho legado `ChangeDisplaySettingsEx` com CDS_UPDATEREGISTRY foi tentado
antes e nao serve: ele aceita CDS_TEST, aceita mudanca dinamica, mas recusa a
gravacao com DISP_CHANGE_FAILED, com ou sem elevacao. Pior, encenar com
CDS_NORESET e nao aplicar deixa transacao pendente no registro que uma chamada
posterior aplica sozinha. Ele continua util so' para trocar resolucao e taxa de
uma tela ja' anexada, que e' um cenario ainda suportado.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from .. import log

_log = log.get("ccd")

user32 = ctypes.WinDLL("user32", use_last_error=True)

QDC_ALL_PATHS = 0x00000001
QDC_ONLY_ACTIVE_PATHS = 0x00000002

SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x00000020
SDC_VALIDATE = 0x00000040
SDC_APPLY = 0x00000080
SDC_SAVE_TO_DATABASE = 0x00000200
SDC_ALLOW_CHANGES = 0x00000400
SDC_ALLOW_PATH_ORDER_CHANGES = 0x00002000

SDC_TOPOLOGY_INTERNAL = 0x00000001
SDC_TOPOLOGY_CLONE = 0x00000002
SDC_TOPOLOGY_EXTEND = 0x00000004
SDC_TOPOLOGY_EXTERNAL = 0x00000008

TOPOLOGY_MODES = {
    "clone": SDC_TOPOLOGY_CLONE,
    "extend": SDC_TOPOLOGY_EXTEND,
    "internal": SDC_TOPOLOGY_INTERNAL,
    "external": SDC_TOPOLOGY_EXTERNAL,
}

DISPLAYCONFIG_PATH_ACTIVE = 0x00000001
DISPLAYCONFIG_PATH_MODE_IDX_INVALID = 0xFFFFFFFF

DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
DISPLAYCONFIG_MODE_INFO_TYPE_TARGET = 2

_INFO_GET_SOURCE_NAME = 1
_INFO_GET_TARGET_NAME = 2

ERROR_SUCCESS = 0
_ERRORS = {
    0: "ok",
    87: "parametro invalido",
    5: "acesso negado",
    31: "o driver recusou a configuracao",
    1004: "flags invalidas",
    1610: "configuracao invalida",
    1611: "topologia invalida",
}


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    def key(self) -> tuple[int, int]:
        return (self.LowPart, self.HighPart)


class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECTL(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.DWORD), ("Denominator", wintypes.DWORD)]

    @property
    def hz(self) -> int:
        if not self.Denominator:
            return 0
        return round(self.Numerator / self.Denominator)


class REGION2D(ctypes.Structure):
    _fields_ = [("cx", wintypes.DWORD), ("cy", wintypes.DWORD)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", wintypes.DWORD),
                ("modeInfoIdx", wintypes.DWORD), ("statusFlags", wintypes.DWORD)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
        ("modeInfoIdx", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD),
        ("rotation", wintypes.DWORD),
        ("scaling", wintypes.DWORD),
        ("refreshRate", RATIONAL),
        ("scanLineOrdering", wintypes.DWORD),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.DWORD),
    ]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE_INFO), ("targetInfo", PATH_TARGET_INFO),
                ("flags", wintypes.DWORD)]

    @property
    def active(self) -> bool:
        return bool(self.flags & DISPLAYCONFIG_PATH_ACTIVE)


class VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [
        ("pixelRate", ctypes.c_uint64),
        ("hSyncFreq", RATIONAL),
        ("vSyncFreq", RATIONAL),
        ("activeSize", REGION2D),
        ("totalSize", REGION2D),
        ("videoStandard", wintypes.DWORD),
        ("scanLineOrdering", wintypes.DWORD),
    ]


class TARGET_MODE(ctypes.Structure):
    _fields_ = [("targetVideoSignalInfo", VIDEO_SIGNAL_INFO)]


class SOURCE_MODE(ctypes.Structure):
    _fields_ = [("width", wintypes.DWORD), ("height", wintypes.DWORD),
                ("pixelFormat", wintypes.DWORD), ("position", POINTL)]


class DESKTOP_IMAGE_INFO(ctypes.Structure):
    _fields_ = [("PathSourceSize", POINTL), ("DesktopImageRegion", RECTL),
                ("DesktopImageClip", RECTL)]


class _MODE_UNION(ctypes.Union):
    _fields_ = [("targetMode", TARGET_MODE), ("sourceMode", SOURCE_MODE),
                ("desktopImageInfo", DESKTOP_IMAGE_INFO)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", wintypes.DWORD), ("id", wintypes.DWORD),
                ("adapterId", LUID), ("u", _MODE_UNION)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("size", wintypes.DWORD),
                ("adapterId", LUID), ("id", wintypes.DWORD)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER),
                ("viewGdiDeviceName", wintypes.WCHAR * 32)]


class TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DEVICE_INFO_HEADER),
        ("flags", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD),
        ("edidManufactureId", wintypes.WORD),
        ("edidProductCodeId", wintypes.WORD),
        ("connectorInstance", wintypes.DWORD),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]


user32.GetDisplayConfigBufferSizes.restype = wintypes.LONG
user32.GetDisplayConfigBufferSizes.argtypes = [
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
user32.QueryDisplayConfig.restype = wintypes.LONG
user32.QueryDisplayConfig.argtypes = [
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(PATH_INFO),
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(MODE_INFO), ctypes.c_void_p]
user32.SetDisplayConfig.restype = wintypes.LONG
user32.SetDisplayConfig.argtypes = [
    wintypes.DWORD, ctypes.POINTER(PATH_INFO), wintypes.DWORD,
    ctypes.POINTER(MODE_INFO), wintypes.DWORD]
user32.DisplayConfigGetDeviceInfo.restype = wintypes.LONG
user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.POINTER(DEVICE_INFO_HEADER)]


def message(code: int) -> str:
    return _ERRORS.get(code, f"codigo {code}")


@dataclass
class Config:
    """Uma leitura completa da configuracao de telas, pronta para ser devolvida."""

    paths: ctypes.Array
    modes: ctypes.Array
    path_count: int
    mode_count: int

    def active_paths(self):
        return [p for p in self.paths[:self.path_count] if p.active]


def query(all_paths: bool = True) -> Config | None:
    """Le a configuracao atual. Com `all_paths` traz tambem as telas desligadas."""
    flags = QDC_ALL_PATHS if all_paths else QDC_ONLY_ACTIVE_PATHS
    n_paths = wintypes.DWORD()
    n_modes = wintypes.DWORD()
    rc = user32.GetDisplayConfigBufferSizes(flags, ctypes.byref(n_paths), ctypes.byref(n_modes))
    if rc != ERROR_SUCCESS:
        _log.warning("GetDisplayConfigBufferSizes falhou: %s", message(rc))
        return None

    paths = (PATH_INFO * n_paths.value)()
    modes = (MODE_INFO * n_modes.value)()
    rc = user32.QueryDisplayConfig(flags, ctypes.byref(n_paths), paths,
                                   ctypes.byref(n_modes), modes, None)
    if rc != ERROR_SUCCESS:
        _log.warning("QueryDisplayConfig falhou: %s", message(rc))
        return None
    return Config(paths, modes, n_paths.value, n_modes.value)


def source_name(path: PATH_INFO) -> str:
    """Nome GDI da fonte, tipo \\\\.\\DISPLAY1."""
    req = SOURCE_DEVICE_NAME()
    req.header.type = _INFO_GET_SOURCE_NAME
    req.header.size = ctypes.sizeof(SOURCE_DEVICE_NAME)
    req.header.adapterId = path.sourceInfo.adapterId
    req.header.id = path.sourceInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(req.header)) != ERROR_SUCCESS:
        return ""
    return req.viewGdiDeviceName


def target_name(path: PATH_INFO) -> tuple[str, str]:
    """Devolve (nome amigavel do monitor, caminho do dispositivo)."""
    req = TARGET_DEVICE_NAME()
    req.header.type = _INFO_GET_TARGET_NAME
    req.header.size = ctypes.sizeof(TARGET_DEVICE_NAME)
    req.header.adapterId = path.targetInfo.adapterId
    req.header.id = path.targetInfo.id
    if user32.DisplayConfigGetDeviceInfo(ctypes.byref(req.header)) != ERROR_SUCCESS:
        return "", ""
    return req.monitorFriendlyDeviceName, req.monitorDevicePath


def apply(config: Config, validate_first: bool = True) -> tuple[bool, str]:
    """Grava a configuracao e persiste no banco de dados de telas do Windows.

    Valida antes de aplicar, porque uma topologia invalida rejeitada na validacao
    nao chega a mexer na tela. Sem isso o usuario ve a tela piscar para nada.
    """
    base = SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES
    # Sem modos a API exige ponteiro nulo, nao um array de tamanho zero. Um array
    # vazio ainda e' um endereco valido e a chamada volta com parametro invalido.
    modes = config.modes if config.mode_count else None
    if validate_first:
        rc = user32.SetDisplayConfig(config.path_count, config.paths,
                                     config.mode_count, modes, base | SDC_VALIDATE)
        if rc != ERROR_SUCCESS:
            return False, message(rc)
    rc = user32.SetDisplayConfig(config.path_count, config.paths,
                                 config.mode_count, modes,
                                 base | SDC_APPLY | SDC_SAVE_TO_DATABASE)
    return (rc == ERROR_SUCCESS), message(rc)


def _source_key(path: PATH_INFO) -> tuple:
    return (path.sourceInfo.adapterId.key(), path.sourceInfo.id)


def _candidate(cfg: Config, monitor_path: str, used: set[tuple]) -> PATH_INFO | None:
    """Melhor caminho inativo para essa tela.

    Prefere um com origem livre, mas aceita conflito: `_rebuild` remaneja a
    origem e o `SDC_ALLOW_CHANGES` deixa o Windows ajustar o resto. Recusar de
    saida era o que fazia a segunda tela ficar apagada ao voltar do jogo.
    """
    reserva = None
    for i in range(cfg.path_count):
        path = cfg.paths[i]
        if path.active:
            continue
        _, device_path = target_name(path)
        if device_path != monitor_path:
            continue
        if _source_key(path) not in used:
            return path
        if reserva is None:
            reserva = path
    return reserva


def _free_source(adapter, usados: set[tuple]) -> int:
    chave = adapter.key()
    for sid in range(16):
        if (chave, sid) not in usados:
            return sid
    return 0


def _rebuild(chosen: list[PATH_INFO]) -> Config:
    """Monta uma topologia so' com os caminhos escolhidos, sem fixar modos.

    Os indices de modo vao como invalidos de proposito: assim o Windows escolhe
    resolucao e posicao coerentes sozinho. Tentar ditar os modos aqui e' o que
    torna a chamada fragil, porque qualquer combinacao invalida derruba tudo.

    Duas telas nao podem sair da mesma origem (fora do modo clone). Quando os
    caminhos disponiveis colidem, a origem repetida e' trocada por uma livre:
    sem isso a segunda tela simplesmente nao acende, que era o motivo de voltar
    do jogo com o ultrawide apagado.
    """
    array = (PATH_INFO * len(chosen))()
    usados: set[tuple] = set()
    for i, path in enumerate(chosen):
        array[i] = path
        array[i].flags |= DISPLAYCONFIG_PATH_ACTIVE
        array[i].sourceInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID
        array[i].targetInfo.modeInfoIdx = DISPLAYCONFIG_PATH_MODE_IDX_INVALID
        if _source_key(array[i]) in usados:
            array[i].sourceInfo.id = _free_source(array[i].sourceInfo.adapterId, usados)
        usados.add(_source_key(array[i]))
    return Config(array, (MODE_INFO * 0)(), len(chosen), 0)


def set_active(monitor_path: str, active: bool) -> tuple[bool, str]:
    """Liga ou desliga uma tela pela topologia, que e' a camada correta.

    A tela e' identificada pelo caminho do dispositivo, e nao por \\\\.\\DISPLAYn,
    porque o numero e' posicional e muda quando um cabo troca de saida.
    """
    cfg = query(all_paths=True)
    if cfg is None:
        return False, "nao consegui ler a configuracao de telas"

    chosen: list[PATH_INFO] = []
    used: set[tuple] = set()
    already = False

    for i in range(cfg.path_count):
        path = cfg.paths[i]
        if not path.active:
            continue
        _, device_path = target_name(path)
        if device_path == monitor_path:
            already = True
            if not active:
                continue
        chosen.append(path)
        used.add(_source_key(path))

    if active and not already:
        candidate = _candidate(cfg, monitor_path, used)
        if candidate is None:
            return False, "essa tela nao aparece mais na lista de caminhos do Windows"
        chosen.append(candidate)

    if not chosen:
        return False, "isso deixaria a maquina sem nenhuma tela ligada"
    if active == already and bool(chosen):
        if active:
            return True, "ja estava ligada"
    return apply(_rebuild(chosen))


def set_topology(wanted: list[str]) -> tuple[bool, str]:
    """Deixa ligadas exatamente as telas pedidas, numa unica troca.

    Uma chamada so' evita a tela piscar uma vez por monitor e evita estados
    intermediarios onde nenhuma tela esta' ligada.
    """
    if not wanted:
        return False, "isso deixaria a maquina sem nenhuma tela ligada"
    cfg = query(all_paths=True)
    if cfg is None:
        return False, "nao consegui ler a configuracao de telas"

    chosen: list[PATH_INFO] = []
    used: set[tuple] = set()
    pending = list(wanted)

    for i in range(cfg.path_count):
        path = cfg.paths[i]
        if not path.active:
            continue
        _, device_path = target_name(path)
        if device_path not in pending:
            continue
        pending.remove(device_path)
        chosen.append(path)
        used.add(_source_key(path))

    for device_path in list(pending):
        candidate = _candidate(cfg, device_path, used)
        if candidate is None:
            continue
        chosen.append(candidate)
        used.add(_source_key(candidate))
        pending.remove(device_path)

    if pending:
        _log.warning("telas do perfil sem caminho livre: %s", pending)
    if not chosen:
        return False, "nenhuma tela do perfil esta conectada"
    return apply(_rebuild(chosen))


def set_topology_mode(mode: str) -> tuple[bool, str]:
    """Aplica um dos modos prontos do Windows: clone, estender, so' uma ou outra.

    E' o mesmo que o Win+P faz. Aqui nao se passa caminho nenhum: o Windows monta
    a topologia sozinho a partir do que estiver conectado, o que e' justamente o
    que torna o modo clone confiavel sem precisar montar grupos de clone na mao.
    """
    flag = TOPOLOGY_MODES.get(mode)
    if flag is None:
        return False, f"modo desconhecido: {mode}"
    rc = user32.SetDisplayConfig(0, None, 0, None, SDC_APPLY | flag)
    return (rc == ERROR_SUCCESS), message(rc)


def set_positions(wanted: dict[str, tuple[int, int]]) -> tuple[bool, str]:
    """Move as telas no desktop virtual.

    O Windows exige que alguma tela fique em (0,0), entao no fim tudo e'
    transladado pelo canto superior esquerdo do conjunto. Sem isso a configuracao
    e' recusada inteira.
    """
    cfg = query(all_paths=False)
    if cfg is None:
        return False, "nao consegui ler a configuracao de telas"

    touched: dict[int, tuple[int, int]] = {}
    for path in cfg.active_paths():
        idx = path.sourceInfo.modeInfoIdx
        if idx == DISPLAYCONFIG_PATH_MODE_IDX_INVALID or idx >= cfg.mode_count:
            continue
        _, device_path = target_name(path)
        mode = cfg.modes[idx]
        if mode.infoType != DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
            continue
        pos = wanted.get(device_path)
        if pos is not None:
            mode.u.sourceMode.position.x, mode.u.sourceMode.position.y = pos
        touched[idx] = (mode.u.sourceMode.position.x, mode.u.sourceMode.position.y)

    if not touched:
        return False, "nenhuma tela ativa para posicionar"
    min_x = min(x for x, _ in touched.values())
    min_y = min(y for _, y in touched.values())
    if (min_x, min_y) != (0, 0):
        for idx in touched:
            cfg.modes[idx].u.sourceMode.position.x -= min_x
            cfg.modes[idx].u.sourceMode.position.y -= min_y
    return apply(cfg)


def make_primary(monitor_path: str) -> tuple[bool, str]:
    """Torna a tela primaria deslocando todas as posicoes ate' ela cair em (0,0).

    No Windows a primaria nao e' uma marca, e' simplesmente a tela cuja origem e'
    (0,0). Entao virar primaria significa mover o mundo inteiro em volta dela.
    """
    cfg = query(all_paths=False)
    if cfg is None:
        return False, "nao consegui ler a configuracao de telas"

    anchor = None
    for path in cfg.active_paths():
        _, device_path = target_name(path)
        if device_path == monitor_path:
            anchor = source_mode(cfg, path)
            break
    if anchor is None:
        return False, "tela nao esta ligada"
    dx, dy = anchor.position.x, anchor.position.y
    if (dx, dy) == (0, 0):
        return True, "ja era a primaria"

    seen: set[int] = set()
    for path in cfg.active_paths():
        idx = path.sourceInfo.modeInfoIdx
        if idx == DISPLAYCONFIG_PATH_MODE_IDX_INVALID or idx in seen:
            continue
        seen.add(idx)
        mode = cfg.modes[idx]
        if mode.infoType != DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
            continue
        mode.u.sourceMode.position.x -= dx
        mode.u.sourceMode.position.y -= dy
    return apply(cfg)


def source_mode(config: Config, path: PATH_INFO) -> SOURCE_MODE | None:
    idx = path.sourceInfo.modeInfoIdx
    if idx == DISPLAYCONFIG_PATH_MODE_IDX_INVALID or idx >= config.mode_count:
        return None
    info = config.modes[idx]
    if info.infoType != DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE:
        return None
    return info.u.sourceMode
