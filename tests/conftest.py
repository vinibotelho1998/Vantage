"""Isola os testes do app instalado: nada de escrever no %APPDATA% de verdade."""
import os
import tempfile

os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")
os.environ.setdefault("VANTAGE_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "vantage-tests"))

# Estes modulos carregam DLLs do Windows (ctypes.WinDLL) ao importar; no Linux nem
# da' para coletar. A cobertura de Linux fica em test_linux_port.py e nos testes
# de cada modulo que tem versao propria.
# A suite nao pode mexer nas janelas de quem a roda: com a sessao Wayland de verdade
# visivel, o painel flutuante dos testes carregaria um script no KWin que casa pelo
# titulo e reposicionaria o painel REAL do usuario, se estiver aberto. O teste que
# fala com o KWin de proposito le a sessao verdadeira daqui.
os.environ.setdefault("VANTAGE_TESTE_SESSAO_REAL", os.environ.get("XDG_SESSION_TYPE", ""))
os.environ["XDG_SESSION_TYPE"] = "tty"

collect_ignore = [] if os.name == "nt" else [
    "test_ccd_consulta.py", "test_coletor_com.py", "test_display_profile_regressions.py",
    "test_displays_canvas.py", "test_dualsense.py", "test_gpumem.py", "test_instancia_unica.py",
    "test_memclean.py", "test_pads.py", "test_tela_controle.py", "test_win_janelas.py",
]

if os.name != "nt":
    # Varios testes montam telas sem dono. No Linux, com o PySide6 do sistema
    # (6.12) no Python 3.14, soltar uma arvore de layouts assim pela coleta de
    # lixo derruba o processo com falha de segmentacao no meio dos testes. O app
    # de verdade nao passa por isso, porque as telas moram dentro da janela
    # principal. A suite e' curta: sem coleta ciclica ela termina inteira.
    import gc

    gc.disable()


# Testes que exercitam comportamento que so' existe no Windows: registro, ETW e
# PresentMon, CCD de monitores, WMI, gamepad XInput, benchmark de disco e o launcher
# com troca de tela. No Linux o app nao tem esses caminhos (ver README, secao Linux),
# entao o teste nao tem o que provar la'. Cada um segue rodando no Windows.
SO_WINDOWS = {
    "test_autostart.py": (
        "test_ligar_grava_o_comando_na_chave_run",
        "test_desligar_remove_e_desligar_de_novo_nao_quebra",
    ),
    "test_bigpicture.py": (
        "test_foco_anda_com_o_direcional",
        "test_segurar_nao_dispara_todo_tique",
        "test_sem_jogos_nao_quebra",
        "test_a_escolhe_o_jogo_em_foco",
        "test_segurar_a_nao_abre_duas_vezes",
        "test_start_tambem_abre",
        "test_b_fecha",
        "test_back_sozinho_nao_faz_nada_aqui",
    ),
    "test_disk_volume_mapping.py": (
        "test_dois_volumes_do_mesmo_disco_compartilham_sensor_com_ordem_invertida",
        "test_disco_sem_temperatura_nao_desloca_sensor_do_outro",
        "test_cache_de_volumes_e_mapa_inclusive_vazio_dura_vinte_segundos",
    ),
    "test_displays_logic.py": (
        "test_modo_acima_do_painel_e_marcado_como_escalonado",
        "test_altura_maior_tambem_conta",
        "test_sem_edid_nao_chuta",
        "test_tela_em_retrato_nao_marca_a_propria_nativa_como_escalonada",
        "test_tela_de_ponta_cabeca_continua_deitada",
        "test_melhor_modo_em_retrato_e_a_nativa_girada",
        "test_melhor_modo_deitado_continua_igual",
        "test_espelho_liga_todas_e_ancora_numa",
        "test_ancora_fora_da_lista_entra_mesmo_assim",
    ),
    "test_fps_generation.py": (
        "test_supervisor_aposentado_nao_limpa_nem_publica_sobre_o_novo",
        "test_createprocess_atrasado_nao_para_a_sessao_nova",
        "test_stop_limpa_apenas_a_sessao_que_estava_rodando",
    ),
    "test_gamepad.py": (
        "test_combo_liga_e_desliga",
        "test_combo_desligado_nas_configuracoes",
        "test_controle_sumindo_desliga_o_modo",
        "test_diagrama_usa_layout_sony_quando_pedido",
        "test_todo_botao_desenhado_tem_geometria",
        "test_teclado_virtual_nao_pisca_console_na_tela",
    ),
    "test_gamescan.py": (
        "test_scan_sobrevive_a_fonte_que_falha",
    ),
    "test_identidade_barra.py": (
        "test_define_a_identidade_do_processo",
        "test_nao_derruba_o_app_quando_a_api_falta",
    ),
    "test_launch_bench.py": (
        "test_media_do_sistema_no_resumo_e_so_da_partida",
    ),
    "test_launch_display.py": (
        "test_tela_desligada_acende_e_assume",
        "test_tela_ja_ligada_so_vira_principal",
        "test_falha_ao_assumir_desfaz_o_que_ligamos",
        "test_tela_ausente_nao_cancela_o_jogo",
    ),
    "test_launcher_varredura.py": (
        "test_trocar_a_tela_do_big_picture_grava_e_redesenhar_nao_grava",
    ),
    "test_memory_view.py": (
        "test_benchmark_recusado_explica_o_motivo_na_propria_tela",
        "test_resultado_do_teste_chega_mesmo_com_a_aba_no_fundo",
        "test_fechar_o_app_cancela_o_teste_em_andamento",
        "test_o_tamanho_escolhido_chega_ao_motor",
        "test_a_unidade_escolhida_manda_no_botao_de_testar",
        "test_desmarcar_a_ultima_fase_e_ignorado",
        "test_fase_desmarcada_nao_deixa_travessao_no_resultado",
        "test_iops_de_uma_fase_so_diz_qual_fase_foi_medida",
        "test_o_resumo_mostra_o_espaco_que_o_teste_vai_exigir",
        "test_so_leitura_marcada_avisa_que_o_arquivo_e_gravado_antes",
    ),
    "test_overlay_arranjo.py": (
        "test_o_aviso_de_administrador_sobrevive_ao_corte_do_compacto",
    ),
    "test_presentmon_orfao.py": (
        "test_pede_para_sair_em_vez_de_matar",
        "test_sinal_que_nao_chega_cai_para_terminate",
    ),
    "test_rodape_saude.py": (
        "test_captura_parada_fica_vermelha",
    ),
    "test_session.py": (
        "test_argumentos_vazios",
        "test_argumentos_respeitam_aspas",
        "test_caminho_entre_aspas_chega_inteiro_ao_jogo",
        "test_jogo_abre_com_a_linha_montada",
        "test_arquivo_inexistente_nao_inicia",
        "test_atalho_com_apostrofo_no_nome_resolve",
        "test_atalho_para_pasta_com_acento_resolve",
        "test_atalho_de_loja_nao_chuta_nome_de_processo",
        "test_exe_direto_segue_pelo_proprio_nome",
    ),
}


def pytest_collection_modifyitems(config, items):
    if os.name == "nt":
        return
    import pytest

    pular = pytest.mark.skip(reason="comportamento exclusivo do Windows")
    for item in items:
        nomes = SO_WINDOWS.get(item.path.name)
        if nomes and item.name.split("[")[0] in nomes:
            item.add_marker(pular)


_status = {"codigo": 0}


def pytest_sessionfinish(session, exitstatus):
    _status["codigo"] = int(exitstatus)


def pytest_unconfigure(config):
    """Sai sem deixar o interpretador desmontar o Qt fora de ordem.

    Roda depois do resumo do pytest, entao o relatorio sai inteiro.
    """
    if os.name == "nt":
        return
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_status["codigo"])
