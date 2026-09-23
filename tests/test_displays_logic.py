"""Logica pura em volta das telas: comparacao de arranjo e detecao de espelho."""
from vantage.app import _same_layout


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


# ── modo escalonado ──────────────────────────────────────────────────────────
def _tela_falsa(native, nome="TV"):
    from vantage.platform.displays import Display, Mode
    return Display(device="dev", name=nome, hardware_id="hw", monitor_id="mid",
                   active=True, primary=True, mode=Mode(1920, 1080, 60, 32),
                   position=(0, 0), native=native)


def test_modo_acima_do_painel_e_marcado_como_escalonado():
    """A GPU aceita e reduz na entrega (VSR na AMD); nao e' resolucao real.

    Sem essa marca, "4096 x 2160" numa TV 4K parece uma opcao melhor que a
    nativa, e aplicar so' estica a imagem.
    """
    from vantage.platform.displays import Mode

    tv = _tela_falsa((3840, 2160))
    assert tv.is_upscaled(Mode(4096, 2160, 60, 32)) is True
    assert tv.is_upscaled(Mode(3840, 2160, 144, 32)) is False
    assert tv.is_upscaled(Mode(1920, 1080, 60, 32)) is False


def test_altura_maior_tambem_conta():
    from vantage.platform.displays import Mode

    uw = _tela_falsa((3440, 1440))
    assert uw.is_upscaled(Mode(3440, 1600, 60, 32)) is True


def test_sem_edid_nao_chuta():
    """Sem a resolucao fisica do painel, dizer "escalonada" seria adivinhacao."""
    from vantage.platform.displays import Mode

    sem = _tela_falsa(None)
    assert sem.is_upscaled(Mode(9999, 9999, 60, 32)) is False


# ── tela girada ──────────────────────────────────────────────────────────────
def test_tela_em_retrato_nao_marca_a_propria_nativa_como_escalonada():
    """O EDID descreve o painel deitado; a lista do driver vem na orientacao
    atual. Em retrato, 1440 x 2560 E' a nativa de um painel 2560 x 1440, e a
    tela oferecia justamente ela como "escalonada"."""
    from vantage.platform.displays import DMDO_90, DMDO_270, Mode

    for giro in (DMDO_90, DMDO_270):
        tela = _tela_falsa((2560, 1440))
        tela.rotation = giro
        assert tela.native_oriented == (1440, 2560)
        assert tela.is_upscaled(Mode(1440, 2560, 144, 32)) is False
        assert tela.is_upscaled(Mode(2160, 3840, 60, 32)) is True


def test_tela_de_ponta_cabeca_continua_deitada():
    from vantage.platform.displays import DMDO_180

    tela = _tela_falsa((2560, 1440))
    tela.rotation = DMDO_180
    assert tela.native_oriented == (2560, 1440)


def test_melhor_modo_em_retrato_e_a_nativa_girada(monkeypatch):
    """Sem girar a nativa, nada casava e o fallback pegava o maior modo da lista:
    com VSR ligado, um escalonado que o app reimpunha a cada abertura."""
    import vantage.platform.displays as D

    modos = [D.Mode(2160, 3840, 60), D.Mode(1440, 2560, 144), D.Mode(1440, 2560, 60),
             D.Mode(1080, 1920, 144)]
    monkeypatch.setattr(D, "_supported_modes", lambda _dev: list(modos))
    monkeypatch.setattr(D, "_monitor_info", lambda _dev: ("GSM5BBF", "", ""))
    monkeypatch.setattr(D, "edid_native", lambda _hw: (2560, 1440))
    monkeypatch.setattr(D, "_current_mode", lambda _dev: (modos[1], (0, 0), D.DMDO_90))

    assert D.best_mode(r"\\.\DISPLAY9") == D.Mode(1440, 2560, 144)


def test_melhor_modo_deitado_continua_igual(monkeypatch):
    import vantage.platform.displays as D

    modos = [D.Mode(4096, 2160, 60), D.Mode(3840, 2160, 144), D.Mode(3840, 2160, 60)]
    monkeypatch.setattr(D, "_supported_modes", lambda _dev: list(modos))
    monkeypatch.setattr(D, "_monitor_info", lambda _dev: ("TCL9653", "", ""))
    monkeypatch.setattr(D, "edid_native", lambda _hw: (3840, 2160))
    monkeypatch.setattr(D, "_current_mode",
                        lambda _dev: (modos[2], (0, 0), D.DMDO_DEFAULT))

    assert D.best_mode(r"\\.\DISPLAY9") == D.Mode(3840, 2160, 144)


# ── espelho ──────────────────────────────────────────────────────────────────
def test_espelho_liga_todas_e_ancora_numa():
    """O caso do sofa: a imagem vai para a TV sem apagar os monitores da mesa."""
    from vantage.platform.displays import mirror_profile

    tv = _tela_falsa((3840, 2160), "Beyond TV")
    uw = _tela_falsa((3440, 1440), "ULTRAWIDE")
    perfil = mirror_profile(tv, [tv, uw])
    assert perfil["topology"] == "clone"
    assert all(e["active"] for e in perfil["entries"])
    assert sum(1 for e in perfil["entries"] if e["primary"]) == 1
    assert "Beyond TV" in perfil["name"]


def test_ancora_fora_da_lista_entra_mesmo_assim():
    """A TV costuma estar desligada na hora de montar o perfil."""
    from vantage.platform.displays import mirror_profile

    tv = _tela_falsa((3840, 2160), "Beyond TV")
    uw = _tela_falsa((3440, 1440), "ULTRAWIDE")
    perfil = mirror_profile(tv, [uw])
    assert len(perfil["entries"]) == 2
