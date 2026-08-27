"""Uma copia por vez: o guarda que impede duas instancias se sabotarem.

Duas copias nao apenas duplicam janela: cada uma varre as sessoes ETW e derruba
a da outra, porque o nome carrega o pid e nenhuma reconhece a outra como
legitima. Nenhuma das duas captura quadros, e o log nao denuncia a causa.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from dbxstats.platform.instancia import InstanciaUnica  # noqa: E402


def test_a_primeira_assume_a_vaga():
    guarda = InstanciaUnica()
    try:
        assert guarda.assumir() is True
    finally:
        guarda.liberar()


def test_a_segunda_e_recusada():
    primeira = InstanciaUnica()
    segunda = InstanciaUnica()
    try:
        assert primeira.assumir() is True
        assert segunda.assumir() is False
    finally:
        primeira.liberar()
        segunda.liberar()


def test_a_vaga_volta_quando_a_primeira_sai():
    """O mutex e' do kernel: sai junto com o processo, inclusive num taskkill.

    Arquivo de trava nao daria essa garantia; ficaria para tras depois de um
    travamento e o app nunca mais abriria.
    """
    primeira = InstanciaUnica()
    primeira.assumir()
    primeira.liberar()

    segunda = InstanciaUnica()
    try:
        assert segunda.assumir() is True
    finally:
        segunda.liberar()


def test_pedir_foco_sem_ninguem_ouvindo_nao_quebra():
    """Corrida real: a copia antiga pode estar saindo no exato instante."""
    assert InstanciaUnica.pedir_foco() is False


def test_a_segunda_faz_a_primeira_aparecer():
    """Sair calado seria pior que abrir duas: quem clicou no atalho de novo
    concluiria que o app parou de abrir."""
    primeira = InstanciaUnica()
    chamadas = []
    try:
        assert primeira.assumir() is True
        primeira.ouvir(lambda: chamadas.append(1))
        time.sleep(0.3)

        assert InstanciaUnica.pedir_foco() is True
        for _ in range(20):
            if chamadas:
                break
            time.sleep(0.1)
        assert chamadas, "a primeira instancia nao foi avisada"
    finally:
        primeira.liberar()


def test_erro_no_callback_nao_derruba_a_escuta():
    """Falha ao mostrar a janela nao pode matar a thread e deixar o guarda surdo."""
    primeira = InstanciaUnica()
    vezes = []

    def explode():
        vezes.append(1)
        raise RuntimeError("janela sumiu")

    try:
        primeira.assumir()
        primeira.ouvir(explode)
        time.sleep(0.3)
        InstanciaUnica.pedir_foco()
        time.sleep(0.6)
        InstanciaUnica.pedir_foco()
        time.sleep(0.6)
        assert len(vezes) >= 2, "a escuta morreu no primeiro erro"
    finally:
        primeira.liberar()


def test_escopo_e_da_sessao_de_logon():
    r"""Local\ deixa cada usuario com a sua copia numa troca rapida de usuario;
    o que nao pode e' a MESMA pessoa abrir duas."""
    from dbxstats.platform import instancia

    assert instancia.NOME_MUTEX.startswith("Local\\")
    assert instancia.NOME_EVENTO.startswith("Local\\")
