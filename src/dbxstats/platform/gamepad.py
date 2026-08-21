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
VK_F4 = 0x73
VK_SPACE = 0x20
VK_APPS = 0x5D              # tecla de menu de contexto
VK_D = 0x44
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT = 0xB0
VK_MEDIA_PREV = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

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
def tap_alt_tab() -> None:
    """Alterna janelas. Sentado no sofa e' a acao mais usada depois do clique."""
    _send(_key(VK_MENU, False), _key(VK_TAB, False),
          _key(VK_TAB, True), _key(VK_MENU, True))


def tap_win() -> None:
    _send(_key(VK_LWIN, False), _key(VK_LWIN, True))


def _combo(modificador: int, tecla: int) -> None:
    _send(_key(modificador, False), _key(tecla, False),
          _key(tecla, True), _key(modificador, True))


def show_desktop() -> None:
    """Win+D. Sentado no sofa e' a saida de emergencia: seja la' o que esteja na
    frente, uma apertada devolve a area de trabalho."""
    _combo(VK_LWIN, VK_D)


def task_view() -> None:
    _combo(VK_LWIN, VK_TAB)


def close_window() -> None:
    _combo(VK_MENU, VK_F4)


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


NAV_DEADZONE = 16000
"""Zona morta da navegacao, bem maior que a do cursor.

Mover o foco e' passo discreto: com a zona morta do cursor, um analogico
descansando torto ja' pularia de card sozinho."""


def nav_direction(pad, deadzone: int = NAV_DEADZONE) -> str:
    """Para onde o foco deve andar: "", "up", "down", "left" ou "right".

    Direcional e analogico esquerdo valem igual. Diagonal resolve pelo eixo de
    maior deflexao, senao um empurrao torto viraria dois passos de uma vez.
    """
    b = pad.wButtons
    if b & BTN_DPAD_UP:
        return "up"
    if b & BTN_DPAD_DOWN:
        return "down"
    if b & BTN_DPAD_LEFT:
        return "left"
    if b & BTN_DPAD_RIGHT:
        return "right"
    x, y = pad.sThumbLX, pad.sThumbLY
    if abs(x) < deadzone and abs(y) < deadzone:
        return ""
    if abs(x) >= abs(y):
        return "right" if x > 0 else "left"
    return "up" if y > 0 else "down"


def _tap(vk: int):
    return lambda: _send(_key(vk, False), _key(vk, True))


ACTIONS: dict[str, tuple[str, object]] = {
    "": ("Nada", None),
    "click_left": ("Clique esquerdo", (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)),
    "click_right": ("Clique direito", (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)),
    "click_middle": ("Clique do meio", (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP)),
    "key_enter": ("Enter", VK_RETURN),
    "key_esc": ("Esc, volta", VK_ESCAPE),
    "key_back": ("Backspace, apaga", VK_BACK),
    "key_delete": ("Delete", VK_DELETE),
    "key_tab": ("Tab", VK_TAB),
    "key_space": ("Espaço", VK_SPACE),
    "key_up": ("Seta acima", VK_UP),
    "key_down": ("Seta abaixo", VK_DOWN),
    "key_left": ("Seta esquerda", VK_LEFT),
    "key_right": ("Seta direita", VK_RIGHT),
    "key_menu": ("Menu de contexto", VK_APPS),
    "win": ("Menu Iniciar", tap_win),
    "desktop": ("Área de trabalho (Win+D)", show_desktop),
    "alt_tab": ("Alt+Tab, troca de janela", tap_alt_tab),
    "task_view": ("Visão de tarefas (Win+Tab)", task_view),
    "close_window": ("Fechar a janela (Alt+F4)", close_window),
    "osk": ("Teclado virtual", toggle_osk),
    "vol_up": ("Volume +", _tap(VK_VOLUME_UP)),
    "vol_down": ("Volume −", _tap(VK_VOLUME_DOWN)),
    "vol_mute": ("Mudo", _tap(VK_VOLUME_MUTE)),
    "media_play": ("Tocar / pausar", _tap(VK_MEDIA_PLAY_PAUSE)),
    "media_next": ("Faixa seguinte", _tap(VK_MEDIA_NEXT)),
    "media_prev": ("Faixa anterior", _tap(VK_MEDIA_PREV)),
    "scroll_up": ("Rolar para cima", "scroll_up"),
    "scroll_down": ("Rolar para baixo", "scroll_down"),
}
"""Tudo que um botao pode fazer, com o nome que aparece na interface.

Cada valor diz *como* a acao e' executada, e o laco decide por isso: par de
flags e' botao de mouse (segura enquanto o botao estiver apertado), inteiro e'
tecla (idem), texto e' rolagem continua e funcao e' disparo unico na descida.
"""

