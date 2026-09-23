"""Sessao de jogo: quando ela conta como viva e como os argumentos sao lidos."""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes

import vantage.core.session as sessao
from vantage.core.session import GameSession, _linha_de_comando, resolve_shortcut


def _argv_do_jogo(linha: str) -> list[str]:
    """Quebra a linha como o proprio Windows quebra para o jogo que vai abrir."""
    quebrar = ctypes.windll.shell32.CommandLineToArgvW
    quebrar.restype = ctypes.POINTER(wintypes.LPWSTR)
    quebrar.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    n = ctypes.c_int()
    argv = quebrar(linha, ctypes.byref(n))
    try:
        return [argv[i] for i in range(n.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))


def test_argumentos_vazios():
    assert _argv_do_jogo(_linha_de_comando(r"C:\Jogos\x.exe", "   ")) == [r"C:\Jogos\x.exe"]


def test_argumentos_respeitam_aspas():
    """As aspas agrupam, e nao entram no valor.

    A lista quebrada com as aspas dentro era remontada pelo subprocess, que as
    escapava: o jogo recebia `"de dust"`, com aspas, e nao achava o mapa.
    """
    linha = _linha_de_comando(r"C:\Program Files\Jogo\jogo.exe", '-novid -map "de dust"')
    assert _argv_do_jogo(linha) == [r"C:\Program Files\Jogo\jogo.exe", "-novid", "-map",
                                    "de dust"]


def test_caminho_entre_aspas_chega_inteiro_ao_jogo():
    linha = _linha_de_comando(r"C:\Jogos\x.exe", r'-config "C:\Meus Jogos\cfg.ini"')
    assert _argv_do_jogo(linha)[1:] == ["-config", r"C:\Meus Jogos\cfg.ini"]


def test_jogo_abre_com_a_linha_montada(tmp_path, monkeypatch):
    alvo = tmp_path / "jogo.exe"
    alvo.write_bytes(b"")
    chamadas = []

    class _Popen:
        def __init__(self, cmd, **kw):
            chamadas.append((cmd, kw))

        def poll(self):
            return None

    monkeypatch.setattr(sessao.subprocess, "Popen", _Popen)
    ok, _ = GameSession(str(alvo), '-map "de dust"').start()

    assert ok
    cmd, kw = chamadas[0]
    assert _argv_do_jogo(cmd) == [str(alvo), "-map", "de dust"]
    assert kw["cwd"] == str(tmp_path)


def test_arquivo_inexistente_nao_inicia(tmp_path):
    ok, err = GameSession(str(tmp_path / "nao_existe.exe")).start()
    assert not ok
    assert "não encontrado" in err


def test_carencia_segura_a_sessao_ate_o_jogo_subir():
    """Launcher de loja sai antes do jogo abrir; a sessao nao pode morrer nesse vao."""
    s = GameSession("x.exe", start_grace=0.4)
    s.names = {"processo_que_nao_existe_12345.exe"}
    s.started_at = time.monotonic()
    assert s.running() is True
    time.sleep(0.5)
    assert s.running() is False


def test_jogo_que_sumiu_encerra_depois_da_confirmacao():
    """Ja' rodou e sumiu: encerra rapido, sem esperar a carencia longa de abertura."""
    import psutil
    s = GameSession("qualquer.exe", start_grace=99.0, exit_grace=0.3)
    s.names = {psutil.Process().name().lower()}
    s.started_at = time.monotonic()
    assert s.running() is True          # visto vivo
    s.names = {"processo_que_nao_existe_12345.exe"}
    assert s.running() is True          # sumiu agora, ainda confirmando
    time.sleep(0.4)
    assert s.running() is False


def test_watch_agrega_nomes():
    s = GameSession("jogo.exe")
    s.names = {"jogo.exe"}
    s.watch({"Launcher.exe", "", "OUTRO.EXE"})
    assert s.names == {"jogo.exe", "launcher.exe", "outro.exe"}


def test_processo_vivo_mantem_a_sessao():
    import psutil
    atual = psutil.Process().name()
    s = GameSession("qualquer.exe", start_grace=0.0)
    s.names = {atual.lower()}
    s.started_at = time.monotonic() - 10
    assert s.running() is True
    assert s.ever_started is True


def test_resolve_shortcut_ignora_nao_atalho(tmp_path):
    alvo = tmp_path / "jogo.exe"
    alvo.write_text("")
    assert resolve_shortcut(str(alvo)) == str(alvo)


def _atalho(caminho, alvo) -> None:
    """Grava um .lnk de verdade, pela mesma interface COM que o Windows usa."""
    import win32com.client

    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(caminho))
    link.TargetPath = str(alvo)
    link.Save()


def test_atalho_com_apostrofo_no_nome_resolve(tmp_path):
    """"Assassin's Creed.lnk": o apostrofo fechava a string do PowerShell no
    meio do caminho, o script quebrava e o atalho nunca era resolvido."""
    alvo = tmp_path / "jogo.exe"
    alvo.write_bytes(b"")
    atalho = tmp_path / "Assassin's Creed.lnk"
    _atalho(atalho, alvo)

    assert resolve_shortcut(str(atalho)) == str(alvo)


def test_atalho_para_pasta_com_acento_resolve(tmp_path):
    """O PowerShell escrevia na pagina OEM e o app lia em outra: "Ação" voltava
    "A‡ao", o caminho nao existia e o atalho ficava sem resolver. Pasta com
    acento e' o caso comum aqui: usuario "João", "Área de Trabalho"."""
    pasta = tmp_path / "Ação"
    pasta.mkdir()
    alvo = pasta / "jogo.exe"
    alvo.write_bytes(b"")
    atalho = tmp_path / "jogo.lnk"
    _atalho(atalho, alvo)

    assert resolve_shortcut(str(atalho)) == str(alvo)


def test_caminho_do_atalho_nao_vira_codigo(tmp_path, monkeypatch):
    """O caminho vai por variavel de ambiente, nunca colado no script."""
    visto = {}

    def _run(cmd, **kw):
        visto["cmd"], visto["env"] = cmd, kw.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sessao.subprocess, "run", _run)
    malicioso = str(tmp_path / "x'; Remove-Item C:\\nada; '.lnk")
    resolve_shortcut(malicioso)

    assert malicioso not in " ".join(visto["cmd"])
    assert malicioso in visto["env"].values()
    assert os.environ.get("PATH") == visto["env"].get("PATH")


def test_atalho_de_loja_nao_chuta_nome_de_processo(tmp_path, monkeypatch):
    """O nome do .url nao diz nada sobre o processo: seguir por ele daria falso fim."""
    atalho = tmp_path / "Battlefield 6.url"
    atalho.write_text("[InternetShortcut]\nURL=origin2://game/launch\n")
    # Sem isto o teste entregava o atalho ao shell de verdade: abria o cliente
    # da loja, ou o aviso do Windows de que nenhum app abre "origin2://".
    abertos = []
    monkeypatch.setattr(sessao.os, "startfile", abertos.append)
    s = GameSession(str(atalho))
    s.start()
    assert abertos == [str(atalho)]
    assert s.names == set()
    assert s.direct is False
    assert s.start_grace >= 180.0


def test_exe_direto_segue_pelo_proprio_nome(tmp_path):
    alvo = tmp_path / "forzahorizon6.exe"
    alvo.write_bytes(b"")
    s = GameSession(str(alvo))
    s.start()          # falha ao executar, mas o nome ja' foi registrado
    assert s.names == {"forzahorizon6.exe"}
    assert s.direct is True
