"""Controle como mouse e teclado, para usar o PC do sofa.

Le o controle com XInput e injeta entrada com `SendInput`, que e' a mesma dupla de
APIs que qualquer ferramenta do genero usa. Nada aqui e' derivado de codigo de
terceiros: a implementacao sai direto da documentacao do Win32, o que mantem o
projeto em MIT.

Suporta qualquer controle que o Windows exponha como XInput, o que inclui Xbox
360, Xbox One, Series e os DualShock e DualSense quando ha' uma camada XInput.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .. import log

_log = log.get("gamepad")

user32 = ctypes.WinDLL("user32", use_last_error=True)

_xinput = None
for _dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xinput = ctypes.WinDLL(_dll)
        break
    except OSError:
        continue

ERROR_SUCCESS = 0

BTN_DPAD_UP = 0x0001
BTN_DPAD_DOWN = 0x0002
BTN_DPAD_LEFT = 0x0004
BTN_DPAD_RIGHT = 0x0008
BTN_START = 0x0010
BTN_BACK = 0x0020
BTN_LTHUMB = 0x0040
BTN_RTHUMB = 0x0080
BTN_LB = 0x0100
BTN_RB = 0x0200
BTN_A = 0x1000
BTN_B = 0x2000
BTN_X = 0x4000
BTN_Y = 0x8000

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
KEYEVENTF_KEYUP = 0x0002
WHEEL_DELTA = 120

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_DELETE = 0x2E
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_LWIN = 0x5B
VK_TAB = 0x09
VK_MENU = 0x12

TRIGGER_THRESHOLD = 40
_POLL_MS = 8
_IDLE_POLL_MS = 1000


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", wintypes.WORD), ("wRightMotorSpeed", wintypes.WORD)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

if _xinput is not None:
    _xinput.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
    _xinput.XInputGetState.restype = wintypes.DWORD
    _xinput.XInputSetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_VIBRATION)]
    _xinput.XInputSetState.restype = wintypes.DWORD


def available() -> bool:
    return _xinput is not None


# ── injecao de entrada ───────────────────────────────────────────────────────
def _send(*inputs: INPUT) -> None:
    array = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    evt = INPUT(type=INPUT_MOUSE)
    evt.u.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    return evt


def _key(vk: int, up: bool) -> INPUT:
    evt = INPUT(type=INPUT_KEYBOARD)
    evt.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, None)
    return evt


def move_mouse(dx: int, dy: int) -> None:
    if dx or dy:
        _send(_mouse(MOUSEEVENTF_MOVE, dx, dy))


def scroll(amount: int, horizontal: bool = False) -> None:
    if amount:
        _send(_mouse(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, data=amount))


# ── laco de leitura ──────────────────────────────────────────────────────────
_MOUSE_BUTTONS = {
    BTN_A: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    BTN_B: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    BTN_RTHUMB: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# Backspace no X: e' o botao que cai debaixo do polegar sem largar o analogico,
# e apagar caractere e' o que mais se faz digitando no teclado virtual.
_KEY_BUTTONS = {
    BTN_X: VK_BACK,
    BTN_Y: VK_ESCAPE,
    BTN_START: VK_RETURN,
    BTN_DPAD_UP: VK_UP,
    BTN_DPAD_DOWN: VK_DOWN,
    BTN_DPAD_LEFT: VK_LEFT,
    BTN_DPAD_RIGHT: VK_RIGHT,
}


def tap_alt_tab() -> None:
    """Alterna janelas. Sentado no sofa e' a acao mais usada depois do clique."""
    _send(_key(VK_MENU, False), _key(VK_TAB, False),
          _key(VK_TAB, True), _key(VK_MENU, True))


def tap_win() -> None:
    _send(_key(VK_LWIN, False), _key(VK_LWIN, True))


