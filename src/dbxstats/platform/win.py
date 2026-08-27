"""Helpers win32 (ctypes) com prototypes corretos para x64 e multi-monitor."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

MONITOR_DEFAULTTONEAREST = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
MSGFLT_ALLOW = 1


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def _setup_prototypes() -> None:
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    if hasattr(user32, "GetWindowLongPtrW"):
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    shell32.IsUserAnAdmin.restype = wintypes.BOOL
    shell32.IsUserAnAdmin.argtypes = []


_setup_prototypes()


def _get_long(hwnd: int, idx: int) -> int:
    if hasattr(user32, "GetWindowLongPtrW"):
        return int(user32.GetWindowLongPtrW(hwnd, idx))
    return int(user32.GetWindowLongW(hwnd, idx))


def _set_long(hwnd: int, idx: int, value: int) -> int:
    if hasattr(user32, "SetWindowLongPtrW"):
        return int(user32.SetWindowLongPtrW(hwnd, idx, value))
    return int(user32.SetWindowLongW(hwnd, idx, value))


def keep_topmost(hwnd: int) -> None:
    if not hwnd:
        return
    user32.SetWindowPos(hwnd, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_as_admin(executable: str, params: str) -> bool:
    try:
        rc = shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


def foreground_hwnd() -> int:
    return user32.GetForegroundWindow() or 0


def window_pid(hwnd: int) -> int:
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground_pid() -> int:
    return window_pid(foreground_hwnd())


def _monitor_rect(hwnd: int) -> RECT | None:
    hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not hmon:
        return None
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    return mi.rcMonitor


def allow_drops_from_explorer(hwnd: int) -> None:
    """Libera arrastar-e-soltar do Explorer para uma janela executando como admin.

    O Windows bloqueia mensagens de um processo de integridade menor para um
    maior (UIPI). Como o DBX Stats se eleva para ler sensores, o Explorer (que
    roda sem elevacao) nao consegue entregar o arquivo arrastado: o cursor vira
    "proibido" e o drop simplesmente nao acontece. Liberar as tres mensagens do
    protocolo de drop e' o caminho oficial para esse caso.
    """
    if not hwnd:
        return
    for message in (0x0233, 0x0049, 0x004A):   # WM_DROPFILES, WM_COPYGLOBALDATA, WM_COPYDATA
        try:
            user32.ChangeWindowMessageFilterEx(hwnd, message, MSGFLT_ALLOW, None)
        except (AttributeError, OSError):       # Windows antigo: nada a fazer
            return


def foreground_monitor_rect() -> tuple[int, int, int, int] | None:
    """Retangulo do monitor onde esta' a janela em foco.

    E' o que diz em qual tela o overlay deve aparecer: com TV e monitores ligados
    ao mesmo tempo, colar sempre na primaria poe o overlay onde o jogo nao esta'.
    """
    hwnd = foreground_hwnd()
    if not hwnd:
        return None
    rc = _monitor_rect(hwnd)
    if rc is None:
        return None
    return (rc.left, rc.top, rc.right, rc.bottom)


def is_foreground_fullscreen() -> tuple[bool, int]:
    hwnd = foreground_hwnd()
    if not hwnd:
        return False, 0
    rc = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return False, hwnd
    mon = _monitor_rect(hwnd)
    if mon is None:
        return False, hwnd
    covers = (rc.left <= mon.left and rc.top <= mon.top
              and rc.right >= mon.right and rc.bottom >= mon.bottom)
    return covers, hwnd


def set_clickthrough(hwnd: int, enabled: bool = True) -> None:
    if not hwnd:
        return
    style = _get_long(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    _set_long(hwnd, GWL_EXSTYLE, style)


def set_tool_window(hwnd: int) -> None:
    if not hwnd:
        return
    style = _get_long(hwnd, GWL_EXSTYLE)
    _set_long(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)


SW_SHOWNORMAL = 1
SW_SHOWMAXIMIZED = 3
SW_SHOWMINIMIZED = 2
SWP_NOZORDER = 0x0004
WPF_ASYNCWINDOWPLACEMENT = 0x0004


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.GetWindowPlacement.restype = wintypes.BOOL
user32.SetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWPLACEMENT)]
user32.SetWindowPlacement.restype = wintypes.BOOL


def _movable(hwnd: int) -> bool:
    """Janela de aplicativo de verdade, com titulo e visivel.

    Sem esse filtro a varredura pega a area de trabalho, a barra de tarefas e
    dezenas de janelas invisiveis de servico, e mover qualquer uma delas quebra o
    shell.
    """
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.GetWindowTextLengthW(hwnd) == 0:
        return False
    style = _get_long(hwnd, GWL_EXSTYLE)
    return not (style & WS_EX_TOOLWINDOW)


def app_windows() -> list[int]:
    encontradas: list[int] = []

    def callback(hwnd, _):
        if _movable(hwnd):
            encontradas.append(int(hwnd))
        return True

    user32.EnumWindows(_ENUMPROC(callback), 0)
    return encontradas


def move_windows_to(target: tuple[int, int, int, int]) -> int:
    """Traz todas as janelas de aplicativo para dentro do retangulo dado.

    Janela maximizada e' tratada pela posicao normal guardada no
    WINDOWPLACEMENT, e volta a maximizar na tela nova. Mover uma maximizada
    direto com SetWindowPos nao funciona: o Windows a devolve para a tela antiga
    assim que ela for restaurada.

    Devolve quantas janelas foram movidas.
    """
    left, top, right, bottom = target
    largura, altura = right - left, bottom - top
    movidas = 0

    for hwnd in app_windows():
        place = WINDOWPLACEMENT()
        place.length = ctypes.sizeof(WINDOWPLACEMENT)
        if not user32.GetWindowPlacement(hwnd, ctypes.byref(place)):
            continue
        if place.showCmd == SW_SHOWMINIMIZED:
            continue

        rc = place.rcNormalPosition
        w = min(rc.right - rc.left, largura)
        h = min(rc.bottom - rc.top, altura)
        x = left + max(0, (largura - w) // 2) if w >= largura else \
            max(left, min(left + largura - w, left + (largura - w) // 2))
        y = max(top, min(top + altura - h, top + (altura - h) // 2))

        place.rcNormalPosition = RECT(x, y, x + w, y + h)
        place.flags |= WPF_ASYNCWINDOWPLACEMENT
        if user32.SetWindowPlacement(hwnd, ctypes.byref(place)):
            movidas += 1
    return movidas
