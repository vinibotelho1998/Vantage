"""Logica pura em volta das telas: comparacao de arranjo e detecao de espelho."""
from dbxstats.app import _same_layout


def _tela(mid, active=True, primary=False, pos=(0, 0), mode=(1920, 1080, 180)):
    return {"monitor_id": mid, "device": f"\\\\.\\{mid}", "active": active,
            "primary": primary, "position": list(pos),
            "mode": list(mode) if mode else None}


def test_arranjo_igual_ignora_ordem():
    a = [_tela("A", primary=True), _tela("B", pos=(1920, 0))]
    b = [_tela("B", pos=(1920, 0)), _tela("A", primary=True)]
    assert _same_layout(a, b)


def test_tela_desligada_muda_o_arranjo():
    a = [_tela("A", primary=True), _tela("B")]
    b = [_tela("A", primary=True), _tela("B", active=False)]
    assert not _same_layout(a, b)


def test_resolucao_diferente_muda_o_arranjo():
    a = [_tela("A", mode=(3840, 2160, 120))]
    b = [_tela("A", mode=(1920, 1080, 120))]
    assert not _same_layout(a, b)


def test_primaria_diferente_muda_o_arranjo():
    a = [_tela("A", primary=True), _tela("B")]
    b = [_tela("A"), _tela("B", primary=True)]
    assert not _same_layout(a, b)


def test_posicao_diferente_muda_o_arranjo():
    a = [_tela("A"), _tela("B", pos=(1920, 0))]
    b = [_tela("A"), _tela("B", pos=(0, 1080))]
    assert not _same_layout(a, b)
