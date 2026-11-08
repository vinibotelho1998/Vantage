"""Posiciona e prende no topo o painel flutuante quando a sessao e' KDE Plasma (Wayland).

No Wayland uma janela comum nao escolhe onde aparece nem fica por cima de um jogo em
tela cheia: o compositor decide, e o Qt ignora `move()` e `WindowStaysOnTopHint`. O
KWin, porem, aceita scripts pelo D-Bus da sessao, e um script de janela pode marcar
"manter acima", tirar do alternador de tarefas e mudar a geometria. E' o mesmo caminho
de ferramentas como o kdotool, sem pedir privilegio nenhum.

O script casa a janela pelo titulo e vale so' enquanto o painel esta' aberto: ao
esconder o painel (ou fechar o app) ele e' descarregado, e o KWin devolve as janelas
ao normal. Fora do KWin nada daqui faz efeito.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .. import log, paths

_log = log.get("kwin")

TITULO = "Vantage Overlay"
NOME_DO_SCRIPT = "vantage-overlay"
_SERVICO = "org.kde.KWin"


def gerar_script(titulo: str, x: int, y: int, largura: int, altura: int) -> str:
    """O JavaScript que o KWin roda: acha a janela pelo titulo e a fixa na posicao."""
    return f"""\
(function () {{
    var alvo = {json.dumps(titulo)};
    function ajustar(w) {{
        if (!w || w.caption !== alvo) return;
        w.keepAbove = true;
        w.skipTaskbar = true;
        w.skipPager = true;
        w.skipSwitcher = true;
        w.noBorder = true;
        w.frameGeometry = {{ x: {int(x)}, y: {int(y)}, width: {int(largura)}, height: {int(altura)} }};
    }}
    workspace.windowList().forEach(ajustar);
    workspace.windowAdded.connect(ajustar);
}})();
"""


def _chamar_dbus(caminho: str, interface: str, metodo: str, *args):
    """Chamada ao KWin pelo barramento da sessao; devolve o primeiro valor ou None."""
    from PySide6.QtDBus import QDBusConnection, QDBusInterface

    iface = QDBusInterface(_SERVICO, caminho, interface, QDBusConnection.sessionBus())
    if not iface.isValid():
        return None
    resposta = iface.call(metodo, *args)
    valores = resposta.arguments()
    return valores[0] if valores else True


def _kwin_no_barramento() -> bool:
    try:
        from PySide6.QtDBus import QDBusConnection

        bus = QDBusConnection.sessionBus()
        return bus.isConnected() and bus.interface().isServiceRegistered(_SERVICO).value()
    except Exception:  # noqa: BLE001 - sem QtDBus ou sem barramento: simplesmente nao ha' KWin
        return False


def disponivel() -> bool:
    """True numa sessao Wayland do Plasma, onde o KWin responde a scripts."""
    if not sys.platform.startswith("linux"):
        return False
    if (os.environ.get("XDG_SESSION_TYPE") or "").lower() != "wayland":
        return False
    return _kwin_no_barramento()


class Fixador:
    """Mantem o script do painel carregado e so' o recarrega quando a geometria muda."""

    def __init__(self, chamar=_chamar_dbus, pasta: Path | None = None) -> None:
        self._chamar = chamar
        self._pasta = pasta
        self._ultima: tuple[int, int, int, int] | None = None
        self._carregado = False

    def _arquivo(self) -> Path:
        pasta = self._pasta or paths.data_dir()
        return pasta / "kwin-overlay.js"

    def aplicar(self, x: int, y: int, largura: int, altura: int) -> bool:
        """Devolve True se o KWin aceitou o script (ou se ele ja' estava assim)."""
        geometria = (int(x), int(y), int(largura), int(altura))
        if self._carregado and geometria == self._ultima:
            return True
        arquivo = self._arquivo()
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(gerar_script(TITULO, *geometria), encoding="utf-8")
        except OSError as erro:
            _log.warning("nao consegui gravar o script do KWin: %s", erro)
            return False
        self.remover()
        identificador = self._chamar("/Scripting", "org.kde.kwin.Scripting", "loadScript",
                                     str(arquivo), NOME_DO_SCRIPT)
        if identificador is None or (isinstance(identificador, int) and identificador < 0):
            _log.warning("o KWin recusou o script do painel (retorno %r)", identificador)
            return False
        self._chamar(f"/Scripting/Script{identificador}", "org.kde.kwin.Script", "run")
        self._ultima, self._carregado = geometria, True
        return True

    def remover(self) -> None:
        """Descarrega o script; a janela volta ao comportamento normal do KWin."""
        try:
            self._chamar("/Scripting", "org.kde.kwin.Scripting", "unloadScript", NOME_DO_SCRIPT)
        except Exception:  # noqa: BLE001 - encerrando; nada daqui pode quebrar o fechamento
            _log.debug("unloadScript falhou", exc_info=True)
        self._carregado = False
        self._ultima = None
