"""Limpeza de memoria: o risco e' derrubar o Windows e mentir sobre o ganho.

Esvaziar o working set do gerenciador de sessao, do subsistema de tempo de
execucao ou do compositor nao libera nada util e desestabiliza a maquina na hora.
O outro risco e' de comunicacao: apresentar "memoria disponivel subiu" como se
fosse desempenho ganho, quando logo depois o sistema fica mais lento repovoando
o cache que acabou de ser jogado fora.

Nenhum teste aqui chama a API do Windows: as quatro dependencias de `limpar`
entram por parametro justamente para a regra ser exercitada sem mexer na memoria
da maquina que roda os testes.
"""
from vantage.platform import memclean


def _limpar(processos, esvaziar=None, standby=None, antes=8.0, depois=12.0):
    valores = iter((antes, depois))
    return memclean.limpar(
        processos=lambda: processos,
        esvaziar=esvaziar or (lambda _pid: True),
        standby=standby or (lambda: (True, "")),
        disponivel=lambda: next(valores))


# ── quem fica de fora ────────────────────────────────────────────────────────
def test_processos_do_kernel_nunca_sao_tocados():
    """PID 0 e 4 nao sao processos comuns; nem ha' handle para abrir neles."""
    assert memclean.e_critico(0, "System Idle Process")
    assert memclean.e_critico(4, "System")


def test_compositor_e_subsistemas_ficam_de_fora():
    """Zerar o working set do DWM faz a tela piscar e nao libera nada relevante."""
    for nome in ("dwm.exe", "csrss.exe", "winlogon.exe", "lsass.exe", "smss.exe"):
        assert memclean.e_critico(999, nome), nome


def test_nome_com_caixa_diferente_ainda_e_reconhecido():
    """A lista de processos do Windows nao promete caixa nenhuma."""
    assert memclean.e_critico(999, "  DWM.EXE  ")


def test_aplicativo_comum_pode_ser_limpo():
    assert not memclean.e_critico(1234, "game.exe")
    assert not memclean.e_critico(1234, "chrome.exe")


def test_criticos_sao_contados_e_pulados():
    tocados = []
    r = _limpar(
        [(0, "System Idle Process"), (4, "System"), (900, "dwm.exe"),
         (1234, "game.exe"), (5678, "chrome.exe")],
        esvaziar=lambda pid: tocados.append(pid) or True)
    assert tocados == [1234, 5678]
    assert r.limpos == 2
    assert r.ignorados == 3
    assert r.falhas == 0


# ── falhas esperadas ─────────────────────────────────────────────────────────
def test_processo_protegido_conta_como_recusa_e_nao_quebra():
    """Anticheat e antivirus recusam OpenProcess; isso e' normal, nao e' erro."""
    r = _limpar([(1234, "anticheat.exe"), (5678, "jogo.exe")],
                esvaziar=lambda pid: pid != 1234)
    assert r.limpos == 1 and r.falhas == 1
    assert r.avisos and "esperado" in r.avisos[0]


def test_erro_de_sistema_ao_abrir_processo_nao_derruba_a_limpeza():
    """Processo que morre no meio da varredura vira OSError; a fila continua."""
    def esvaziar(pid):
        if pid == 1234:
            raise OSError("processo saiu")
        return True

    r = _limpar([(1234, "morreu.exe"), (5678, "vivo.exe")], esvaziar=esvaziar)
    assert r.limpos == 1 and r.falhas == 1


def test_standby_recusada_nao_cancela_o_resto():
    """Sem elevacao a standby nao vai; os working sets ja' foram liberados."""
    r = _limpar([(1234, "jogo.exe")],
                standby=lambda: (False, "Abra o Vantage como administrador."))
    assert r.limpos == 1
    assert r.standby is False
    assert "administrador" in r.erro_standby


# ── o que a tela mostra ──────────────────────────────────────────────────────
def test_ganho_e_a_diferenca_medida_e_nao_uma_promessa():
    r = _limpar([(1234, "jogo.exe")], antes=8.0, depois=12.5)
    assert r.liberado_gb == 4.5


def test_sem_leitura_de_memoria_nao_ha_ganho_para_mostrar():
    """Se psutil nao respondeu, o campo fica vazio em vez de virar 0,00 GB."""
    r = memclean.limpar(processos=lambda: [], esvaziar=lambda _p: True,
                        standby=lambda: (True, ""), disponivel=lambda: None)
    assert r.liberado_gb is None
    assert "disponível" not in memclean.resumo(r)


def test_resumo_diz_o_que_aconteceu_com_a_standby():
    limpa = _limpar([(1234, "jogo.exe")])
    assert "standby descartada" in memclean.resumo(limpa)
    mantida = _limpar([(1234, "jogo.exe")], standby=lambda: (False, "sem privilégio"))
    assert "standby mantida" in memclean.resumo(mantida)


def test_resumo_nao_promete_desempenho():
    """A frase da tela fala de memoria liberada, nunca de ficar mais rapido."""
    texto = memclean.resumo(_limpar([(1234, "jogo.exe")])).lower()
    for palavra in ("rápido", "acelera", "desempenho", "otimiza", "fps"):
        assert palavra not in texto
