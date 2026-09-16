"""Le controles da Sony por HID e entrega o estado no formato do XInput.

O XInput so' aceita dispositivo Xbox-compativel. Um DualSense pareado direto por
Bluetooth nao passa por ele: o Windows o expoe como HID comum, e o app ficava
cego para um controle que esta' ali, ligado e funcionando: a queixa de que "o
Vantage nao reconhece o controle".

A saida usada por todo mundo e' instalar um tradutor (DS4Windows, DsHidMini) que
cria um controle XInput virtual num driver de kernel. Aqui nao: o relatorio de
entrada do DualSense e' publico e curto, e ler ele direto evita pendurar um
driver de terceiros na maquina do usuario so' para mover um cursor.

O estado sai como `XINPUT_GAMEPAD` de proposito. Todo o resto do app (modo
mouse, grade do Big Picture, desenho da tela do controle) ja' fala essa
estrutura, e traduzir aqui na entrada deixa tudo isso funcionando sem tocar em
uma linha sequer.

Sem vibracao: ela exige relatorio de SAIDA, com CRC proprio no caminho Bluetooth.
Ler e' o que faz o controle servir; vibrar e' confirmacao, e some em silencio.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from .. import log
from .gamepad import (
    BTN_A,
    BTN_B,
    BTN_BACK,
    BTN_DPAD_DOWN,
    BTN_DPAD_LEFT,
    BTN_DPAD_RIGHT,
    BTN_DPAD_UP,
    BTN_LB,
    BTN_LTHUMB,
    BTN_RB,
    BTN_RTHUMB,
    BTN_START,
    BTN_X,
    BTN_Y,
    XINPUT_GAMEPAD,
)

_log = log.get("dualsense")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

SONY = 0x054C
SUPORTADOS = {0x0CE6, 0x0DF2, 0x09CC, 0x05C4, 0x0BA0}
"""DualSense, DualSense Edge e os DualShock 4, que usam o mesmo relatorio."""

_SIMPLES = 0x01
"""Relatorio que o controle manda sozinho, sem ninguem pedir nada.

O DualSense tem um relatorio estendido (0x31) com giroscopio, toque e bateria,
mas ele so' comeca depois de uma requisicao de feature. O 0x01 chega de graca
assim que o controle conecta, e traz tudo que um controle precisa ter: dois
analogicos, direcional, catorze botoes e dois gatilhos.
"""

_FACES = ((0x10, BTN_X), (0x20, BTN_A), (0x40, BTN_B), (0x80, BTN_Y))
"""Quadrado->X, Xis->A, Bola->B, Triangulo->Y.

O casamento e' por POSICAO no controle, e nao por nome: o Xis da Sony fica onde
fica o A do Xbox, e e' a posicao que a mao aprendeu. Casar por letra colocaria
"confirmar" no botao de cima.
"""

_OMBROS = ((0x01, BTN_LB), (0x02, BTN_RB), (0x10, BTN_BACK), (0x20, BTN_START),
           (0x40, BTN_LTHUMB), (0x80, BTN_RTHUMB))
"""L1, R1, Create->Back, Options->Start, L3, R3.

L2 e R2 (0x04 e 0x08) ficam de fora: eles sao analogicos e entram pelos bytes
proprios de pressao, senao o gatilho perderia o meio do curso.
"""

_HAT = {
    0: BTN_DPAD_UP,
    1: BTN_DPAD_UP | BTN_DPAD_RIGHT,
    2: BTN_DPAD_RIGHT,
    3: BTN_DPAD_DOWN | BTN_DPAD_RIGHT,
    4: BTN_DPAD_DOWN,
    5: BTN_DPAD_DOWN | BTN_DPAD_LEFT,
    6: BTN_DPAD_LEFT,
    7: BTN_DPAD_UP | BTN_DPAD_LEFT,
}
"""O direcional vem como bussola de 0 a 7, e 8 quer dizer solto.

