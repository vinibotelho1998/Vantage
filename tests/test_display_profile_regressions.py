"""Perfis simulados: nenhum teste altera as telas da maquina."""
from types import SimpleNamespace
import pytest
from vantage.platform import displays as D


def ambiente(monkeypatch, falha=""):
    telas = [D.Display("A", "A", "hwA", "A", True, True, D.Mode(1920,1080,60), (0,0)),
             D.Display("B", "B", "hwB", "B", True, False, D.Mode(1920,1080,60), (1920,0))]
    monkeypatch.setattr(D, "list_displays", lambda **k: telas)
    monkeypatch.setattr(D.ccd, "query", lambda **k: None)
    monkeypatch.setattr(D.ccd, "set_topology", lambda paths: (True, "ok"))
    def modo(device, valor):
        if falha == "modo": return False, "recusado"
        next(t for t in telas if t.device == device).mode = valor
        return True, "ok"
    def posicoes(valores):
        if falha == "posicoes": return False, "recusado"
        for t in telas: t.position = valores[t.monitor_id]
        return True, "ok"
    def primaria(mid):
        if falha == "primaria": return False, "recusado"
        for t in telas: t.primary = t.monitor_id == mid
        return True, "ok"
    monkeypatch.setattr(D, "set_mode", modo)
    monkeypatch.setattr(D.ccd, "set_positions", posicoes)
    monkeypatch.setattr(D.ccd, "make_primary", primaria)
    entradas = [{"monitor_id": t.monitor_id, "active": True, "primary": t.monitor_id=="B",
                 "mode": [1280,720,60], "position": [i*1280,0]} for i,t in enumerate(telas)]
    return telas, entradas


@pytest.mark.parametrize("falha", ["modo", "posicoes", "primaria"])
def test_falha_intermediaria_nao_e_sucesso(monkeypatch, falha):
    _, entradas = ambiente(monkeypatch, falha)
    ok, erro = D.apply_profile(entradas)
    assert ok is False and "parcialmente" in erro


def test_aplicacao_confirmada(monkeypatch):
    _, entradas = ambiente(monkeypatch)
    assert D.apply_profile(entradas) == (True, "ok")


def test_monitor_desconectado_recusa_antes_de_mutar(monkeypatch):
    _, entradas = ambiente(monkeypatch)
    chamadas = []
    monkeypatch.setattr(D.ccd, "set_topology", lambda paths: chamadas.append(paths))
    entradas.append({"monitor_id":"desligado", "active":True})
    assert D.apply_profile(entradas)[0] is False
    assert chamadas == []


def test_modo_recusado_no_clone_nao_anuncia_modo_pedido(monkeypatch):
    telas, entradas = ambiente(monkeypatch, "modo")
    ccd_ambiente(monkeypatch, telas)
    def clonar(modo):
        for tela in telas: tela.position = (0,0)
        return True, "ok"
    monkeypatch.setattr(D.ccd, "set_topology_mode", clonar)
    monkeypatch.setattr(D, "_supported_modes", lambda dev: [D.Mode(1280,720,60)])
    ok, erro = D.apply_profile(entradas, "clone")
    assert ok is False and "parcialmente" in erro


def ccd_ambiente(monkeypatch, telas, somente_uma_fonte=False):
    # Destinos fisicos podem compartilhar um unico \\.\DISPLAY1.
    paths = [SimpleNamespace(mid=t.monitor_id, targetInfo=SimpleNamespace(targetAvailable=True))
             for t in telas]
    cfg = SimpleNamespace(paths=paths, path_count=len(paths), active_paths=lambda: paths)
    monkeypatch.setattr(D.ccd, "query", lambda **k: cfg)
    monkeypatch.setattr(D.ccd, "target_name", lambda p: (p.mid, p.mid))
    monkeypatch.setattr(D.ccd, "source_name", lambda p: "fonte" if somente_uma_fonte else p.mid)
    def fonte(c, p):
        tela = next(t for t in telas if t.monitor_id == p.mid)
        return SimpleNamespace(position=SimpleNamespace(x=tela.position[0], y=tela.position[1]),
                               width=tela.mode.width, height=tela.mode.height, pixelFormat=4)
    monkeypatch.setattr(D.ccd, "source_mode", fonte)
    monkeypatch.setattr(D, "_current_mode", lambda dev: (telas[0].mode, telas[0].position, 0)
                        if somente_uma_fonte else (next(t for t in telas if t.device==dev).mode, (0,0), 0))


def test_clone_confirma_destinos_que_compartilham_gdi(monkeypatch):
    telas, entradas = ambiente(monkeypatch)
    for tela in telas:
        tela.position = (0,0)
    ccd_ambiente(monkeypatch, telas, somente_uma_fonte=True)
    # GDI lista uma tela; CCD ainda possui os dois destinos fisicos.
    monkeypatch.setattr(D, "list_displays", lambda **k: [telas[0]])
    monkeypatch.setattr(D.ccd, "set_topology_mode", lambda modo: (True, "ok"))
    monkeypatch.setattr(D, "_supported_modes", lambda dev: [D.Mode(1280,720,60)])
    chamadas = []
    def modo(dev, valor):
        chamadas.append(dev)
        for tela in telas: tela.mode = valor
        return True, "ok"
    monkeypatch.setattr(D, "set_mode", modo)
    assert D.apply_profile(entradas, "clone") == (True, "espelhado em 1280 x 720 @ 60 Hz")
    assert chamadas == ["fonte"]


def test_clone_nao_confirma_conteudos_estendidos(monkeypatch):
    telas, entradas = ambiente(monkeypatch)
    ccd_ambiente(monkeypatch, telas)
    monkeypatch.setattr(D.ccd, "set_topology_mode", lambda modo: (True, "ok"))
    ok, erro = D.apply_profile(entradas, "clone")
    assert ok is False and "nao confirmou" in erro


def test_clone_desconectado_recusa_antes_de_mutar(monkeypatch):
    telas, entradas = ambiente(monkeypatch)
    ccd_ambiente(monkeypatch, telas[:1])
    chamadas = []
    monkeypatch.setattr(D.ccd, "set_topology_mode", lambda modo: chamadas.append(modo))
    assert D.apply_profile(entradas, "clone")[0] is False
    assert chamadas == []


def test_perfil_estendido_restaura_destino_oculto_pelo_clone(monkeypatch):
    telas, entradas = ambiente(monkeypatch)
    ccd_ambiente(monkeypatch, telas, somente_uma_fonte=True)
    aplicadas = []
    monkeypatch.setattr(D, "list_displays", lambda **k: telas if aplicadas else telas[:1])
    def estender(paths):
        aplicadas.append(paths)
        return True, "ok"
    monkeypatch.setattr(D.ccd, "set_topology", estender)
    assert D.apply_profile(entradas) == (True, "ok")
    assert aplicadas == [["A", "B"]]


def test_rollback_recusado_nao_anuncia_restauracao(monkeypatch):
    from vantage.ui.views import displays as view
    mensagens = []
    fake = SimpleNamespace(cfg=SimpleNamespace(display_confirm_seconds=10), reload=lambda:None,
                           window=lambda:None, notify=lambda texto, cor:mensagens.append(texto))
    def recusar(desc, seconds, undo, parent):
        undo()
        return False
    monkeypatch.setattr(view, "ask_confirm", recusar)
    assert view.DisplaysView.confirm_or_revert(fake, "aplicado", lambda:(False,"driver recusou")) is False
    assert "não consegui restaurar" in mensagens[-1]
