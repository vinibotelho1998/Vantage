"""Benchmark de disco: o risco nao e' o numero errado, e' o arquivo no lugar errado.

Escrever gigabytes e' a operacao mais destrutiva que este app faz. Os testes
abaixo cobrem, nessa ordem de gravidade: recusar unidade e espaco impossiveis,
nao deixar sobra de execucao anterior, parar de verdade quando mandam parar, e
so' entao a aritmetica da medida. Nada aqui toca no disco de verdade — o I/O e'
substituido por contador; o unico arquivo criado e' o `tmp_path` do pytest.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace

from dbxstats.sensors import diskbench


class _MotorFalso(diskbench.DiskBench):
    """Motor com o I/O trocado por contador: exercita o laco, nao o dispositivo."""

    def __init__(self, parar_apos: int | None = None) -> None:
        super().__init__()
        self.blocos = 0
        self.bytes = 0
        self.escritos = 0
        self.lidos = 0
        self.offsets: list[int] = []
        self._parar_apos = parar_apos

    def _posicionar(self, offset: int) -> None:
        self.offsets.append(offset)

    def _bloco(self, buffer, quantos: int, escrever: bool) -> int:
        self.blocos += 1
        self.bytes += quantos
        if escrever:
            self.escritos += quantos
        else:
            self.lidos += quantos
        if self._parar_apos is not None and self.blocos >= self._parar_apos:
            self._parar.set()
        return quantos


class _MotorSemDisco(_MotorFalso):
    """Alem do I/O, troca a abertura do arquivo: nada e' criado em lugar nenhum."""

    def _abrir(self, caminho) -> bool:
        self.abertos = getattr(self, "abertos", []) + [caminho]
        return True

    def _flush(self) -> None:
        pass


def _buffer(tamanho: int = diskbench.BLOCO_SEQ):
    return SimpleNamespace(tamanho=tamanho)


# ── recusas antes de escrever o primeiro byte ────────────────────────────────
def test_recusa_quando_o_arquivo_nao_cabe():
    ok, erro = diskbench.folga_suficiente(livre=1 << 30, total=500 << 30, tamanho=1 << 30)
    assert not ok and "insuficiente" in erro


def test_recusa_quando_deixaria_a_unidade_no_limite():
    """Cabe, mas encheria o SSD — disco cheio fica lento e NTFS precisa de folga."""
    livre = (4 << 30)
    ok, erro = diskbench.folga_suficiente(livre=livre, total=1000 << 30, tamanho=1 << 30)
    assert not ok and "livres" in erro


def test_aceita_unidade_com_folga_de_sobra():
    ok, erro = diskbench.folga_suficiente(livre=600 << 30, total=855 << 30, tamanho=1 << 30)
    assert ok and erro == ""


def test_espaco_livre_desconhecido_e_motivo_para_recusar():
    """Nao conseguir medir o espaco nao autoriza tentar: pode nao haver nenhum."""
    ok, _ = diskbench.folga_suficiente(livre=0, total=0, tamanho=1 << 30)
    assert not ok


def test_unidade_de_rede_e_optica_sao_recusadas():
    """Medir um compartilhamento mediria a rede; CD nao aceita escrita."""
    assert not diskbench.tipo_aceito(diskbench.DRIVE_REMOTE)[0]
    assert not diskbench.tipo_aceito(diskbench.DRIVE_CDROM)[0]
    assert diskbench.tipo_aceito(diskbench.DRIVE_FIXED)[0]
    assert diskbench.tipo_aceito(diskbench.DRIVE_REMOVABLE)[0]


# ── pasta temporaria ─────────────────────────────────────────────────────────
def test_pasta_de_teste_fica_na_unidade_escolhida():
    """Escrever noutra unidade mediria o disco errado e encheria o disco errado."""
    temp = Path(tempfile.gettempdir())
    assert diskbench._pasta_base(temp.drive + "\\") == temp


def test_limpar_sobras_so_apaga_o_que_e_nosso_e_ja_esfriou(tmp_path, monkeypatch):
    """Sobra antiga sai; pasta de terceiro e teste em andamento ficam intactos."""
    import os
    import time

    nossa_velha = tmp_path / (diskbench.PREFIXO + "velha")
    nossa_nova = tmp_path / (diskbench.PREFIXO + "agora")
    alheia = tmp_path / "documentos-importantes"
    for pasta in (nossa_velha, nossa_nova, alheia):
        pasta.mkdir()
        (pasta / "teste.tmp").write_bytes(b"x")
    antigo = time.time() - diskbench.IDADE_SOBRA_S - 60
    os.utime(nossa_velha, (antigo, antigo))

    monkeypatch.setattr(diskbench, "_pasta_base", lambda _m: tmp_path)
    assert diskbench.limpar_sobras("X:\\") == 1
    assert not nossa_velha.exists()
    assert nossa_nova.exists()
    assert alheia.exists()


