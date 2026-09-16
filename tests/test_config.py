from vantage.config import VIEWS, Settings


def test_defaults_roundtrip():
    d = Settings().as_dict()
    assert Settings.from_dict(d).as_dict() == d


def test_unknown_keys_ignored():
    s = Settings.from_dict({"foo": "bar", "accent": "green"})
    assert s.accent == "green"
    assert not hasattr(s, "foo")


def test_accent_fallback():
    assert Settings.from_dict({"accent": "neon"}).accent == "cyan"


def test_start_view_fallback():
    assert Settings.from_dict({"start_view": "nope"}).start_view == "dashboard"


def test_interval_snaps_to_nearest():
    assert Settings.from_dict({"update_interval": 0.9}).update_interval == 1.0
    assert Settings.from_dict({"update_interval": 0.3}).update_interval == 0.25


def test_fps_window_snaps():
    assert Settings.from_dict({"fps_window": 45.0}).fps_window == 30.0
    assert Settings.from_dict({"fps_window": 55.0}).fps_window == 60.0


def test_window_size_clamped():
    s = Settings.from_dict({"win_w": 100, "win_h": 99999})
    assert s.win_w == 900
    assert s.win_h == 4000


def test_ui_scale_clamped():
    assert Settings.from_dict({"ui_scale": 9.0}).ui_scale == 1.8
    assert Settings.from_dict({"ui_scale": 0.1}).ui_scale == 0.8


def test_overlay_metrics_filtered():
    s = Settings.from_dict({"overlay_metrics": ["fps", "lixo", "cpu"]})
    assert s.overlay_metrics == ["fps", "cpu"]


def test_overlay_metrics_never_empty():
    assert Settings.from_dict({"overlay_metrics": ["lixo"]}).overlay_metrics


def test_dash_cards_filtered():
    s = Settings.from_dict({"dash_cards": ["cpu", "inexistente"]})
    assert s.dash_cards == ["cpu"]


def test_alert_clamped():
    s = Settings.from_dict({"alert_cpu_temp": 500, "alert_ram_pct": -5})
    assert s.alert_cpu_temp == 120
    assert s.alert_ram_pct == 0


def test_ping_host_fallback():
    assert Settings.from_dict({"ping_host": "   "}).ping_host == "8.8.8.8"


def test_corner_fallback():
    assert Settings.from_dict({"overlay_corner": "meio"}).overlay_corner == "top-left"


def _profile(**extra):
    base = {"name": "TV", "entries": [{"device": r"\.\DISPLAY1", "active": True}]}
    base.update(extra)
    return base


def test_perfil_guarda_topologia_de_espelho():
    s = Settings.from_dict({"display_profiles": [_profile(topology="CLONE")]})
    assert s.display_profiles[0]["topology"] == "clone"


def test_perfil_topologia_desconhecida_vira_extend():
    s = Settings.from_dict({"display_profiles": [_profile(topology="pirueta")]})
    assert s.display_profiles[0]["topology"] == ""


def test_perfil_sem_topologia_continua_valido():
    s = Settings.from_dict({"display_profiles": [_profile()]})
    assert s.display_profiles[0]["topology"] == ""


def test_restaurar_telas_ao_fechar_ligado_por_padrao():
    assert Settings().display_restore_on_exit is True


def test_atalho_sem_caminho_e_descartado():
    s = Settings.from_dict({"launch_items": [{"name": "x"}]})
    assert s.launch_items == []


def test_atalho_ganha_nome_do_arquivo():
    s = Settings.from_dict({"launch_items": [{"path": r"C:\Games\bf6.exe"}]})
    assert s.launch_items[0]["name"] == "bf6"
    assert s.launch_items[0]["restore"] is True


def test_atalho_alvo_invalido_vira_vazio():
    s = Settings.from_dict({"launch_items": [{"path": "a.exe", "target": "voar:tv"}]})
    assert s.launch_items[0]["target"] == ""


def test_atalho_guarda_alvo_de_primaria():
    s = Settings.from_dict({"launch_items": [{"path": "a.exe", "target": r"primary:MON\TV"}]})
    assert s.launch_items[0]["target"] == r"primary:MON\TV"


# ── filtros do grafico do painel ─────────────────────────────────────────────
def test_linhas_do_painel_sobrevivem_ao_disco():
    """Escolher o que olhar e' trabalho; refazer a cada abertura e' atrito."""
    c = Settings()
    c.dashboard_plots = ["cpu", "gpu"]
    c.sanitize()
    assert c.dashboard_plots == ["cpu", "gpu"]


def test_linha_desconhecida_e_descartada():
    c = Settings()
    c.dashboard_plots = ["cpu", "npu", "gpu"]
    c.sanitize()
    assert c.dashboard_plots == ["cpu", "gpu"]


def test_lista_vazia_volta_ao_padrao():
    """Grafico em branco sem explicacao parece defeito, nao escolha."""
    c = Settings()
    c.dashboard_plots = []
    c.sanitize()
    assert set(c.dashboard_plots) == {"cpu", "gpu", "ram", "vram"}


def test_lixo_no_arquivo_nao_derruba():
    c = Settings()
    c.dashboard_plots = "cpu"
    c.sanitize()
    assert isinstance(c.dashboard_plots, list)


