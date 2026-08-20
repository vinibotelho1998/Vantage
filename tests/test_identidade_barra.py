"""Identidade do processo na barra de tarefas do Windows.

Sem um AppUserModelID proprio, o Windows agrupa a janela sob o executavel que
hospeda o Python e mostra o icone DELE — e fixar na barra fixa a coisa errada.
"""
from dbxstats.__main__ import _identidade_na_barra


def test_define_a_identidade_do_processo():
    import ctypes

    _identidade_na_barra()
    buf = ctypes.c_wchar_p()
    ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(buf))
    assert buf.value == "DBX.DBXStats"


def test_nao_derruba_o_app_quando_a_api_falta():
    """Windows antigo nao tem essa chamada, e ela nao vale um app que nao abre."""
    import ctypes

    original = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID

    def explode(*_a):
        raise OSError("sem essa API")

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID = explode
    try:
        _identidade_na_barra()      # nao pode levantar
    finally:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID = original


def test_o_icone_e_empacotado_junto():
    """O icone embutido no .exe serve ao Explorer, nao a barra de tarefas.

    A barra usa o icone da JANELA, carregado deste arquivo em tempo de execucao.
    Ele nao estava sendo copiado para o pacote, entao setWindowIcon nunca rodava
    e a janela ficava com o icone generico do Windows.
    """
    import pathlib

    spec = pathlib.Path("packaging/DBXStats.spec").read_text(encoding="utf-8")
    assert '"icon.ico"), "assets"' in spec, "o .ico precisa entrar em datas"
    assert pathlib.Path("assets/icon.ico").exists()
