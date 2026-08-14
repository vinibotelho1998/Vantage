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
        self.adopted = False
        """Ja' descobrimos o processo real do jogo (ver App._adopt_game_process)."""
        self.direct = True
        """O alvo e' o proprio executavel do jogo, nao um atalho de loja."""

    # ── ciclo ────────────────────────────────────────────────────────────────
    def start(self) -> tuple[bool, str]:
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
                argv = [str(alvo), *_split_args(self.args)]
                self._proc = subprocess.Popen(argv, cwd=str(alvo.parent))
            else:
                os.startfile(str(alvo))  # noqa: S606 — atalho/URL fica com o shell
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
        return self._alive_by_name()

    def _alive_by_name(self) -> bool:
        if not self.names:
            return False
        for proc in psutil.process_iter(["name"]):
            try:
                nome = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if nome in self.names:
                return True
        return False

    @property
    def ever_started(self) -> bool:
        return self._seen_alive


def _split_args(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        import shlex
        return shlex.split(raw, posix=False)
    except ValueError:
        return raw.split()


def resolve_shortcut(path: str) -> str:
    """Devolve o alvo de um .lnk. Fora isso, o proprio caminho.

    Windows guarda atalho em formato binario proprio; o caminho barato de ler
    isso sem dependencia nova e' pedir para o WScript.Shell.
    """
    if not path.lower().endswith(".lnk"):
        return path
    script = (f"$s=(New-Object -COM WScript.Shell).CreateShortcut('{path}');"
              "Write-Output $s.TargetPath")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=8,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        alvo = out.stdout.strip()
        return alvo if alvo and Path(alvo).exists() else path
    except (OSError, subprocess.SubprocessError):
        return path