# ── teste de disco ───────────────────────────────────────────────────────────
# Aqui o risco nao e' cosmetico: essas opcoes decidem quantos gigabytes o app
# escreve na unidade do usuario.
def test_tamanho_absurdo_do_teste_de_disco_nao_passa():
    """999999 MiB no settings.json nao pode virar um arquivo temporario de 1 TB."""
    from vantage.sensors.diskbench import TAMANHOS_MIB

    assert Settings.from_dict({"diskbench_size_mib": 999999}).diskbench_size_mib \
        == max(TAMANHOS_MIB)
    assert Settings.from_dict({"diskbench_size_mib": "grande"}).diskbench_size_mib == 1024
    assert Settings.from_dict({"diskbench_size_mib": -8}).diskbench_size_mib \
        == min(TAMANHOS_MIB)


def test_fases_do_teste_de_disco_voltam_para_a_ordem_de_execucao():
    """Ler antes de escrever mediria um arquivo que ainda nao tem dado nenhum."""
    s = Settings.from_dict({"diskbench_phases": ["walea", "inexistente", "wseq"]})
    assert s.diskbench_phases == ["wseq", "walea"]


def test_teste_de_disco_sem_nenhuma_fase_volta_ao_completo():
    """Teste sem fase nao mede nada e ainda assim cria o arquivo na unidade."""
    from vantage.config import DISKBENCH_PHASES

    assert Settings.from_dict({"diskbench_phases": []}).diskbench_phases == \
        [k for k, _ in DISKBENCH_PHASES]


def test_fila_do_teste_de_disco_e_sempre_um():
    """O motor e' sincrono: guardar QD32 seria prometer o que ele nao faz."""
    assert Settings.from_dict({"diskbench_queue_depth": 32}).diskbench_queue_depth == 1


def test_chaves_das_fases_batem_com_o_motor():
    """Config e motor precisam falar a mesma lingua, ou a fase marcada some."""
    from vantage.config import DISKBENCH_PHASES
    from vantage.sensors.diskbench import CHAVES_FASES

    assert tuple(k for k, _ in DISKBENCH_PHASES) == CHAVES_FASES


def test_aba_de_jogos_mantem_a_chave_antiga():
    """O rotulo virou "Jogos", mas a chave continua "launcher".

    Trocar a chave faria sanitize() nao reconhecer o start_view de quem ja'
    escolhia essa aba e cair calado para o painel; foi o que aconteceu quando a
    tela "gaming" saiu de VIEWS.
    """
    assert "launcher" in VIEWS
    c = Settings.from_dict({"start_view": "launcher"})
    assert c.start_view == "launcher"


def test_aba_removida_no_passado_nao_deixa_o_app_sem_tela():
    c = Settings.from_dict({"start_view": "gaming"})
    assert c.start_view in VIEWS


def test_janela_fora_de_qualquer_tela_nao_e_restaurada():
    """A posicao guardada envelhece e o app parecia fechar sozinho.

    Basta fechar com a janela na TV e depois desligar a TV: a geometria salva
    aponta para o vazio, a janela nasce fora de qualquer monitor e, de fora,
    parece que o app nao abriu, com o processo vivo na bandeja o tempo todo.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vantage.ui.main_window import _cabe_em_alguma_tela

    app = QApplication.instance() or QApplication([])
    tela = app.primaryScreen().availableGeometry()

    assert _cabe_em_alguma_tela(tela.x() + 20, tela.y() + 20, 400, 300)
    assert not _cabe_em_alguma_tela(tela.right() + 500, tela.y(), 400, 300)
    assert not _cabe_em_alguma_tela(-9000, 0, 400, 300)


def test_canto_espiando_nao_conta_como_visivel():
    """Quarenta pixels de titulo na borda nao dao para arrastar de volta."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vantage.ui.main_window import _cabe_em_alguma_tela

    app = QApplication.instance() or QApplication([])
    tela = app.primaryScreen().availableGeometry()
    assert not _cabe_em_alguma_tela(tela.right() - 30, tela.y(), 1360, 860)


def test_metrica_aposentada_sai_de_quem_ja_tinha_config():
    """Mudar o padrao nao alcanca quem ja' tem arquivo salvo.

    Banda do controlador, teto de potencia e working set estrearam ligados e se
    mostraram ruins de conviver. Sem esta migracao eles continuariam na tela de
    quem ja' usava o app, e trocar o padrao pareceria nao ter feito nada.
    """
    c = Settings.from_dict({
        "settings_version": 2,
        "overlay_metrics": ["fps", "cpu", "mem_ctrl", "teto_watts", "jogo_ram_ws"],
    })
    assert "mem_ctrl" not in c.overlay_metrics
    assert "teto_watts" not in c.overlay_metrics
    assert "jogo_ram_ws" not in c.overlay_metrics
    assert "fps" in c.overlay_metrics and "cpu" in c.overlay_metrics


def test_quem_religar_depois_nao_perde_de_novo():
    """A remocao e' de uma vez so'; religar na mao tem de valer."""
    c = Settings.from_dict({
        "settings_version": 3,
        "overlay_metrics": ["fps", "mem_ctrl"],
    })
    assert "mem_ctrl" in c.overlay_metrics
