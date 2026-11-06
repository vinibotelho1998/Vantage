"""Sessao de jogo: sobe o executavel e diz quando ele realmente terminou.

Esperar o processo lancado nao basta. Launcher de loja (Steam, EA, Epic) sai
poucos segundos depois de repassar para o jogo de verdade, e o jogo costuma ter
outro nome. Entao o fim da sessao aqui e' "nenhum processo dessa familia vivo",
com uma carencia inicial para o repasse acontecer.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import psutil

from .. import log

_log = log.get("session")

START_GRACE_S = 45.0
"""Espera inicial ate' alguma coisa subir. Launcher de loja demora a repassar."""
SHORTCUT_GRACE_S = 180.0
"""Atalho de loja: da' tempo do cliente abrir, atualizar e so' entao subir o jogo."""
EXIT_GRACE_S = 6.0
"""Depois que o jogo some, confirma que sumiu mesmo antes de encerrar a sessao.

Serve para dois casos reais: o launcher que sai e so' entao abre o jogo, e o jogo
que reinicia sozinho ao trocar de resolucao ou de API grafica.
"""


class GameSession:
    def __init__(self, path: str, args: str = "",
                 start_grace: float = START_GRACE_S,
                 exit_grace: float = EXIT_GRACE_S) -> None:
        self.path = path
        self.args = args
        self.start_grace = start_grace
        self.exit_grace = exit_grace
        self.started_at = 0.0
        self.names: set[str] = set()
        self._proc: subprocess.Popen | None = None
        self._seen_alive = False
        self._last_alive = 0.0
        self._pid = 0
        """Processo do jogo ja' encontrado; evita varrer a tabela toda."""
        self._steam_id = ""
        self._steam_reaper: psutil.Process | None = None
        self.adopted = False
        """Ja' descobrimos o processo real do jogo (ver App._adopt_game_process)."""
        self.direct = True
        """O alvo e' o proprio executavel do jogo, nao um atalho de loja."""

    def start(self) -> tuple[bool, str]:
        if os.name != "nt":
            import re
            import shlex
            self.started_at = time.monotonic()
            if re.fullmatch(r"steam://rungameid/[0-9]+", self.path):
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                self._steam_id = self.path.rsplit("/", 1)[1]
                self.direct = False
                self.start_grace = max(self.start_grace, SHORTCUT_GRACE_S)
                ok = QDesktopServices.openUrl(QUrl(self.path))
                return ok, "ok" if ok else "Steam indisponível"
            exe = Path(self.path).expanduser().absolute()
            if not exe.is_file() or not os.access(exe, os.X_OK):
                return False, "Escolha um arquivo executável Linux ou use o Steam."
            try:
                self._proc = subprocess.Popen([str(exe), *shlex.split(self.args)], cwd=exe.parent,
                                              start_new_session=True)
                self._seen_alive = True
                self._last_alive = time.monotonic()
            except (OSError, ValueError) as exc:
                return False, str(exc)
            return True, "ok"
        alvo = Path(self.path)
        if not alvo.exists():
            return False, "arquivo não encontrado"
        # Nome de arquivo so' serve como pista quando o alvo e' o proprio jogo.
        # Atalho de loja (.url, .lnk de protocolo) abre o cliente, e o processo
        # que vai aparecer nao tem relacao nenhuma com o nome do atalho.
        self.direct = alvo.suffix.lower() == ".exe"
        self.names = {alvo.name.lower()} if self.direct else set()
        if not self.direct:
            self.start_grace = max(self.start_grace, SHORTCUT_GRACE_S)
        self.started_at = time.monotonic()
        self._seen_alive = False
        try:
            if alvo.suffix.lower() == ".exe":
                self._proc = subprocess.Popen(_linha_de_comando(alvo, self.args),
                                              cwd=str(alvo.parent))
            else:
                os.startfile(str(alvo))  # noqa: S606, atalho/URL fica com o shell
        except OSError as e:
            return False, str(e)
        _log.info("sessao iniciada: %s", alvo.name)
        return True, "ok"

    def watch(self, extra_names: set[str]) -> None:
        """Adiciona nomes de processo que tambem contam como 'o jogo rodando'."""
        self.names |= {n.lower() for n in extra_names if n}

    def running(self) -> bool:
        agora = time.monotonic()
        if self._alive():
            self._seen_alive = True
            self._last_alive = agora
            return True
        if self._seen_alive:
            return (agora - self._last_alive) < self.exit_grace
        return (agora - self.started_at) < self.start_grace

    def _alive(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        if os.name != "nt":
            if self._proc is not None:
                # Um script lançador pode sair assim que o filho abre a janela.
                try:
                    os.killpg(self._proc.pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    return False
                return True
            if self._steam_id:
                return self._steam_running()
        return self._alive_by_name()

    @property
    def native_pid(self):
        return self._proc.pid if self._proc is not None and self._proc.poll() is None else None

    def _steam_running(self):
        if self._steam_reaper is not None and self._steam_reaper.is_running():
            return True
        self._steam_reaper = None
        marker = f"AppId={self._steam_id}"
        for proc in psutil.process_iter(["name", "uids"]):
            # O cliente Steam delimita a sessão (inclusive Proton) com o reaper.
            if proc.info["name"] != "reaper" or not proc.info["uids"] or proc.info["uids"].real != os.getuid():
                continue
            try:
                args = proc.cmdline()
            except (OSError, psutil.Error):
                continue
            if "SteamLaunch" in args and marker in args:
                self._steam_reaper = proc
                return True
        return False

    def _alive_by_name(self) -> bool:
        """O jogo ainda esta' de pe', olhando pelo nome do executavel.

        Varrer a tabela de processos inteira uma vez por segundo, a partida toda,
        custa caro justamente enquanto o jogo esta' rodando. Entao a varredura
        acontece so' ate' achar; dai' em diante conferimos aquele pid, que e' uma
        consulta unica. So' quando ele morre voltamos a varrer: e' assim que o
        fim da partida e' percebido sem pesar no meio dela.
        """
        if not self.names:
            return False
        if self._pid and self._same_game(self._pid):
            return True
        self._pid = 0
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                nome = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if nome in self.names:
                self._pid = proc.info.get("pid") or 0
                return True
        return False

    def _same_game(self, pid: int) -> bool:
        """Aquele pid continua vivo E continua sendo o jogo.

        Conferir so' a existencia nao serve: o Windows reaproveita numero de pid,
        e um processo qualquer herdando o numero faria a sessao nunca terminar.
        """
        try:
            return psutil.Process(pid).name().lower() in self.names
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return False

    @property
    def ever_started(self) -> bool:
        return self._seen_alive


def _linha_de_comando(exe, args: str) -> str:
    """Linha de comando do jogo, com os argumentos exatamente como digitados.

    Os argumentos seguem crus, como no campo "Destino" de um atalho do Windows.
    Quebrar em lista e deixar o subprocess remontar escapava as aspas do
    usuario: `-map "de dust"` chegava ao jogo como `"de dust"`, com as aspas
    dentro do valor, e um caminho entre aspas virava caminho que nao existe.
    """
    linha = subprocess.list2cmdline([str(exe)])
    extra = (args or "").strip()
    return f"{linha} {extra}" if extra else linha


_VAR_ATALHO = "VANTAGE_ATALHO"


def resolve_shortcut(path: str) -> str:
    """Devolve o alvo de um .lnk. Fora isso, o proprio caminho.

    Windows guarda atalho em formato binario proprio; o caminho barato de ler
    isso sem dependencia nova e' pedir para o WScript.Shell.

    O caminho entra por variavel de ambiente, e nao colado no script: colado
    entre aspas simples, o apostrofo de "Assassin's Creed.lnk" fechava a string
    no meio e o resto do nome virava codigo do PowerShell. A saida vem em UTF-8
    porque, na pagina OEM do console, "Ação" chegava aqui como "A‡ao" e o alvo
    resolvido nunca existia.
    """
    if not path.lower().endswith(".lnk"):
        return path
    script = ("[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding $false;"
              f"$s=(New-Object -COM WScript.Shell).CreateShortcut($env:{_VAR_ATALHO});"
              "Write-Output $s.TargetPath")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, encoding="utf-8-sig",
                             errors="replace", timeout=8,
                             env={**os.environ, _VAR_ATALHO: path},
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        alvo = out.stdout.strip()
        return alvo if alvo and Path(alvo).exists() else path
    except (OSError, subprocess.SubprocessError):
        return path