# ── parada ───────────────────────────────────────────────────────────────────
def test_cancelar_interrompe_no_meio_do_arquivo():
    """Sem essa checada entre blocos, cancelar so' faria efeito no fim de 1 GiB."""
    motor = _MotorFalso(parar_apos=3)
    motor._sequencial(_buffer(), tamanho=64 * diskbench.BLOCO_SEQ,
                      escrever=True, fase="teste")
    assert motor.blocos == 3


def test_cancelado_no_primeiro_bloco_nao_inventa_taxa():
    """Zero byte medido em tempo nenhum nao e' 'infinito', e' 'nao sei'."""
    motor = _MotorFalso()
    motor._parar.set()
    assert motor._sequencial(_buffer(), tamanho=1 << 30, escrever=False,
                             fase="teste") is None


# ── medida ───────────────────────────────────────────────────────────────────
def test_uma_passada_cobre_o_arquivo_inteiro(monkeypatch):
    monkeypatch.setattr(diskbench, "TEMPO_MINIMO_FASE", 0.0)
    motor = _MotorFalso()
    tamanho = 8 * diskbench.BLOCO_SEQ
    motor._sequencial(_buffer(), tamanho=tamanho, escrever=False, fase="teste")
    assert motor.bytes == tamanho
    assert motor.offsets == [0]              # sequencial volta ao inicio uma vez so'


def test_passadas_extras_quando_o_disco_e_rapido_demais(monkeypatch):
    """Um NVMe engole 1 GiB em decimos de segundo; uma passada so' e' ruido puro."""
    monkeypatch.setattr(diskbench, "TEMPO_MINIMO_FASE", 999.0)
    motor = _MotorFalso(parar_apos=10)
    motor._sequencial(_buffer(), tamanho=4 * diskbench.BLOCO_SEQ,
                      escrever=False, fase="teste")
    assert len(motor.offsets) > 1


def test_arquivo_pequeno_demais_nao_gera_teste_aleatorio():
    """Sem espaco para sortear posicao, o 4K aleatorio nao mede nada."""
    motor = _MotorFalso()
    assert motor._aleatorio(_buffer(diskbench.BLOCO_ALEA),
                            tamanho=diskbench.BLOCO_ALEA,
                            escrever=False, fase="teste") == (None, None)


def test_aleatorio_so_sorteia_posicao_alinhada():
    """FILE_FLAG_NO_BUFFERING recusa qualquer deslocamento fora do setor."""
    motor = _MotorFalso(parar_apos=64)
    motor._aleatorio(_buffer(diskbench.BLOCO_ALEA), tamanho=64 * 1024 * 1024,
                     escrever=False, fase="teste")
    assert motor.offsets
    assert all(o % diskbench.BLOCO_ALEA == 0 for o in motor.offsets)


def test_alinhamento_arredonda_sempre_para_baixo():
    """Arredondar para cima passaria do tamanho pedido e do fim do arquivo."""
    assert diskbench.alinhar(4097, 4096) == 4096
    assert diskbench.alinhar(4096, 4096) == 4096
    assert diskbench.alinhar(100, 4096) == 0


def test_taxa_recusa_medida_impossivel():
    assert diskbench.taxa(0, 1.0) is None
    assert diskbench.taxa(1000, 0.0) is None
    assert diskbench.taxa(2048, 2.0) == 1024.0


# ── barra de progresso ───────────────────────────────────────────────────────
def test_progresso_e_do_teste_inteiro_e_nunca_recua():
    """A barra andava para tras, e isso se le' como travamento.

    Cada fase publicava a fracao dela propria, entao o valor voltava a zero a
    cada troca de fase (64%, 24%, 14%, 5%). E dentro da fase repetia: cada
    passada de medicao recomecava do zero.
    """
    from dbxstats.sensors.diskbench import FASES, DiskBench

    b = DiskBench()
    visto = []
    for fase in FASES:
        for fracao in (0.0, 0.5, 1.0, 0.0, 0.7):   # repeticao de passada
            b._publicar(fase, fracao)
            visto.append(b.estado()["progresso"])
        assert b.estado()["fase"] == fase

    assert visto == sorted(visto), visto
    assert visto[-1] <= 1.0
    # cada fase tem de somar sua fatia do total
    assert b.estado()["progresso"] >= (len(FASES) - 1) / len(FASES)


def test_fase_desconhecida_nao_quebra_a_barra():
    from dbxstats.sensors.diskbench import DiskBench

    b = DiskBench()
    b._publicar("fase que nao existe", 0.5)
    assert 0.0 <= b.estado()["progresso"] <= 1.0


