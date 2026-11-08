"""Script do KWin que posiciona o painel flutuante: texto gerado e ciclo de carga."""
import json
import sys

import pytest

from vantage.platform import kwin

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="KWin so' existe no Linux")


class _Barramento:
    def __init__(self, id_do_script=7):
        self.chamadas = []
        self.id = id_do_script

    def __call__(self, caminho, interface, metodo, *args):
        self.chamadas.append((caminho, metodo, args))
        return self.id if metodo == "loadScript" else True


def test_script_casa_pelo_titulo_e_define_a_geometria():
    texto = kwin.gerar_script('Vantage "Overlay"', 12, 34, 400, 180)
    assert json.dumps('Vantage "Overlay"') in texto            # aspas escapadas, nao quebram o JS
    assert "w.keepAbove = true" in texto
    assert "x: 12, y: 34, width: 400, height: 180" in texto
    assert "workspace.windowAdded.connect(ajustar)" in texto


def test_carrega_roda_e_so_recarrega_quando_a_geometria_muda(tmp_path):
    bus = _Barramento()
    fixador = kwin.Fixador(chamar=bus, pasta=tmp_path)
    assert fixador.aplicar(10, 20, 300, 100)
    metodos = [m for _, m, _ in bus.chamadas]
    assert metodos == ["unloadScript", "loadScript", "run"]
    assert ("/Scripting/Script7", "run", ()) in bus.chamadas
    assert (tmp_path / "kwin-overlay.js").read_text().count("x: 10, y: 20") == 1

    n = len(bus.chamadas)
    assert fixador.aplicar(10, 20, 300, 100)                  # igual: nada a fazer
    assert len(bus.chamadas) == n
    assert fixador.aplicar(11, 20, 300, 100)                  # mudou: recarrega
    assert len(bus.chamadas) > n


def test_recusa_do_kwin_nao_estoura_e_devolve_falso(tmp_path):
    bus = _Barramento(id_do_script=-1)
    assert not kwin.Fixador(chamar=bus, pasta=tmp_path).aplicar(0, 0, 10, 10)


def test_sem_barramento_nada_acontece(tmp_path):
    fixador = kwin.Fixador(chamar=lambda *a: None, pasta=tmp_path)
    assert not fixador.aplicar(0, 0, 10, 10)


def test_remover_descarrega_o_script(tmp_path):
    bus = _Barramento()
    fixador = kwin.Fixador(chamar=bus, pasta=tmp_path)
    fixador.aplicar(1, 2, 3, 4)
    bus.chamadas.clear()
    fixador.remover()
    assert [(m, a) for _, m, a in bus.chamadas] == [("unloadScript", (kwin.NOME_DO_SCRIPT,))]


def test_fora_do_wayland_nao_ha_kwin(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert not kwin.disponivel()


def test_script_real_do_kwin_e_aceito_sem_mexer_em_janela_nenhuma(tmp_path, monkeypatch):
    """Carrega no KWin de verdade um script que casa um titulo que nao existe."""
    import os

    monkeypatch.setenv("XDG_SESSION_TYPE", os.environ.get("VANTAGE_TESTE_SESSAO_REAL", ""))
    if not kwin.disponivel():
        pytest.skip("sem KWin Wayland nesta sessao")
    fixador = kwin.Fixador(pasta=tmp_path)
    monkey_titulo = "__titulo_que_nenhuma_janela_tem__"
    arquivo = tmp_path / "kwin-overlay.js"
    arquivo.write_text(kwin.gerar_script(monkey_titulo, 0, 0, 10, 10), encoding="utf-8")
    ident = kwin._chamar_dbus("/Scripting", "org.kde.kwin.Scripting", "loadScript", str(arquivo), "vantage-teste")
    try:
        assert isinstance(ident, int) and ident >= 0
    finally:
        kwin._chamar_dbus("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "vantage-teste")
    del fixador
