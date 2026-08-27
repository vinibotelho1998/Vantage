"""VRAM por processo: o numero que diz se quem encheu a placa foi o jogo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

import ctypes  # noqa: E402

from dbxstats.platform import gpumem  # noqa: E402


def test_struct_tem_o_tamanho_que_o_windows_espera():
    """Em 64 bits ha' 4 bytes de alinhamento entre CStatus e o valor. Sem eles o
    ctypes le' o numero deslocado e devolve lixo em vez de bytes."""
    assert ctypes.sizeof(gpumem.PDH_FMT_COUNTERVALUE_ITEM_W) == 24


def test_caminho_do_contador_usa_curinga():
    """Um processo aparece em varias instancias: uma por adaptador e segmento.
    Ler so' a primeira daria um numero parcial."""
    caminho = gpumem.ProcessVram.CONTADOR.format(pid=1234)
    assert "pid_1234*" in caminho
    assert caminho.endswith(r"\Local Usage")


def test_mede_a_vram_dedicada_e_nao_a_compartilhada():
    """`Non Local Usage` cresce DEPOIS que a dedicada acabou; somar as duas
    esconderia o instante em que o problema comecou."""
    assert "Non Local" not in gpumem.ProcessVram.CONTADOR


def test_sem_pid_nao_devolve_numero():
    """Zero seria mentira: nao ha' processo para medir."""
    v = gpumem.ProcessVram()
    v.follow(0)
    assert v.read_mb() is None
    v.follow(None)
    assert v.read_mb() is None


def test_pid_inexistente_nao_quebra():
    v = gpumem.ProcessVram()
    v.follow(999_999)
    assert v.read_mb() is None
    v.close()


def test_fechar_duas_vezes_e_seguro():
    """O coletor fecha no encerramento, e o jogo pode ter fechado antes."""
    v = gpumem.ProcessVram()
    v.close()
    v.close()


def test_mede_um_processo_de_verdade():
    """Contra a maquina real: o que importa e' devolver numero plausivel.

    O dwm.exe (compositor da area de trabalho) sempre tem VRAM enquanto houver
    tela ligada, entao serve de alvo estavel.
    """
    import psutil

    if not gpumem.disponivel():
        return          # Windows sem o contador; nada a verificar

    v = gpumem.ProcessVram()
    try:
        for p in psutil.process_iter(["pid", "name"]):
            if (p.info["name"] or "").lower() != "dwm.exe":
                continue
            v.follow(p.info["pid"])
            mb = v.read_mb()
            if mb:
                assert 0 < mb < 64_000        # placa nenhuma tem 64 GB dedicados
                return
    finally:
        v.close()


def test_consulta_e_reaproveitada_entre_leituras():
    """Reabrir a consulta a cada ciclo custaria milissegundos o jogo inteiro."""
    import psutil

    if not gpumem.disponivel():
        return
    v = gpumem.ProcessVram()
    try:
        pid = next(iter(psutil.pids()))
        v.follow(pid)
        v.read_mb()
        primeira = v._query
        v.read_mb()
        assert v._query is primeira
    finally:
        v.close()
