"""Sessao de jogo: quando ela conta como viva e como os argumentos sao lidos."""
import time

from dbxstats.core.session import GameSession, _split_args, resolve_shortcut


def test_argumentos_vazios():
    assert _split_args("   ") == []


def test_argumentos_respeitam_aspas():
    assert _split_args('-novid -map "de dust"') == ["-novid", "-map", '"de dust"']


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


def test_atalho_de_loja_nao_chuta_nome_de_processo(tmp_path):
    """O nome do .url nao diz nada sobre o processo: seguir por ele daria falso fim."""
    atalho = tmp_path / "Battlefield 6.url"
    atalho.write_text("[InternetShortcut]\nURL=origin2://game/launch\n")
    s = GameSession(str(atalho))
    s.start()
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