def test_barra_fecha_na_ultima_fase_marcada():
    """Com duas fases marcadas, a barra tem de chegar a 100% — e nao a 40%.

    O denominador era o teste completo; quem rodasse so' a leitura 4K veria a
    barra parar no meio e concluir, que se le' como teste interrompido.
    """
    b = diskbench.DiskBench()
    b._roteiro = [diskbench.FASE_PREPARO, diskbench.ROTULOS_FASES["ralea"]]
    b._publicar(diskbench.ROTULOS_FASES["ralea"], 1.0)
    assert b.estado()["progresso"] == 1.0


# ── opcoes escolhidas pelo usuario ───────────────────────────────────────────
def test_folga_exigida_acompanha_o_tamanho_escolhido():
    """Escolher 4 GiB e continuar validando 1 GiB encheria a unidade do usuario."""
    livre, total = 7 << 30, 120 << 30
    assert diskbench.folga_suficiente(livre, total, 1 << 30)[0]
    ok, erro = diskbench.folga_suficiente(livre, total, 4 << 30)
    assert not ok and erro


def test_iniciar_valida_o_espaco_com_o_tamanho_pedido():
    """A recusa acontece antes de qualquer byte: nenhuma thread chega a subir."""
    vistos: list[int] = []
    motor = diskbench.DiskBench()
    motor._validar = lambda mount, tamanho: (vistos.append(tamanho), (False, "sem espaço"))[1]
    pedido = 4 * 1024 * diskbench.MIB
    ok, erro = motor.iniciar("X:\\", diskbench.Opcoes(tamanho=pedido))
    assert not ok and erro == "sem espaço"
    assert vistos == [pedido]
    assert not motor.ativo


def test_opcoes_estragadas_no_settings_viram_teste_valido():
    """settings.json editado a mao nao pode virar pedido de 1 TB de arquivo."""
    o = diskbench.Opcoes(tamanho=999 << 30, fases=("banana", "rseq"),
                         segundos_fase=0.0, profundidade=32).normalizar()
    assert o.tamanho == diskbench.TAMANHO_MAXIMO
    assert o.fases == ("rseq",)
    assert o.segundos_fase >= 0.2
    assert o.profundidade == 1


def test_fases_fora_de_ordem_voltam_para_a_ordem_de_execucao():
    """Ler antes de escrever mediria um arquivo que ainda nao tem dado nenhum."""
    assert diskbench.Opcoes(fases=("walea", "rseq", "wseq")).normalizar().fases == (
        "wseq", "rseq", "walea")


def test_lista_de_fases_vazia_vira_teste_completo():
    """Teste sem fase nenhuma nao mede nada e ainda cria o arquivo — sem sentido."""
    assert diskbench.Opcoes(fases=()).normalizar().fases == diskbench.CHAVES_FASES


def test_profundidade_de_fila_maior_que_um_e_recusada():
    """QD>1 exigiria I/O assincrono; aceitar o numero seria rotular QD1 de QD32."""
    assert diskbench.PROFUNDIDADES == (1,)
    assert diskbench.Opcoes(profundidade=32).normalizar().profundidade == 1


def test_teto_de_tempo_acompanha_o_minimo_escolhido():
    """Com 6 s por fase, um teto fixo de 8 s cortaria a medida quase no comeco."""
    assert diskbench.Opcoes(segundos_fase=6.0).tempo_maximo >= 30.0
    assert diskbench.Opcoes(segundos_fase=0.5).tempo_maximo == diskbench.TEMPO_MAXIMO_FASE


# ── fases marcadas e desmarcadas ─────────────────────────────────────────────
def _opcoes(**kw) -> diskbench.Opcoes:
    base = {"tamanho": 8 * diskbench.BLOCO_SEQ, "segundos_fase": 0.0}
    base.update(kw)
    return diskbench.Opcoes(**base)


def test_fase_desmarcada_nao_roda_nem_aparece_no_resultado():
    """Desmarcar leitura tem de economizar o I/O, e nao so' esconder o numero."""
    motor = _MotorSemDisco()
    r = motor._medir(Path("teste.tmp"), "X:\\", _opcoes(fases=("wseq",)), setor=4096)
    assert motor.lidos == 0
    assert r.leitura_seq is None and r.leitura_alea is None and r.escrita_alea is None
    assert r.fases == ("wseq",)