As diagonais acendem os dois lados, que e' como o XInput representa a mesma
coisa: assim `nav_direction` resolve diagonal do mesmo jeito nos dois controles.
"""

_RESCAN_S = 2.0
"""Intervalo entre varreduras por controle novo. Conectar nao e' evento urgente,
e a varredura HID abre um handle por periferico da maquina."""


def _eixo(valor: int) -> int:
    """Converte eixo de 0..255 para o -32768..32767 do XInput.

    O fator e' 256, e nao 258 nem 257: o byte anda de -128 a +127 em volta do
    meio, e so' 256 cabe inteiro no destino. Com 258 o extremo dava -33024, que
    NAO cabe num `c_short`: o ctypes trunca em silencio e o numero volta
    positivo, entao o analogico empurrado todo para a esquerda pulava para a
    direita. O cursor ficava saltando entre os cantos da tela.

    O 128 do meio vira exatamente 0: qualquer resto e' deriva, e deriva num eixo
    que comanda o cursor e' o cursor andando sozinho.
    """
    return (valor - 128) * 256


class Leitor:
    """Um controle aberto, lido por uma thread propria.

    A leitura e' bloqueante de proposito. `ReadFile` num HID dorme ate' o
    controle falar, o que entrega cada relatorio na hora e sem gastar CPU
    perguntando. Fazer isso no laco da interface congelaria a janela inteira
    entre dois relatorios, entao a thread existe para carregar o bloqueio.
    """

    def __init__(self, path: str, tamanho: int, nome: str = "") -> None:
        self.path = path
        self.nome = nome or "controle Sony"
        self._tamanho = max(16, tamanho)
        self._handle = None
        self._estado = XINPUT_GAMEPAD()
        self._vivo = False
        self._thread: threading.Thread | None = None

    def abrir(self) -> bool:
        handle = kernel32.CreateFileW(self.path, GENERIC_READ,
                                      FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                      OPEN_EXISTING, 0, None)
        if handle == INVALID_HANDLE_VALUE:
            _log.debug("nao consegui abrir %s: %s", self.nome, ctypes.get_last_error())
            return False
        self._handle = handle
        self._vivo = True
        self._thread = threading.Thread(target=self._laco, name="dualsense",
                                        daemon=True)
        self._thread.start()
        _log.info("%s aberto por HID", self.nome)
        return True

    def fechar(self) -> None:
        """Fecha o handle e deixa a thread morrer sozinha.

        Fechar por baixo de um `ReadFile` bloqueado e' justamente o que o
        desbloqueia: a chamada falha, o laco ve' que nao esta' mais vivo e sai.
        Nao ha' como interromper a leitura de outro jeito.
        """
        self._vivo = False
        handle, self._handle = self._handle, None
        if handle is not None:
            kernel32.CloseHandle(handle)

    @property
    def vivo(self) -> bool:
        return self._vivo

    @property
    def estado(self) -> XINPUT_GAMEPAD:
        return self._estado

    def _laco(self) -> None:
        buf = ctypes.create_string_buffer(self._tamanho)
        lidos = wintypes.DWORD()
        while self._vivo:
            handle = self._handle
            if handle is None:
                break
            ok = kernel32.ReadFile(handle, buf, self._tamanho,
                                   ctypes.byref(lidos), None)
            if not ok or lidos.value < 10:
                break
            dados = bytes(buf)[:lidos.value]
            if dados[0] != _SIMPLES:
                continue
            novo = self._decodificar(dados)
            if novo is not None:
                # Troca a referencia inteira, sem trava. O leitor da interface
                # sempre pega um relatorio completo: ou o de antes, ou o de
                # agora, nunca metade de cada.
                self._estado = novo
        self._vivo = False
        _log.info("%s desconectou", self.nome)

    @staticmethod
    def _decodificar(d: bytes) -> XINPUT_GAMEPAD | None:
        if len(d) < 10:
            return None
        pad = XINPUT_GAMEPAD()

        botoes = 0
        for mask, bit in _FACES:
            if d[5] & mask:
                botoes |= bit
        for mask, bit in _OMBROS:
            if d[6] & mask:
                botoes |= bit
        botoes |= _HAT.get(d[5] & 0x0F, 0)
        pad.wButtons = botoes

        pad.bLeftTrigger = d[8]
        pad.bRightTrigger = d[9]
        pad.sThumbLX = _eixo(d[1])
        # O eixo Y do HID cresce para BAIXO e o do XInput para CIMA. Sem inverter,
        # empurrar o analogico para cima desceria o cursor.
        pad.sThumbLY = -_eixo(d[2]) - 1
        pad.sThumbRX = _eixo(d[3])
        pad.sThumbRY = -_eixo(d[4]) - 1
        return pad


class Conjunto:
    """Todos os controles Sony conectados, abertos sob demanda.

    Guarda os leitores entre varreduras: reabrir o dispositivo a cada volta do
    laco perderia relatorio e piscaria o controle como se ele tivesse caido.
    """

    def __init__(self) -> None:
        self._leitores: dict[str, Leitor] = {}
        self._ultima_busca = 0.0

    def estados(self) -> list[XINPUT_GAMEPAD]:
        """Estado de cada controle Sony vivo agora."""
        self._sincronizar()
        return [le.estado for le in self._leitores.values() if le.vivo]

    @property
    def nomes(self) -> list[str]:
        return [le.nome for le in self._leitores.values() if le.vivo]

    def parar(self) -> None:
        for leitor in self._leitores.values():
            leitor.fechar()
        self._leitores.clear()

    def _sincronizar(self) -> None:
        for path, leitor in list(self._leitores.items()):
            if not leitor.vivo:
                leitor.fechar()
                del self._leitores[path]

        agora = time.monotonic()
        if agora - self._ultima_busca < _RESCAN_S:
            return
        self._ultima_busca = agora

        from . import pads as P

        try:
            achados = P.list_pads()
        except OSError:
            return
        for pad in achados:
            if pad.vid != SONY or pad.pid not in SUPORTADOS:
                continue
            # Controle da Sony que JA' fala XInput esta' atras de um tradutor
            # instalado pelo usuario. Ler os dois lados dobraria cada botao.
            if pad.xinput or pad.path in self._leitores:
                continue
            leitor = Leitor(pad.path, P.input_report_length(pad.path), pad.name)
            if leitor.abrir():
                self._leitores[pad.path] = leitor
