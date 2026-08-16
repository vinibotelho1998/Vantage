"""Descoberta do servidor do jogo pelo trafego."""
import socket
import struct

from dbxstats.sensors import peer


def _pacote_udp(origem: str, destino: str, sport: int, dport: int, carga: int = 40) -> bytes:
    """Datagrama IPv4/UDP minimo, do jeito que o socket raw entrega."""
    cabecalho = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + 8 + carga, 0, 0, 64, 17, 0,
                            socket.inet_aton(origem), socket.inet_aton(destino))
    return cabecalho + struct.pack("!HHHH", sport, dport, 8 + carga, 0) + b"\x00" * carga


def _conta(pacotes, portas):
    """Reproduz a contagem do farejador sobre uma lista de pacotes."""
    import collections
    contagem = collections.Counter()
    for dados in pacotes:
        ihl = (dados[0] & 0x0F) * 4
        if dados[9] != 17:
            continue
        sport, dport = struct.unpack("!HH", dados[ihl:ihl + 4])
        if sport in portas:
            contagem[(socket.inet_ntoa(dados[16:20]), dport)] += 1
        elif dport in portas:
            contagem[(socket.inet_ntoa(dados[12:16]), sport)] += 1
    return contagem


def test_par_mais_falante_e_o_servidor():
    portas = {49884}
    pacotes = [_pacote_udp("192.168.1.20", "155.133.227.35", 49884, 27032) for _ in range(30)]
    pacotes += [_pacote_udp("155.133.227.35", "192.168.1.20", 27032, 49884) for _ in range(28)]
    pacotes += [_pacote_udp("192.168.1.20", "1.1.1.1", 49884, 53) for _ in range(2)]
    contagem = _conta(pacotes, portas)
    assert contagem.most_common(1)[0][0] == ("155.133.227.35", 27032)


def test_trafego_de_outro_processo_e_ignorado():
    contagem = _conta([_pacote_udp("192.168.1.20", "8.8.4.4", 55555, 53)], {49884})
    assert contagem == {}


def test_portas_locais_ignora_processos_de_sistema():
    assert peer.local_ports(0) == set()
    assert peer.local_ports(4) == set()


def test_finder_sem_alvo_nao_devolve_par():
    f = peer.PeerFinder()
    assert f.peer is None
    f.watch(1234)
    assert f.peer is None       # ainda nao farejou


def test_finder_troca_de_alvo_descarta_o_par_antigo():
    f = peer.PeerFinder()
    f._pid = 1234
    f._checked_pid = 1234
    f._peer = ("155.133.227.35", 27032)
    assert f.peer == ("155.133.227.35", 27032)
    f.watch(9999)
    assert f.peer is None


def test_piscada_do_jogo_nao_joga_o_cache_fora():
    """Perder o foco tira o jogo da lista por um instante; o servidor continua o mesmo."""
    f = peer.PeerFinder()
    f._pid = 1234
    f._checked_pid = 1234
    f._peer = ("155.133.227.35", 27032)
    f.watch(0)                                   # jogo sumiu da lista
    assert f.peer is None
    f.watch(1234)                                # e voltou
    assert f.peer == ("155.133.227.35", 27032)   # sem farejar de novo