# Controle do sofa: o PC inteiro na mao, sem teclado por perto. A ideia por tras
# das escolhas: os dois botoes de baixo sao os cliques (e' o que mais se faz),
# os de cima sao navegacao entre janelas, o gatilho direito e' a saida rapida
# para a area de trabalho e o direcional anda pela interface.
DEFAULT_BINDINGS: dict[str, str] = {
    "A": "click_left",
    "B": "click_right",
    "X": "key_back",
    "Y": "key_esc",
    "LB": "alt_tab",
    "RB": "win",
    "L3": "osk",
    "R3": "click_middle",
    "Start": "key_enter",
    # Back fica livre de proposito: ele forma o combo que assume e devolve o
    # mouse, e apertar os dois botoes nunca sai perfeitamente junto. Com uma
    # acao aqui, o caminho ate' o combo dispararia ela toda vez — Alt+F4 era o
    # padrao anterior, e fechar a janela sem querer e' o pior jeito de descobrir
    # isso. Quem quiser pode escolher uma na tela do controle.
    "Back": "",
    # Os gatilhos sozinhos ficam livres de proposito. Win+D e' um INTERRUPTOR:
    # aperta uma vez e a area de trabalho aparece, aperta de novo e as janelas
    # voltam — o jogo junto. Num gatilho, que e' analogico e dispara com um
    # roçar, isso virava "o jogo volta sozinho toda hora".
    "LT": "",
    "RT": "",
    "LT+RT": "desktop",
    "Direcional ↑": "key_up",
    "Direcional ↓": "key_down",
    "Direcional ←": "key_left",
    "Direcional →": "key_right",
}

TRIGGERS = ("LT", "RT", "LT+RT")
"""Gatilhos: analogicos, mas tratados como botao a partir de um limiar."""

BUTTON_NAMES = {
    BTN_A: "A", BTN_B: "B", BTN_X: "X", BTN_Y: "Y",
    BTN_LB: "LB", BTN_RB: "RB", BTN_BACK: "Back", BTN_START: "Start",
    BTN_LTHUMB: "L3", BTN_RTHUMB: "R3",
    BTN_DPAD_UP: "Direcional ↑", BTN_DPAD_DOWN: "Direcional ↓",
    BTN_DPAD_LEFT: "Direcional ←", BTN_DPAD_RIGHT: "Direcional →",
}

MASK_BY_NAME = {nome: mask for mask, nome in BUTTON_NAMES.items()}

BUTTON_ORDER = ("A", "B", "X", "Y", "LB", "RB", "LT", "RT", "LT+RT",
                "L3", "R3", "Back", "Start",
                "Direcional ↑", "Direcional ↓", "Direcional ←", "Direcional →")
"""Ordem em que os botoes aparecem na tela de configuracao."""


def action_label(action: str) -> str:
    return ACTIONS.get(action, ("desconhecida", None))[0]


def bindings_from(cfg) -> dict[str, str]:
    """Mapa em uso: o padrao com as trocas do usuario por cima.

    Partir do padrao a cada leitura e' de proposito. Assim um botao que o
    usuario nunca tocou continua acompanhando o padrao quando ele melhora, e
    uma configuracao antiga nao deixa botao novo sem funcao nenhuma.
    """
    mapa = dict(DEFAULT_BINDINGS)
    for nome, acao in (getattr(cfg, "gamepad_bindings", None) or {}).items():
        if nome in mapa and acao in ACTIONS:
            mapa[nome] = acao
    return mapa


