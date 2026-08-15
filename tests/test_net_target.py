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
    p.set_auto_target("155.133.227.42", "jogo.exe")
    assert p._target() == ("155.133.227.42", 0)
    assert p.following_game is True
    assert p.target_label == "jogo.exe"


def test_voltar_para_o_host_fixo():
    p = PingMonitor("8.8.8.8", 53)
    p.set_auto_target("1.2.3.4", "jogo.exe")
    p.set_auto_target(None)
    assert p._target() == ("8.8.8.8", 53)
    assert p.following_game is False


def test_trocar_de_alvo_zera_o_historico():
    p = PingMonitor()
    p._history.extend([10.0, 11.0])
    p.set_auto_target("1.2.3.4", "jogo.exe")
    assert p.history() == []
