"""Regressões na adaptação das APIs do Windows para Linux."""
import os
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="integrações Linux")


def test_executavel_com_argumentos_roda_sem_shell(tmp_path):
    from vantage.core.session import GameSession

    result = tmp_path / "argumentos.txt"
    script = tmp_path / "jogo com espaços"
    script.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > argumentos.txt\n")
    script.chmod(0o700)
    session = GameSession(str(script), '"uma fase" "$(echo injetado)"', start_grace=0, exit_grace=0)
    assert session.start() == (True, "ok")
    assert session._proc.wait(timeout=5) == 0
    assert not session.running()
    assert result.read_text().splitlines() == ["uma fase", "$(echo injetado)"]


def test_arquivo_comum_nao_inicia(tmp_path):
    from vantage.core.session import GameSession

    doc = tmp_path / "texto"
    doc.write_text("conteúdo")
    assert not GameSession(str(doc)).start()[0]


def test_varredura_e_sessao_do_steam_seguem_mesmo_appid(tmp_path, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from vantage.core.session import GameSession
    from vantage.platform import art, gamescan
    import psutil

    steamapps = tmp_path / "steamapps"
    (steamapps / "common" / "Um Jogo").mkdir(parents=True)
    (steamapps / "appmanifest_42.acf").write_text('"name" "Um Jogo"\n"installdir" "Um Jogo"')
    monkeypatch.setattr(art, "_steam_root", lambda: tmp_path)
    [game] = gamescan.scan()
    requests = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: requests.append(url.toString()) or True)
    app = GameSession(game.path)
    assert app.start() == (True, "ok")
    assert requests == ["steam://rungameid/42"]
    reaper = SimpleNamespace(info={"name": "reaper", "uids": SimpleNamespace(real=os.getuid())},
                             cmdline=lambda: ["reaper", "SteamLaunch", "AppId=420"], is_running=lambda: True)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [reaper])
    assert not app._steam_running()
    reaper.cmdline = lambda: ["reaper", "SteamLaunch", "AppId=42"]
    assert app._steam_running()


def test_autostart_xdg_sem_dependencia_do_diretorio_atual(tmp_path, monkeypatch):
    from vantage.platform import linux_desktop
    from vantage import paths

    project = tmp_path / 'Apps com espaço e 100%'
    project.mkdir()
    (project / 'Vantage.sh').touch()
    monkeypatch.setattr(paths, "base_dir", lambda: project)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    linux_desktop.set_autostart(True)
    entry = tmp_path / "config/autostart/vantage.desktop"
    assert f'Exec="{str(project).replace("%", "%%")}/Vantage.sh"' in entry.read_text().splitlines()
    linux_desktop.set_autostart(False)
    assert not entry.exists()


def test_acao_de_processo_preserva_pid_uno():
    from vantage.sensors.procs import bloqueio_encerrar

    assert bloqueio_encerrar("systemd", 1)
    assert bloqueio_encerrar("vantage", os.getpid())
    assert not bloqueio_encerrar("jogo", 424242)
