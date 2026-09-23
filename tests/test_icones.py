"""Icones vetoriais: toda tela tem o seu, e cada um desenha alguma coisa.

Os glifos Unicode de antes falhavam em silencio: um caractere sem fonte na
maquina virava um quadrado, e ninguem no codigo sabia. Aqui o icone de cada
tela e' cobrado pelo nome, e cada desenho e' pintado de verdade num bitmap.
"""
import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from vantage.config import Settings  # noqa: E402
from vantage.ui import icons  # noqa: E402
from vantage.ui.components import IconButton, IconWidget, NavButton  # noqa: E402
from vantage.ui.main_window import NAV_GRUPOS, VIEW_CLASSES, Sidebar  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _pintar(nome: str, lado: int = 32):
    img = QImage(lado, lado, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    ok = icons.paint(p, nome, QRectF(0, 0, lado, lado), "#FFFFFF")
    p.end()
    return ok, img


def _tem_tinta(img: QImage) -> bool:
    return any(img.pixelColor(x, y).alpha() > 0
               for x in range(img.width()) for y in range(img.height()))


def test_toda_tela_tem_icone():
    for cls in VIEW_CLASSES:
        assert cls.key in icons.names(), cls.key


def test_todo_icone_desenha_alguma_coisa():
    for nome in icons.names():
        ok, img = _pintar(nome)
        assert ok and _tem_tinta(img), nome


def test_nome_desconhecido_nao_desenha_e_avisa():
    ok, img = _pintar("nao-existe")
    assert not ok
    assert not _tem_tinta(img)


def test_botao_da_barra_usa_o_icone_da_tela():
    btn = NavButton("cpu", "CPU", "x")
    assert isinstance(btn._glyph, IconWidget)
    btn.set_active(True, "#22D3EE")
    assert btn._glyph._color == "#22D3EE"


def test_tela_sem_icone_cai_no_glifo_de_texto():
    btn = NavButton("inexistente", "Algo", "#")
    assert not isinstance(btn._glyph, IconWidget)
    assert btn._glyph.text() == "#"


def test_botao_de_icone_troca_de_desenho():
    b = IconButton(tooltip="x", icon="more")
    assert b.icon == "more"
    assert b.text() == ""
    b.set_icon("close")
    assert b.icon == "close"


def test_grupos_da_barra_cobrem_todas_as_telas():
    agrupadas = {k for _titulo, chaves in NAV_GRUPOS for k in chaves}
    for cls in VIEW_CLASSES:
        assert cls.key in agrupadas, cls.key


def _janela_falsa() -> QWidget:
    janela = QWidget()
    janela.app = types.SimpleNamespace(settings=Settings())
    janela.show_view = lambda _k: None
    return janela


def test_barra_lateral_tem_um_botao_por_tela_e_os_rotulos_dos_grupos():
    barra = Sidebar(_janela_falsa())
    assert set(barra.buttons) == {cls.key for cls in VIEW_CLASSES}
    textos = {w.text() for w in barra.findChildren(QWidget) if hasattr(w, "text")
              and callable(w.text)}
    for titulo, _chaves in NAV_GRUPOS:
        assert titulo.upper() in textos, titulo