def describe(cfg=None) -> list[tuple[str, str]]:
    """Mapa do controle montado a partir do mapeamento real.

    Nasce do proprio mapeamento de proposito: uma lista escrita a mao na
    interface envelhece calada toda vez que alguem remapeia um botao.
    """
    mapa = bindings_from(cfg) if cfg is not None else dict(DEFAULT_BINDINGS)
    linhas: list[tuple[str, str]] = [
        ("Analógico esquerdo", "Move o cursor"),
        ("Analógico direito", "Rola a página"),
    ]
    for nome in BUTTON_ORDER:
        acao = mapa.get(nome, "")
        if acao:
            linhas.append((nome, action_label(acao)))
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
        self._held: dict[str, bool] = {}
        self._bindings = bindings_from(settings)
        self._combo_held = False
        """Back+Start ainda esta' pressionado; segura a borda ate' soltar."""
        self._last_packet = 0
        self._scroll_carry = 0.0
        self._hscroll_carry = 0.0
        self._last_seek = 0.0
        self._gate = None
        """Callable opcional que decide se o modo mouse pode assumir agora."""
        self._consumer = None
        """Quem assumiu o controle inteiro; ver set_consumer."""

    # ── ciclo ────────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not available():
            _log.warning("XInput indisponivel, controle como mouse desligado")
            return
        self._timer.start(_IDLE_POLL_MS)

    def stop(self) -> None:
        self._timer.stop()
        self._release_all()
        self._combo_held = False
        self._set_active(False)

    def set_consumer(self, fn) -> None:
        """Entrega o controle inteiro para outra tela, ou devolve com None.

        Um laco so', um dono. Um segundo leitor de XInput significaria dois
        donos do mesmo hardware disputando o mesmo estado a cada 8 ms.
        """
        self._consumer = fn
        if fn is not None:
            self._release_all()      # nada de tecla presa ao trocar de dono

    def deactivate(self) -> None:
        """Desliga o modo mouse sem alternar.

        toggle() nao serve para garantir estado: chamado com o modo ja' desligado
        ele LIGA. Quem entra numa tela propria precisa de "desligado", nao de
        "o contrario do que estava".
        """
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
        self._feedback(value)

    def _feedback(self, value: bool) -> None:
        """Um toque curto confirma a troca sem depender da tela, que no sofa pode
        estar longe ou mostrando outra coisa."""
        alvos = list(self.slots)
        rumble(alvos, 24000 if value else 0, 24000 if value else 12000)
        QTimer.singleShot(180, lambda: rumble(alvos, 0, 0))

    def _release_all(self) -> None:
        """Solta tudo que estava pressionado ao devolver o mouse.

        Sem isso, desligar o modo com um botao apertado deixaria a tecla ou o
        clique presos no Windows — e o usuario sem entender por que a maquina
        parou de responder.
        """
        for nome, held in list(self._held.items()):
            if not held:
                continue
            efeito = ACTIONS.get(self._bindings.get(nome, ""), ("", None))[1]
            if isinstance(efeito, tuple):
                _send(_mouse(efeito[1]))
            elif isinstance(efeito, int):
                _send(_key(efeito, True))
        self._held.clear()

    def reload_bindings(self) -> None:
        """Reaplica o mapeamento depois de o usuario mexer nele."""
        self._release_all()
        self._bindings = bindings_from(self.cfg)

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
        # Quem assumiu o controle recebe o estado cru e o laco para por aqui.
        # A checagem vem ANTES do combo de proposito: o combo roda mesmo com o
        # modo mouse desligado, e sem essa ordem apertar Back+Start dentro de uma
        # tela propria devolveria o cursor calado, por baixo dela.
        if self._consumer is not None:
            self._consumer(pad)
            return

        # O estado do combo vive fora de `_held` de proposito: desligar o modo mouse
        # chama `_release_all`, que zera `_held`. Com o combo guardado la', a borda
        # se perdia no mesmo instante e o proximo tick religava tudo — o atalho so'
        # ligava, nunca desligava.
        if self.cfg.gamepad_toggle_combo and (buttons & BTN_BACK) and (buttons & BTN_START):
            if not self._combo_held:
                self._combo_held = True
                self.toggle()
            return
        self._combo_held = False

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
        for nome, mask in MASK_BY_NAME.items():
            self._apply(nome, bool(buttons & mask))

    def _triggers(self, pad: XINPUT_GAMEPAD) -> None:
        """Gatilhos viram botao a partir de um limiar, e valem como qualquer outro.

        Os dois juntos formam um terceiro gesto, e quando ele acontece os dois
        sozinhos ficam calados: senao apertar o par dispararia tres acoes de uma
        vez, e ainda deixaria a de cada gatilho presa quando o par se desfizesse.
        """
        esq = pad.bLeftTrigger > TRIGGER_THRESHOLD
        dir_ = pad.bRightTrigger > TRIGGER_THRESHOLD
        juntos = esq and dir_
        self._apply("LT+RT", juntos)
        self._apply("LT", esq and not juntos)
        self._apply("RT", dir_ and not juntos)

    def _apply(self, nome: str, pressed: bool) -> None:
        """Executa a acao do botao conforme o tipo dela.

        Clique e tecla acompanham o botao (descem e sobem junto), rolagem repete
        enquanto estiver segurado, e o resto dispara so' na descida: repetir
        Alt+Tab a 125 vezes por segundo viraria uma enxurrada de trocas de
        janela.
        """
        efeito = ACTIONS.get(self._bindings.get(nome, ""), ("", None))[1]
        if efeito is None:
            return
        if efeito == "scroll_up" or efeito == "scroll_down":
            if pressed:
                scroll(WHEEL_DELTA if efeito == "scroll_up" else -WHEEL_DELTA)
            return
        antes = self._held.get(nome, False)
        if pressed == antes:
            return
        self._held[nome] = pressed
        if isinstance(efeito, tuple):
            _send(_mouse(efeito[0] if pressed else efeito[1]))
        elif isinstance(efeito, int):
            _send(_key(efeito, not pressed))
        elif pressed and callable(efeito):
            efeito()
