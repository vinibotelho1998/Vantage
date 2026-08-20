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


# ── modo escalonado ──────────────────────────────────────────────────────────
def _tela_falsa(native, nome="TV"):
    from dbxstats.platform.displays import Display, Mode
    return Display(device="dev", name=nome, hardware_id="hw", monitor_id="mid",
                   active=True, primary=True, mode=Mode(1920, 1080, 60, 32),
                   position=(0, 0), native=native)


def test_modo_acima_do_painel_e_marcado_como_escalonado():
    """A GPU aceita e reduz na entrega (VSR na AMD); nao e' resolucao real.

    Sem essa marca, "4096 x 2160" numa TV 4K parece uma opcao melhor que a
    nativa, e aplicar so' estica a imagem.
    """
    from dbxstats.platform.displays import Mode

    tv = _tela_falsa((3840, 2160))
    assert tv.is_upscaled(Mode(4096, 2160, 60, 32)) is True
    assert tv.is_upscaled(Mode(3840, 2160, 144, 32)) is False
    assert tv.is_upscaled(Mode(1920, 1080, 60, 32)) is False


def test_altura_maior_tambem_conta():
    from dbxstats.platform.displays import Mode

    uw = _tela_falsa((3440, 1440))
    assert uw.is_upscaled(Mode(3440, 1600, 60, 32)) is True


def test_sem_edid_nao_chuta():
    """Sem a resolucao fisica do painel, dizer "escalonada" seria adivinhacao."""
    from dbxstats.platform.displays import Mode

    sem = _tela_falsa(None)
    assert sem.is_upscaled(Mode(9999, 9999, 60, 32)) is False


# ── espelho ──────────────────────────────────────────────────────────────────
def test_espelho_liga_todas_e_ancora_numa():
    """O caso do sofa: a imagem vai para a TV sem apagar os monitores da mesa."""
    from dbxstats.platform.displays import mirror_profile

    tv = _tela_falsa((3840, 2160), "Beyond TV")
    uw = _tela_falsa((3440, 1440), "ULTRAWIDE")
    perfil = mirror_profile(tv, [tv, uw])
    assert perfil["topology"] == "clone"
    assert all(e["active"] for e in perfil["entries"])
    assert sum(1 for e in perfil["entries"] if e["primary"]) == 1
    assert "Beyond TV" in perfil["name"]


def test_ancora_fora_da_lista_entra_mesmo_assim():
    """A TV costuma estar desligada na hora de montar o perfil."""
    from dbxstats.platform.displays import mirror_profile

    tv = _tela_falsa((3840, 2160), "Beyond TV")
    uw = _tela_falsa((3440, 1440), "ULTRAWIDE")
    perfil = mirror_profile(tv, [uw])
    assert len(perfil["entries"]) == 2