def toggle_osk() -> None:
    """Abre o teclado virtual do Windows, para digitar sem sair do controle.

    O DBX Stats roda elevado, e dai' o `osk.exe` chamado direto costuma morrer
    calado: ele se recusa a subir no mesmo nivel de integridade. A saida e' pedir
    para o `explorer.exe` abrir, porque o explorer roda no nivel do usuario e o
    teclado nasce junto dele.

    Se ja' houver um teclado aberto, fecha. E' um botao de alternar, nao de abrir
    varios.
    """
    import subprocess

    for name in ("osk.exe", "TabTip.exe"):
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                                 capture_output=True, text=True, timeout=3)
            if name.lower() in out.stdout.lower():
                subprocess.run(["taskkill", "/F", "/IM", name],
                               capture_output=True, timeout=3)
                return
        except (OSError, subprocess.SubprocessError):
            pass

    osk = r"C:\Windows\System32\osk.exe"
    tabtip = r"C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe"
    for args in (["explorer.exe", osk], [osk], [tabtip]):
        try:
            subprocess.Popen(args, close_fds=True)
            return
        except OSError as e:
            _log.debug("teclado virtual via %s falhou: %s", args[0], e)
    _log.warning("nao consegui abrir nenhum teclado virtual")


def rumble(slots, left: int = 0, right: int = 0) -> None:
    """Vibra os controles indicados. Aceita um slot ou uma lista deles."""
    if _xinput is None:
        return
    if isinstance(slots, int):
        slots = [slots] if slots >= 0 else []
    vib = XINPUT_VIBRATION(max(0, min(65535, left)), max(0, min(65535, right)))
    for slot in slots:
        _xinput.XInputSetState(slot, ctypes.byref(vib))


def _merge(pads: list[XINPUT_GAMEPAD]) -> XINPUT_GAMEPAD:
    """Junta varios controles num so'.

    Botoes somam por OU, e nos eixos vence a maior deflexao. Assim dois controles
    nunca brigam pelo cursor: o que estiver sendo mexido manda.
    """
    out = XINPUT_GAMEPAD()
    for pad in pads:
        out.wButtons |= pad.wButtons
        out.bLeftTrigger = max(out.bLeftTrigger, pad.bLeftTrigger)
        out.bRightTrigger = max(out.bRightTrigger, pad.bRightTrigger)
        for eixo in ("sThumbLX", "sThumbLY", "sThumbRX", "sThumbRY"):
            atual, novo = getattr(out, eixo), getattr(pad, eixo)
            if abs(novo) > abs(atual):
                setattr(out, eixo, novo)
    return out


_ACTION_BUTTONS = {
    BTN_LB: tap_alt_tab,
    BTN_RB: tap_win,
    BTN_LTHUMB: toggle_osk,
}

BUTTON_NAMES = {
    BTN_A: "A", BTN_B: "B", BTN_X: "X", BTN_Y: "Y",
    BTN_LB: "LB", BTN_RB: "RB", BTN_BACK: "Back", BTN_START: "Start",
    BTN_LTHUMB: "L3", BTN_RTHUMB: "R3",
    BTN_DPAD_UP: "Direcional ↑", BTN_DPAD_DOWN: "Direcional ↓",
    BTN_DPAD_LEFT: "Direcional ←", BTN_DPAD_RIGHT: "Direcional →",
}

_VK_LABELS = {
    VK_BACK: "Backspace, apaga", VK_RETURN: "Enter", VK_ESCAPE: "Esc",
    VK_UP: "Seta acima", VK_DOWN: "Seta abaixo",
    VK_LEFT: "Seta esquerda", VK_RIGHT: "Seta direita",
}

_MOUSE_LABELS = {
    BTN_A: "Clique esquerdo", BTN_B: "Clique direito", BTN_RTHUMB: "Clique do meio",
}

_ACTION_LABELS = {
    BTN_LB: "Alt+Tab, troca de janela",
    BTN_RB: "Tecla Windows",
    BTN_LTHUMB: "Teclado virtual",
}