def test_so_leitura_marcada_grava_o_arquivo_antes_de_medir():
    """Ler um arquivo de zero byte devolveria uma taxa que nao mediu disco nenhum.

    A gravacao acontece na fase "preparando" e fica fora do cronometro — o
    resultado nao traz numero de escrita porque escrita nao foi o que se mediu.
    """
    motor = _MotorSemDisco()
    tamanho = 8 * diskbench.BLOCO_SEQ
    r = motor._medir(Path("teste.tmp"), "X:\\", _opcoes(fases=("rseq",)), setor=4096)
    assert motor.escritos == tamanho          # exatamente uma gravacao do arquivo
    assert motor.lidos >= tamanho
    assert r.escrita_seq is None


def test_cada_fase_cai_no_campo_certo_do_resultado():
    """Trocar leitura 4K por escrita 4K no resultado passaria despercebido na tela."""
    motor = _MotorSemDisco()
    motor._sequencial = lambda buffer, tamanho, escrever, fase, tempo_minimo=None, \
        tempo_maximo=None: (11.0 if escrever else 22.0)
    motor._aleatorio = lambda buffer, tamanho, escrever, fase, segundos=None: (
        (33.0, 44.0) if escrever else (55.0, 66.0))
    r = motor._medir(Path("teste.tmp"), "X:\\", _opcoes(), setor=4096)
    assert (r.escrita_seq, r.leitura_seq) == (11.0, 22.0)
    assert (r.leitura_alea, r.iops_leitura) == (55.0, 66.0)
    assert (r.escrita_alea, r.iops_escrita) == (33.0, 44.0)


def test_escrita_sequencial_marcada_dispensa_o_preparo():
    """Ela ja' deixa o arquivo cheio; preparar antes seria gravar tudo duas vezes."""
    motor = _MotorSemDisco()
    tamanho = 8 * diskbench.BLOCO_SEQ
    motor._medir(Path("teste.tmp"), "X:\\",
                 _opcoes(fases=("wseq", "rseq")), setor=4096)
    assert motor.escritos == tamanho


def test_a_leitura_mede_so_o_pedaco_que_a_escrita_gravou():
    """Num disco lento o teto de tempo corta a escrita no meio do arquivo.

    Ler o arquivo inteiro depois disso bateria no fim do dado valido: o Windows
    devolve zero byte na hora, e esse trecho entraria na conta como se tivesse
    sido lido em tempo nenhum — inflando a leitura.
    """
    motor = _MotorSemDisco()
    pedidos: list[tuple[bool, int]] = []
    curto = 2 * diskbench.BLOCO_SEQ

    def _seq(buffer, tamanho, escrever, fase, tempo_minimo=None, tempo_maximo=None):
        pedidos.append((escrever, tamanho))
        if escrever:
            motor._validos = curto
        return 1.0

    motor._sequencial = _seq
    tamanho = 64 * diskbench.BLOCO_SEQ
    motor._medir(Path("teste.tmp"), "X:\\",
                 _opcoes(tamanho=tamanho, fases=("wseq", "rseq")), setor=4096)
    assert pedidos == [(True, tamanho), (False, curto)]


def test_aleatorio_nao_sorteia_alem_do_dado_gravado():
    """Escrever 4K depois do fim do arquivo faz o NTFS zerar o buraco no meio da medida."""
    motor = _MotorFalso(parar_apos=64)
    tamanho = 4 * 1024 * 1024
    motor._aleatorio(_buffer(diskbench.BLOCO_ALEA), tamanho=tamanho,
                     escrever=True, fase="teste", segundos=0.2)
    assert motor.offsets
    assert max(motor.offsets) <= tamanho - diskbench.BLOCO_ALEA


def test_cancelar_no_preparo_nao_deixa_nenhuma_medida_inventada():
    """Parar antes de existir dado valido tem de devolver 'nao sei', nao um numero."""
    motor = _MotorSemDisco(parar_apos=2)
    r = motor._medir(Path("teste.tmp"), "X:\\",
                     _opcoes(fases=("rseq", "ralea")), setor=4096)
    assert r.leitura_seq is None and r.leitura_alea is None


def test_o_tempo_escolhido_chega_em_todas_as_fases():
    """Se o tempo por fase nao descesse ate' o laco, a opcao seria so' enfeite."""
    motor = _MotorSemDisco()
    seq: list[tuple] = []
    alea: list[float] = []
    motor._sequencial = lambda buffer, tamanho, escrever, fase, tempo_minimo=None, \
        tempo_maximo=None: (seq.append((tempo_minimo, tempo_maximo)) or 1.0)
    motor._aleatorio = lambda buffer, tamanho, escrever, fase, segundos=None: (
        alea.append(segundos) or (1.0, 1.0))
    opcoes = _opcoes(segundos_fase=3.0)
    motor._medir(Path("teste.tmp"), "X:\\", opcoes, setor=4096)
    assert seq == [(3.0, opcoes.tempo_maximo)] * 2
    assert alea == [3.0, 3.0]
