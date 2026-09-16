"""Capa dos jogos: qual imagem cada atalho ganha, e como ela e' desenhada."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.config import _clean_launch_item  # noqa: E402
from vantage.platform import art  # noqa: E402
from vantage.ui.bigpicture import BigPicture  # noqa: E402

_app = QApplication.instance() or QApplication([])


# ── forma da imagem decide o desenho ─────────────────────────────────────────
def test_quadrado_e_tratado_como_icone():
    assert BigPicture._e_icone(QPixmap(256, 256)) is True


def test_header_deitado_nao_e_icone():
    """460x215 e' o header do Steam: arte de verdade, tem que cobrir o card."""
    assert BigPicture._e_icone(QPixmap(460, 215)) is False


def test_pixmap_vazio_nao_quebra():
    """QPixmap nulo tem altura zero; dividir por ela derrubaria a grade inteira."""
    assert BigPicture._e_icone(QPixmap()) is False


# ── cascata de origem ────────────────────────────────────────────────────────
def test_imagem_escolhida_ganha_de_tudo(tmp_path):
    capa = tmp_path / "capa.png"
    QPixmap(8, 8).save(str(capa), "PNG")
    item = {"path": str(tmp_path / "jogo.exe"), "image": str(capa)}
    assert art.artwork_path(item) == capa
    assert art.origin(item) == "escolhida"


def test_imagem_apagada_do_disco_nao_e_usada(tmp_path):
    """Apontar para arquivo que sumiu tem que cair para a proxima fonte, e nao
    devolver um caminho quebrado para o desenho."""
    item = {"path": str(tmp_path / "jogo.exe"), "image": str(tmp_path / "sumiu.png")}
    assert art.artwork_path(item) is None
    assert art.origin(item) == "nenhuma"


def test_jogo_inexistente_fica_sem_capa(tmp_path):
    item = {"path": str(tmp_path / "nao-existe.exe"), "image": ""}
    assert art.artwork_path(item) is None


def test_appid_sai_do_atalho_url(tmp_path):
    """Atalho do Steam nao tem executavel: o appid e' a unica pista de capa."""
    url = tmp_path / "jogo.url"
    url.write_text("[InternetShortcut]\nURL=steam://rungameid/2807960\n",
                   encoding="utf-8")
    assert art._appid_do_url(url) == "2807960"


def test_url_sem_appid_devolve_vazio(tmp_path):
    url = tmp_path / "site.url"
    url.write_text("[InternetShortcut]\nURL=https://exemplo.com\n", encoding="utf-8")
    assert art._appid_do_url(url) == ""


# ── o campo sobrevive ao settings.json ───────────────────────────────────────
def test_config_guarda_a_capa_escolhida():
    item = _clean_launch_item({"path": "C:/j.exe", "image": "  C:/capa.png  "})
    assert item["image"] == "C:/capa.png"


def test_config_aceita_atalho_antigo_sem_o_campo():
    """settings.json gravado antes desta versao nao pode invalidar o atalho."""
    item = _clean_launch_item({"path": "C:/j.exe"})
    assert item["image"] == ""


def test_todo_rotulo_de_origem_existe():
    """origin() so' devolve chave que a interface saiba escrever."""
    assert set(art.ORIGIN_LABEL) == {"escolhida", "steam", "icone", "nenhuma"}
