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
        self.offsets: list[int] = []
        self._parar_apos = parar_apos

    def _posicionar(self, offset: int) -> None:
        self.offsets.append(offset)

    def _bloco(self, buffer, quantos: int, escrever: bool) -> int:
        self.blocos += 1
        self.bytes += quantos
        if self._parar_apos is not None and self.blocos >= self._parar_apos:
            self._parar.set()
        return quantos


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
    for i, fase in enumerate(FASES):
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
