"""Previa do overlay dentro das Configuracoes.

Configurar o overlay as cegas, abrindo um jogo a cada mexida para ver o
resultado, e' o que tornava essas opcoes praticamente inuteis.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication                     # noqa: E402

from dbxstats.config import Settings                           # noqa: E402
from dbxstats.ui.settings import _CfgPrevia, _CtlPrevia        # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_previa_le_o_que_esta_na_tela_e_nao_o_que_foi_salvo():
    """A graca e' ver o efeito ANTES de confirmar."""
    real = Settings()
    real.overlay_scale = 1.0
    falsa = _CfgPrevia(real, {"overlay_scale": 1.8})
    assert falsa.overlay_scale == 1.8
    assert real.overlay_scale == 1.0


def test_o_que_nao_foi_mexido_vem_do_que_esta_salvo():
    real = Settings()
    real.overlay_corner = "bottom-left"
    falsa = _CfgPrevia(real, {"overlay_scale": 1.2})
    assert falsa.overlay_corner == "bottom-left"


def test_controlador_falso_entrega_todas_as_pecas():
    """Faltando uma chave, a previa quebraria em vez de desenhar."""
    ctl = _CtlPrevia(Settings())
    d = ctl.last_data()
    for chave in ("cpu_pct", "cpu_temp_package", "cpu_temp_cores", "ram_used",
                  "ram_total", "ping_ms"):
        assert chave in d, chave
    for chave in ("usage", "temp", "temp_hotspot", "vram_used", "vram_total"):
        assert chave in d["gpu"], chave
    assert ctl.active_stream().app
    assert ctl.history.values("fps")
    assert ctl.ping.target_label


def test_a_previa_usa_a_classe_de_verdade():
    """Uma segunda implementacao so' para a previa envelheceria em silencio.

    O risco concreto: mexer no overlay e a previa continuar mostrando o desenho
    antigo, dando confianca falsa sobre uma configuracao.
    """
    from dbxstats.ui.overlay import GameOverlay
    from dbxstats.ui.settings import SettingsDialog
    import inspect

    fonte = inspect.getsource(SettingsDialog._atualizar_previa)
    assert "GameOverlay" in fonte
    assert GameOverlay is not None
