"""Escolha do servidor do jogo e troca de alvo do ping."""
from dbxstats.sensors.net import PingMonitor, _publico


def test_endereco_publico_ipv4():
    assert _publico("155.133.227.42") is True


def test_endereco_privado_nao_serve():
    for ip in ("192.168.0.10", "10.0.0.1", "127.0.0.1", "0.0.0.0", "224.0.0.1"):
        assert _publico(ip) is False, ip


def test_ipv6_fica_de_fora():
    """O ICMP daqui e' v4; alvo v6 seria lido como perda total."""
    assert _publico("2607:6bc0::10") is False


def test_lixo_nao_quebra():
    assert _publico("nao-e-ip") is False


def test_alvo_automatico_substitui_o_host_fixo():
    p = PingMonitor("8.8.8.8", 53)
    assert p._target() == ("8.8.8.8", 53)
    p.set_auto_target("155.133.227.42", 27019, "jogo.exe")
    assert p._target() == ("155.133.227.42", 27019)
    assert p.following_game is True
    assert p.target_label == "jogo.exe"


def test_voltar_para_o_host_fixo():
    p = PingMonitor("8.8.8.8", 53)
    p.set_auto_target("1.2.3.4", 1234, "jogo.exe")
    p.set_auto_target(None)
    assert p._target() == ("8.8.8.8", 53)
    assert p.following_game is False


def test_trocar_de_alvo_zera_o_historico():
    p = PingMonitor()
    p._history.extend([10.0, 11.0])
    p.set_auto_target("1.2.3.4", 1234, "jogo.exe")
    assert p.history() == []


def test_alvo_mudo_volta_para_o_host_fixo():
    """Servidor que ignora ICMP nao pode virar '100% de perda' na cara do usuario."""
    p = PingMonitor("8.8.8.8", 53)
    p.set_auto_target("203.0.113.7", 27015, "jogo.exe")
    p._publish("203.0.113.7", [None, None, None])
    assert p.following_game is False
    assert p._target() == ("8.8.8.8", 53)
    assert p.read()["loss"] is None          # nada foi publicado sobre o alvo mudo


def test_alvo_mudo_nao_e_readotado():
    p = PingMonitor("8.8.8.8", 53)
    p.set_auto_target("203.0.113.7", 27015, "jogo.exe")
    p._publish("203.0.113.7", [None])
    p.set_auto_target("203.0.113.7", 27015, "jogo.exe")
    assert p.following_game is False


def test_perda_real_do_host_fixo_continua_sendo_publicada():
    p = PingMonitor("8.8.8.8", 53)
    p._publish("8.8.8.8", [12.0, None, 14.0, None])
    assert p.read()["loss"] == 50.0


def test_medida_do_trafego_manda_na_leitura():
    """Sem depender do servidor responder ICMP: o numero vem do proprio jogo."""
    p = PingMonitor("8.8.8.8", 53)
    p._publish("8.8.8.8", [18.0, 18.0])
    assert p.read()["ms"] == 18.0
    p.set_measured(15.2, 1.4, "dota2.exe")
    leitura = p.read()
    assert leitura["ms"] == 15.2
    assert leitura["jitter"] == 1.4
    assert p.measuring_game is True
    assert p.target_label == "dota2.exe"


def test_medida_velha_devolve_a_sonda():
    p = PingMonitor("8.8.8.8", 53)
    p._publish("8.8.8.8", [18.0])
    p.set_measured(15.2, 1.0, "jogo.exe")
    p._measured_at -= 60.0            # envelheceu
    assert p.measuring_game is False
    assert p.read()["ms"] == 18.0


def test_limpar_medida_volta_para_a_sonda():
    p = PingMonitor("8.8.8.8", 53)
    p._publish("8.8.8.8", [20.0])
    p.set_measured(15.0, 1.0, "jogo.exe")
    p.set_measured(None, None, "")
    assert p.read()["ms"] == 20.0


def test_leitura_fica_com_a_menor_das_duas_medidas():
    """Sonda e medida passiva carregam sobras diferentes; a rede e' o piso comum.

    A sonda leva o tempo de tratar o ICMP; a passiva leva o tick do servidor.
    Mostrar a maior das duas era o que deixava o numero 1 ms acima do que o
    proprio jogo exibe.
    """
    p = PingMonitor("8.8.8.8", 53)
    p._publish("155.133.227.57", [15.0, 15.0, 16.0, 15.0])   # sonda: 15.2
    p.set_measured(16.4, 1.1, "cs2.exe")                     # passiva: tick do servidor
    assert p.read()["ms"] == 15.2
    assert p.read()["jitter"] == 1.1     # jitter continua vindo do trafego do jogo


def test_medida_passiva_vale_sozinha_quando_a_sonda_nao_responde():
    p = PingMonitor("8.8.8.8", 53)
    p.set_measured(16.4, 1.1, "cs2.exe")
    assert p.read()["ms"] == 16.4


def test_sem_jogo_nao_mostra_o_dns_de_reserva():
    """"8.8.8.8" aparecia no overlay como se fosse o servidor da partida.

    Sem partida identificada o ping vai para um DNS publico so' para ter alguma
    referencia de latencia. Esse endereco nao diz nada sobre o jogo, entao nao
    tem por que carregar um rotulo.
    """
    m = PingMonitor("8.8.8.8", 53)
    assert m.target_label == ""


def test_com_servidor_do_jogo_o_rotulo_aparece():
    m = PingMonitor("8.8.8.8", 53)
    m.set_auto_target("155.133.227.42", 27015, "cs2")
    assert m.target_label == "cs2"


def test_medida_pelo_trafego_tambem_ganha_rotulo():
    """Aqui nem ha' servidor descoberto: o numero vem do trafego do proprio jogo."""
    m = PingMonitor("8.8.8.8", 53)
    m.set_measured(15.2, 1.4, "cs2.exe")
    assert m.target_label == "cs2.exe"