def describe() -> list[tuple[str, str]]:
    """Mapa do controle montado a partir das tabelas reais de mapeamento.

    Nasce do proprio codigo de proposito: um mapa escrito a mao na interface
    envelhece calado toda vez que alguem remapeia um botao.
    """
    linhas: list[tuple[str, str]] = [
        ("Analógico esquerdo", "Move o cursor"),
        ("Analógico direito", "Rola a página"),
    ]
    for mask, label in _MOUSE_LABELS.items():
        linhas.append((BUTTON_NAMES.get(mask, "?"), label))
    for mask, vk in _KEY_BUTTONS.items():
        linhas.append((BUTTON_NAMES.get(mask, "?"), _VK_LABELS.get(vk, "tecla")))
    for mask, _ in _ACTION_BUTTONS.items():
        linhas.append((BUTTON_NAMES.get(mask, "?"), _ACTION_LABELS.get(mask, "ação")))
    linhas.append(("Gatilho esquerdo", "Página acima"))
    linhas.append(("Gatilho direito", "Página abaixo"))
    linhas.append(("Back + Start", "Assume ou devolve o mouse"))
    return linhas


class GamepadMouse(QObject):
    """Transforma o controle em mouse enquanto estiver ativo.

    O laco roda com QTimer no thread da interface porque `XInputGetState` custa
    microssegundos quando ha' controle. Quando nao ha', a consulta e' cara, entao
    a cadencia cai para um por segundo ate' alguem conectar.
    """

    connected_changed = Signal(bool)
    active_changed = Signal(bool)

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = settings
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self.slots: list[int] = []
        """Slots XInput com controle conectado agora. Todos comandam o mouse."""
        self._connected = False
        self._active = False
        self.last: XINPUT_GAMEPAD | None = None
        self._held: dict[int, bool] = {}
        self._last_packet = 0
        self._scroll_carry = 0.0
        self._hscroll_carry = 0.0
        self._last_seek = 0.0
        self._gate = None
        """Callable opcional que decide se o modo mouse pode assumir agora."""

    # ── ciclo ────────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not available():
            _log.warning("XInput indisponivel, controle como mouse desligado")
            return
        self._timer.start(_IDLE_POLL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._release_all()
        self._set_active(False)

    def set_gate(self, fn) -> None:
        self._gate = fn

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self) -> None:
        self._set_active(not self._active)

    def _set_active(self, value: bool) -> None:
        if value == self._active:
            return
        if not value:
            self._release_all()
        self._active = value
        self.active_changed.emit(value)
        # Um toque curto confirma a troca sem depender da tela, que no sofa pode
        # estar longe ou mostrando outra coisa.
        alvos = list(self.slots)
        rumble(alvos, 24000 if value else 0, 24000 if value else 12000)
        QTimer.singleShot(180, lambda: rumble(alvos, 0, 0))

    def _release_all(self) -> None:
        for button, held in list(self._held.items()):
            if not held:
                continue
            if button in _MOUSE_BUTTONS:
                _send(_mouse(_MOUSE_BUTTONS[button][1]))
            elif button in _KEY_BUTTONS:
                _send(_key(_KEY_BUTTONS[button], True))
        self._held.clear()

    # ── leitura ──────────────────────────────────────────────────────────────
    def _read(self) -> XINPUT_GAMEPAD | None:
        """Le todos os controles conectados e funde num estado unico.

        Qualquer controle comanda o mouse, sem eleger um dono. E' o que faz
        sentido na sala: quem estiver com o controle na mao usa, sem menu de
        escolha no meio.

        Slots vazios so' sao varridos uma vez por segundo. `XInputGetState` num
        slot sem controle e' caro, e varrer os quatro a cada 8 ms custaria mais
        que todo o resto do laco junto.
        """
        now = time.monotonic()
        if now - self._last_seek >= 1.0:
            self._last_seek = now
            encontrados = []
            for slot in range(4):
                state = XINPUT_STATE()
                if _xinput.XInputGetState(slot, ctypes.byref(state)) == ERROR_SUCCESS:
                    encontrados.append(slot)
            self.slots = encontrados

        pads: list[XINPUT_GAMEPAD] = []
        vivos: list[int] = []
        for slot in self.slots:
            state = XINPUT_STATE()
            if _xinput.XInputGetState(slot, ctypes.byref(state)) == ERROR_SUCCESS:
                pads.append(state.Gamepad)
                vivos.append(slot)
        self.slots = vivos
        if not pads:
            return None
        return pads[0] if len(pads) == 1 else _merge(pads)

    def _tick(self) -> None:
        pad = self._read()
        # Guardado mesmo com o modo mouse desligado: a aba do controle desenha o
        # que esta' sendo apertado, e isso e' justamente como se confere que o
        # controle responde antes de entregar o cursor a ele.
        self.last = pad
        was = self._connected
        self._connected = pad is not None
        if was != self._connected:
            self.connected_changed.emit(self._connected)
            self._timer.setInterval(_POLL_MS if self._connected else _IDLE_POLL_MS)
            if not self._connected:
                self._set_active(False)
        if pad is None:
            return

        buttons = pad.wButtons
        if self.cfg.gamepad_toggle_combo and (buttons & BTN_BACK) and (buttons & BTN_START):
            if not self._held.get(-1):
                self._held[-1] = True
                self.toggle()
            return
        self._held[-1] = False

        if not self._active:
            return
        if self._gate is not None and not self._gate():
            return

        self._move(pad)
        self._scroll(pad)
        self._buttons(buttons)
        self._triggers(pad)

    # ── mapeamento ───────────────────────────────────────────────────────────
    def _axis(self, value: int) -> float:
        """Normaliza o eixo aplicando zona morta e curva quadratica.

        A curva deixa o movimento fino perto do centro e rapido no fim do curso,
        que e' o que torna mira de cursor tolerable num analogico.
        """
        dead = self.cfg.gamepad_deadzone
        magnitude = abs(value)
        if magnitude <= dead:
            return 0.0
        span = 32767 - dead
        norm = min((magnitude - dead) / span, 1.0)
        return (norm * norm) * (1 if value > 0 else -1)

    def _move(self, pad: XINPUT_GAMEPAD) -> None:
        speed = 22.0 * self.cfg.gamepad_speed
        dx = self._axis(pad.sThumbLX) * speed
        dy = -self._axis(pad.sThumbLY) * speed
        move_mouse(int(dx), int(dy))

    def _scroll(self, pad: XINPUT_GAMEPAD) -> None:
        speed = 0.6 * self.cfg.gamepad_scroll_speed
        self._scroll_carry += self._axis(pad.sThumbRY) * speed * WHEEL_DELTA
        self._hscroll_carry += self._axis(pad.sThumbRX) * speed * WHEEL_DELTA
        if abs(self._scroll_carry) >= WHEEL_DELTA:
            steps = int(self._scroll_carry / WHEEL_DELTA)
            scroll(steps * WHEEL_DELTA)
            self._scroll_carry -= steps * WHEEL_DELTA
        if abs(self._hscroll_carry) >= WHEEL_DELTA:
            steps = int(self._hscroll_carry / WHEEL_DELTA)
            scroll(steps * WHEEL_DELTA, horizontal=True)
            self._hscroll_carry -= steps * WHEEL_DELTA

    def _buttons(self, buttons: int) -> None:
        for mask, (down, up) in _MOUSE_BUTTONS.items():
            self._edge(buttons, mask, lambda f=down: _send(_mouse(f)),
                       lambda f=up: _send(_mouse(f)))
        for mask, vk in _KEY_BUTTONS.items():
            self._edge(buttons, mask, lambda v=vk: _send(_key(v, False)),
                       lambda v=vk: _send(_key(v, True)))
        # Acoes disparam so' na descida: repetir Alt+Tab enquanto o botao esta'
        # pressionado geraria uma enxurrada de trocas de janela.
        for mask, action in _ACTION_BUTTONS.items():
            self._edge(buttons, mask, action, lambda: None)

    def _edge(self, buttons: int, mask: int, on_press, on_release) -> None:
        pressed = bool(buttons & mask)
        if pressed and not self._held.get(mask):
            self._held[mask] = True
            on_press()
        elif not pressed and self._held.get(mask):
            self._held[mask] = False
            on_release()

    def _triggers(self, pad: XINPUT_GAMEPAD) -> None:
        """Gatilhos rolam pagina, que e' o gesto natural pra navegar deitado."""
        if pad.bRightTrigger > TRIGGER_THRESHOLD:
            scroll(-WHEEL_DELTA)
        elif pad.bLeftTrigger > TRIGGER_THRESHOLD:
            scroll(WHEEL_DELTA)
