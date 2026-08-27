"""Uma copia do app por vez, e a segunda traz a primeira para a frente.

Duas instancias nao apenas duplicam janela: elas se sabotam. Cada uma varre as
sessoes ETW procurando orfas e derruba a da outra, porque o nome carrega o pid e
uma nao reconhece a outra como legitima. O resultado e' um laco em que nenhuma
das duas consegue capturar quadros — e o log de cada uma acusa "acesso negado"
sem dizer que ha' outra copia no ar. Levou horas para ser identificado, olhando
contadores de tentativa intercalados no mesmo arquivo de log.

Dois objetos do Windows resolvem, e nenhum deles precisa de arquivo em disco:

  - um mutex nomeado diz "ja' tem alguem aqui". E' liberado pelo proprio kernel
    quando o processo morre, inclusive a forca — o que um arquivo de trava nao
    garante, e por isso arquivo de trava sempre deixa o app preso depois de um
    travamento;
  - um evento nomeado deixa a segunda copia pedir para a primeira aparecer, em
    vez de simplesmente sumir. Fechar calado seria pior que abrir duas: quem
    clicou duas vezes no atalho concluiria que o app nao abre.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from .. import log

_log = log.get("instancia")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000

# "Local\" e' proposital: o escopo e' a sessao de logon. Assim duas contas
# usando o mesmo PC (troca rapida de usuario) tem cada uma a sua copia, que e'
# o certo — o que nao pode e' a MESMA pessoa abrir duas.
NOME_MUTEX = r"Local\DBXStats.instancia.unica"
NOME_EVENTO = r"Local\DBXStats.mostrar.janela"


def _setup() -> None:
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


_setup()


class InstanciaUnica:
    """Guarda a vaga da instancia e escuta pedidos de foco."""

    def __init__(self) -> None:
        self._mutex = None
        self._evento = None
        self._parar = threading.Event()

    def assumir(self) -> bool:
        """Tenta ser a instancia da vez. False quer dizer que ja' ha' outra.

        O mutex e' criado, e nao adquirido: o que interessa e' a existencia dele,
        que o kernel amarra ao processo. Se este morrer de qualquer jeito — saida
        limpa, travamento ou taskkill — o objeto some junto e a proxima copia
        entra sem precisar limpar nada.
        """
        self._mutex = kernel32.CreateMutexW(None, False, NOME_MUTEX)
        if not self._mutex:
            # Sem o mutex nao da' para saber; deixar abrir e' melhor do que
            # impedir o app de subir por causa do guarda.
            _log.warning("nao consegui criar o mutex de instancia unica")
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(self._mutex)
            self._mutex = None
            return False
        return True

    def liberar(self) -> None:
        self._parar.set()
        for h in (self._evento, self._mutex):
            if h:
                kernel32.CloseHandle(h)
        self._evento = self._mutex = None

    def ouvir(self, mostrar) -> None:
        """Chama `mostrar()` sempre que outra copia tentar abrir.

        A espera fica numa thread propria porque `WaitForSingleObject` bloqueia,
        e o retorno tem de cair na interface — por isso quem chama passa uma
        funcao que ja' sabe voltar para o laco do Qt.
        """
        self._evento = kernel32.CreateEventW(None, False, False, NOME_EVENTO)
        if not self._evento:
            return

        def _laco() -> None:
            while not self._parar.is_set():
                # Prazo curto em vez de espera infinita: e' o que permite a
                # thread notar o encerramento e sair, em vez de segurar o
                # processo aberto depois de a janela fechar.
                if kernel32.WaitForSingleObject(self._evento, 500) == WAIT_OBJECT_0:
                    if self._parar.is_set():
                        return
                    try:
                        mostrar()
                    except Exception:                        # noqa: BLE001
                        _log.exception("falha trazendo a janela para a frente")

        threading.Thread(target=_laco, name="instancia-unica", daemon=True).start()

    @staticmethod
    def pedir_foco() -> bool:
        """Avisa a instancia que ja' esta' aberta para aparecer."""
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False,
                                     NOME_EVENTO)
        if not handle:
            return False
        try:
            return bool(kernel32.SetEvent(handle))
        finally:
            kernel32.CloseHandle(handle)
