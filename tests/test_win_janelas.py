"""Contas das janelas do Windows, com um user32 falso: nenhuma janela real se mexe.

Trazer as janelas para a tela que sobrou e' o que salva quem desligou o monitor
onde tudo estava aberto; um erro de conta aqui joga as janelas para fora de
qualquer tela, de onde so' se tira no teclado.
"""
import pytest

from vantage.platform import win


class _User32Falso:
    def __init__(self, janelas):
        self.janelas = janelas
        self.gravadas = {}
        self.recusar = set()

    def GetWindowPlacement(self, hwnd, ref):
        dados = self.janelas.get(hwnd)
        if dados is None:
            return 0
        place = ref._obj
        place.showCmd = dados["show"]
        place.rcNormalPosition = win.RECT(*dados["rc"])
        return 1

    def SetWindowPlacement(self, hwnd, ref):
        if hwnd in self.recusar:
            return 0
        place = ref._obj
        rc = place.rcNormalPosition
        self.gravadas[hwnd] = ((rc.left, rc.top, rc.right, rc.bottom),
                               place.showCmd, place.flags)
        return 1


@pytest.fixture
def mesa(monkeypatch):
    def montar(janelas):
        falso = _User32Falso(janelas)
        monkeypatch.setattr(win, "user32", falso)
        monkeypatch.setattr(win, "app_windows", lambda: list(janelas))
        return falso
    return montar


def test_janela_menor_que_a_tela_vai_para_o_centro(mesa):
    falso = mesa({1: {"show": win.SW_SHOWNORMAL, "rc": (-1920, 100, -1120, 700)}})
    assert win.move_windows_to((0, 0, 1920, 1080)) == 1
    rc, _show, flags = falso.gravadas[1]
    assert rc == (560, 240, 1360, 840)
    assert flags & win.WPF_ASYNCWINDOWPLACEMENT


def test_janela_maior_que_a_tela_encolhe_para_caber(mesa):
    falso = mesa({1: {"show": win.SW_SHOWNORMAL, "rc": (0, 0, 3840, 2160)}})
    win.move_windows_to((1920, 0, 3840, 1080))
    rc, _show, _flags = falso.gravadas[1]
    assert rc == (1920, 0, 3840, 1080)


def test_tela_com_origem_negativa(mesa):
    falso = mesa({1: {"show": win.SW_SHOWNORMAL, "rc": (0, 0, 1000, 500)}})
    win.move_windows_to((-2560, -200, 0, 1240))
    rc, _s, _f = falso.gravadas[1]
    assert rc == (-1780, 270, -780, 770)


def test_maximizada_continua_maximizada(mesa):
    falso = mesa({1: {"show": win.SW_SHOWMAXIMIZED, "rc": (-1920, 0, -960, 540)}})
    win.move_windows_to((0, 0, 1920, 1080))
    _rc, show, _flags = falso.gravadas[1]
    assert show == win.SW_SHOWMAXIMIZED


def test_minimizada_e_a_que_falha_nao_contam(mesa):
    falso = mesa({
        1: {"show": win.SW_SHOWMINIMIZED, "rc": (0, 0, 100, 100)},
        2: {"show": win.SW_SHOWNORMAL, "rc": (0, 0, 100, 100)},
        3: {"show": win.SW_SHOWNORMAL, "rc": (0, 0, 100, 100)},
    })
    falso.recusar.add(3)
    assert win.move_windows_to((0, 0, 1920, 1080)) == 1
    assert set(falso.gravadas) == {2}


def test_janela_sem_placement_e_pulada(mesa, monkeypatch):
    falso = mesa({})
    monkeypatch.setattr(win, "app_windows", lambda: [99])
    assert win.move_windows_to((0, 0, 1920, 1080)) == 0
    assert falso.gravadas == {}


# ── tela cheia ───────────────────────────────────────────────────────────────
class _Retangulos:
    def __init__(self, janela):
        self.janela = janela

    def GetWindowRect(self, hwnd, ref):
        if self.janela is None:
            return 0
        rc = ref._obj
        rc.left, rc.top, rc.right, rc.bottom = self.janela
        return 1


def _tela_cheia(monkeypatch, janela, monitor=(0, 0, 1920, 1080), hwnd=7):
    monkeypatch.setattr(win, "foreground_hwnd", lambda: hwnd)
    monkeypatch.setattr(win, "user32", _Retangulos(janela))
    monkeypatch.setattr(win, "_monitor_rect",
                        lambda h: None if monitor is None else win.RECT(*monitor))
    return win.is_foreground_fullscreen()


def test_janela_que_cobre_o_monitor_e_tela_cheia(monkeypatch):
    assert _tela_cheia(monkeypatch, (0, 0, 1920, 1080)) == (True, 7)
    assert _tela_cheia(monkeypatch, (-8, -8, 1928, 1088)) == (True, 7)


def test_janela_quase_do_tamanho_nao_e_tela_cheia(monkeypatch):
    """Maximizada com a barra de tarefas aparecendo nao e' jogo em tela cheia."""
    assert _tela_cheia(monkeypatch, (0, 0, 1920, 1040)) == (False, 7)


def test_sem_janela_em_foco_ou_sem_retangulo(monkeypatch):
    assert _tela_cheia(monkeypatch, (0, 0, 1920, 1080), hwnd=0) == (False, 0)
    assert _tela_cheia(monkeypatch, None) == (False, 7)
    assert _tela_cheia(monkeypatch, (0, 0, 1920, 1080), monitor=None) == (False, 7)


# ── estilo estendido ─────────────────────────────────────────────────────────
@pytest.fixture
def estilo(monkeypatch):
    atual = {"v": 0}
    monkeypatch.setattr(win, "_get_long", lambda h, i: atual["v"])

    def gravar(h, i, v):
        atual["v"] = v
        return 0
    monkeypatch.setattr(win, "_set_long", gravar)
    return atual


def test_clique_atravessa_e_volta(estilo):
    estilo["v"] = win.WS_EX_TOOLWINDOW
    win.set_clickthrough(5, True)
    assert estilo["v"] & win.WS_EX_TRANSPARENT and estilo["v"] & win.WS_EX_LAYERED
    win.set_clickthrough(5, False)
    assert not estilo["v"] & win.WS_EX_TRANSPARENT
    assert estilo["v"] & win.WS_EX_LAYERED
    assert estilo["v"] & win.WS_EX_TOOLWINDOW


def test_janela_nula_nao_e_tocada(estilo):
    estilo["v"] = 123
    win.set_clickthrough(0, True)
    win.set_tool_window(0)
    assert estilo["v"] == 123
