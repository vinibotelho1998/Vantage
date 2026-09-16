"""Benchmark de disco: leitura e escrita, sequencial e aleatoria, por unidade.

Como o numero sai honesto
-------------------------
Medir disco em Windows sem desligar o cache mede o cache: um arquivo recem
escrito continua inteiro na RAM e a "leitura" volta a 20 GB/s, que nao existe.
Por isso o arquivo e' aberto com FILE_FLAG_NO_BUFFERING e FILE_FLAG_WRITE_THROUGH:
o I/O vai direto ao dispositivo, sem passar pelo cache do sistema. Esses flags
exigem que buffer, deslocamento e tamanho de cada operacao sejam multiplos do
setor fisico, e e' isso que o resto do modulo faz com tanto cuidado de alinhamento.

Se o volume nao aceitar (rede, sistema de arquivos exotico), o teste cai para I/O
comum e marca `cache_evitado=False`, para a tela poder avisar que o numero de
leitura esta' otimista em vez de fingir que esta' certo.

Seguranca do arquivo temporario
-------------------------------
E' a parte que mais importa: um benchmark de disco escreve gigabytes, e escrever
no lugar errado destroi dado de verdade. As regras aqui sao:

* a pasta e' criada por `mkdtemp` na propria unidade testada, entao o nome nunca
  colide com nada que ja' exista e o teste nunca sai da unidade escolhida;
* o arquivo e' aberto com CREATE_NEW: se por absurdo o caminho ja' existisse, a
  abertura falharia em vez de sobrescrever;
* o arquivo nasce com FILE_FLAG_DELETE_ON_CLOSE, ou seja, quem apaga e' o proprio
  Windows quando o handle fecha, inclusive se o processo morrer no meio;
* `finally` e `atexit` ainda tentam remover arquivo e pasta, e uma varredura no
  inicio limpa sobra de execucao anterior que tenha escapado de tudo isso.

O que o usuario escolhe
-----------------------
`Opcoes` carrega tamanho do arquivo, quais fases rodar e quanto tempo medir cada
uma. Duas consequencias que o resto do modulo trata com cuidado:

* o tamanho manda na checagem de espaco livre: escolher 4 GiB e continuar
  validando 1 GiB seria a forma mais facil de encher a unidade do usuario;
* fase de leitura sem fase de escrita nao tem o que ler. Nesse caso o arquivo e'
  gravado antes, na fase "preparando", fora do cronometro. Sem isso a leitura
  bateria no fim do arquivo vazio e devolveria um numero que nao mediu nada, e o
  4K aleatorio escreveria alem do fim do arquivo, o que faz o NTFS zerar o
  buraco no meio da medida.
"""
from __future__ import annotations

import atexit
import ctypes
import os
import random
import shutil
import tempfile
import threading
import time
import weakref
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path

import psutil

from .. import log

_log = log.get("diskbench")

MIB = 1024 * 1024
TAMANHO_PADRAO = 1024 * MIB
"""1 GiB. Grande o bastante para nao caber em cache de controlador nem em SLC."""

TAMANHOS_MIB = (256, 512, 1024, 2048, 4096)
"""Tamanhos oferecidos na tela, em MiB.

Nao e' so' "rapido x demorado". O que enche o cache SLC do SSD e' o total gravado
na fase, que e' o tamanho vezes o numero de passadas: um arquivo pequeno cabe no
cache e e' reescrito la' dentro varias vezes, entao a taxa medida e' a do cache:
num SSD medido logo depois de encher o cache, 256 MiB ainda reportou 2,2 GB/s
enquanto 4 GiB na mesma hora reportou 0,35 GB/s. Arquivo grande com tempo maior
por fase e' o unico jeito de chegar na escrita sustentada.
"""

TAMANHO_MINIMO = 64 * MIB
TAMANHO_MAXIMO = 16 * 1024 * MIB

BLOCO_SEQ = 4 * MIB
BLOCO_ALEA = 4096
"""4 KiB QD1: o bloco que representa carga de sistema operacional e de jogo."""

MARGEM_LIVRE = 2 * 1024 ** 3
"""Folga exigida alem do arquivo de teste.

SSD cheio fica lento e NTFS precisa de espaco para metadado; encher a unidade
para medir velocidade seria pior do que nao medir.
"""

FRACAO_LIVRE_MINIMA = 0.05
TEMPO_MINIMO_FASE = 1.5
TEMPO_MAXIMO_FASE = 8.0
TEMPO_ALEATORIO = 2.0
SEGUNDOS_POR_FASE = (0.5, 1.5, 3.0, 6.0)
"""Tempo minimo de medicao por fase, oferecido na tela.

Menos que isso e a medida vira ruido do agendador; mais estabiliza o numero em
troca de um teste mais demorado.
"""

PROFUNDIDADES = (1,)
"""Profundidades de fila oferecidas, uma so', e de proposito.

Fila maior que 1 significa deixar varias operacoes pendentes no dispositivo ao
mesmo tempo, e isso exige I/O assincrono de verdade: FILE_FLAG_OVERLAPPED, uma
estrutura OVERLAPPED por requisicao e espera em evento, ou varios handles em
varias threads. Este motor usa ReadFile/WriteFile sincronos, que so' retornam
quando a operacao terminou; repetir a chamada em laco continua sendo QD1.
Chamar isso de QD32 daria um numero maior e falso, entao a lista tem um item so'.
"""

TEMPO_MAXIMO_FATOR = 5.0
"""Teto de uma fase em relacao ao minimo pedido.

O teto existe para o caso oposto ao do NVMe: num disco lento uma unica passada
por um arquivo de 4 GiB pode levar minutos, e a fase precisa terminar. Como ele
acompanha o minimo escolhido, pedir 6 s por fase nao esbarra num teto de 8 s.
"""

PREFIXO = "vantage-bench-"
IDADE_SOBRA_S = 3600.0

CHAVES_FASES = ("wseq", "rseq", "ralea", "walea")
"""Ordem de execucao, nao so' de exibicao: a escrita sequencial e' o que deixa o
arquivo com dado valido para as tres fases seguintes lerem."""

ROTULOS_FASES = {"wseq": "escrita seq.", "rseq": "leitura seq.",
                 "ralea": "leitura 4K", "walea": "escrita 4K"}
"""Nomes curtos de proposito: viram texto de badge numa barra ja' apertada."""

FASE_PREPARO = "preparando"
FASES = (FASE_PREPARO,) + tuple(ROTULOS_FASES[c] for c in CHAVES_FASES)


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
CREATE_NEW = 1
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_WRITE_THROUGH = 0x80000000
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_FLAG_DELETE_ON_CLOSE = 0x04000000
FILE_BEGIN = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5

_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_kernel32.SetFilePointerEx.restype = wintypes.BOOL
_kernel32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                       ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
_kernel32.FlushFileBuffers.restype = wintypes.BOOL
_kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetDriveTypeW.restype = wintypes.UINT
_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetDiskFreeSpaceW.restype = wintypes.BOOL
_kernel32.GetDiskFreeSpaceW.argtypes = [wintypes.LPCWSTR] + [ctypes.POINTER(wintypes.DWORD)] * 4


class BenchError(RuntimeError):
    """Falha ja' traduzida para o usuario final."""


@dataclass(frozen=True)
class Opcoes:
    """O que o usuario escolheu na tela.

    Imutavel de proposito: a thread do teste le' isso sem trava nenhuma, e mudar
    o tamanho no meio da corrida quebraria a validacao de espaco que ja' passou.
    """

    tamanho: int = TAMANHO_PADRAO
    fases: tuple[str, ...] = CHAVES_FASES
    segundos_fase: float = TEMPO_MINIMO_FASE
    profundidade: int = 1

    def normalizar(self) -> Opcoes:
        """Devolve opcoes que o motor pode executar sem se machucar.

        A ordem das fases e' reimposta aqui: um settings.json com "rseq" antes de
        "wseq" faria a leitura acontecer antes de existir dado no arquivo.
        """
        pedidas = {c for c in self.fases if isinstance(c, str)}
        fases = tuple(c for c in CHAVES_FASES if c in pedidas) or CHAVES_FASES
        tamanho = max(TAMANHO_MINIMO, min(TAMANHO_MAXIMO, int(self.tamanho or 0)))
        segundos = max(0.2, min(30.0, float(self.segundos_fase or TEMPO_MINIMO_FASE)))
        return replace(self, tamanho=tamanho, fases=fases, segundos_fase=segundos,
                       profundidade=PROFUNDIDADES[0])

    @property
    def precisa_preparar(self) -> bool:
        """Se ha' fase que depende de dado que a escrita sequencial nao vai gravar."""
        return "wseq" not in self.fases and bool(self.fases)

    @property
    def tempo_maximo(self) -> float:
        return max(TEMPO_MAXIMO_FASE, self.segundos_fase * TEMPO_MAXIMO_FATOR)


@dataclass(frozen=True)
class Resultado:
    unidade: str
    escrita_seq: float | None = None
    leitura_seq: float | None = None
    leitura_alea: float | None = None
    escrita_alea: float | None = None
    iops_leitura: float | None = None
    iops_escrita: float | None = None
    bytes_arquivo: int = 0
    cache_evitado: bool = True
    cancelado: bool = False
    segundos: float = 0.0
    fases: tuple[str, ...] = CHAVES_FASES
    """Quais fases de fato rodaram: a tela esconde as linhas das outras em vez
    de mostrar travessao, que se le' como 'o teste falhou aqui'."""
    segundos_fase: float = TEMPO_MINIMO_FASE
    profundidade: int = 1


def _gb(n: float) -> str:
    return f"{n / 1024 ** 3:.1f} GB"


def folga_suficiente(livre: int, total: int, tamanho: int) -> tuple[bool, str]:
    """Decide se da' para escrever o arquivo de teste sem sufocar a unidade.

    Duas barreiras: a folga fixa, que protege metadado e arquivo de paginacao, e
    a folga proporcional, que evita encher um disco pequeno ate' a borda.
    """
    if tamanho <= 0:
        return False, "Tamanho de teste inválido."
    if livre <= 0:
        return False, "Não foi possível medir o espaço livre da unidade."
    if livre < tamanho + MARGEM_LIVRE:
        return False, (f"Espaço livre insuficiente: o teste precisa de {_gb(tamanho)} "
                       f"mais {_gb(MARGEM_LIVRE)} de folga e a unidade tem "
                       f"{_gb(livre)} livres.")
    if total > 0 and (livre - tamanho) < total * FRACAO_LIVRE_MINIMA:
        return False, (f"O teste deixaria a unidade com menos de "
                       f"{FRACAO_LIVRE_MINIMA * 100:.0f}% livres. Libere espaço antes.")
    return True, ""


def tipo_aceito(tipo: int) -> tuple[bool, str]:
    """So' disco local. Rede e midia optica dariam numero de outra coisa."""
    if tipo == DRIVE_REMOTE:
        return False, "Unidade de rede: o número mediria a rede, não o disco."
    if tipo == DRIVE_CDROM:
        return False, "Unidade óptica não aceita teste de escrita."
    if tipo in (DRIVE_FIXED, DRIVE_REMOVABLE):
        return True, ""
    return False, "Tipo de unidade não suportado para o teste."


def alinhar(valor: int, setor: int) -> int:
    """Arredonda para baixo ate' um multiplo do setor.

    Sem alinhamento o Windows recusa toda operacao em arquivo sem buffer, e a
    recusa vem como ERROR_INVALID_PARAMETER, que nao explica nada.
    """
    setor = max(1, setor)
    return (valor // setor) * setor


def taxa(total_bytes: int, segundos: float) -> float | None:
    if total_bytes <= 0 or segundos <= 0:
        return None
    return total_bytes / segundos


class _BufferAlinhado:
    """Bloco de memoria com endereco multiplo do setor.

    FILE_FLAG_NO_BUFFERING exige que ate' o endereco do buffer seja alinhado, e
    o alocador do Python nao promete nada disso. A saida e' pedir um pedaco maior
    e trabalhar a partir do primeiro endereco alinhado dentro dele.
    """

    def __init__(self, tamanho: int, alinhamento: int) -> None:
        self._bruto = ctypes.create_string_buffer(tamanho + alinhamento)
        base = ctypes.addressof(self._bruto)
        self.endereco = (base + alinhamento - 1) & ~(alinhamento - 1)
        self.tamanho = tamanho

    def preencher(self, dados: bytes) -> None:
        ctypes.memmove(self.endereco, dados, min(len(dados), self.tamanho))

    @property
    def ponteiro(self):
        return ctypes.c_void_p(self.endereco)


def setor_do_volume(raiz: str) -> int:
    """Bytes por setor do volume; 4096 e' o palpite seguro se a API nao responder."""
    setores = wintypes.DWORD()
    bytes_setor = wintypes.DWORD()
    livres = wintypes.DWORD()
    total = wintypes.DWORD()
    ok = _kernel32.GetDiskFreeSpaceW(raiz, ctypes.byref(setores), ctypes.byref(bytes_setor),
                                     ctypes.byref(livres), ctypes.byref(total))
    if not ok or not bytes_setor.value:
        return 4096
    return max(512, int(bytes_setor.value))


def _pasta_base(mount: str) -> Path:
    """Onde criar a pasta temporaria, sempre dentro da unidade testada.

    Se a unidade for a mesma do TEMP do sistema, usa o TEMP, que ja' e' area
    descartavel e nao suja a raiz. Nas outras, a raiz da unidade e' o unico lugar
    que se pode garantir que existe e e' gravavel.
    """
    temp = Path(tempfile.gettempdir())
    try:
        if temp.drive.upper() == Path(mount).drive.upper() and temp.is_dir():
            return temp
    except (OSError, ValueError):
        pass
    return Path(mount)


def limpar_sobras(mount: str) -> int:
    """Remove pastas de teste esquecidas por uma execucao anterior.

    So' mexe no que tem o nosso prefixo e ja' passou de uma hora: se outra
    instancia estiver testando agora, a pasta dela e' recente e fica intacta.
    """
    base = _pasta_base(mount)
    removidas = 0
    try:
        candidatas = list(base.glob(PREFIXO + "*"))
    except OSError:
        return 0
    agora = time.time()
    for pasta in candidatas:
        try:
            if not pasta.is_dir() or (agora - pasta.stat().st_mtime) < IDADE_SOBRA_S:
                continue
            shutil.rmtree(pasta, ignore_errors=True)
            removidas += 1
        except OSError:
            continue
    return removidas


class DiskBench:
    """Roda o teste numa thread propria e publica o estado para a UI ler.

    A UI nunca chama nada bloqueante: pergunta `estado()` num timer. Cancelar e'
    so' levantar um Event: cada laco checa entre blocos, entao a parada e'
    imediata e ainda passa pelo `finally` que apaga o arquivo.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._fase = ""
        self._progresso = 0.0
        self._unidade = ""
        self._resultado: Resultado | None = None
        self._erro = ""
        self._handle: int | None = None
        self._roteiro: list[str] = list(FASES)
        """Fases desta corrida, na ordem. E' o denominador da barra de progresso:
        com duas fases marcadas, cada uma vale metade da barra."""
        self._validos = 0
        """Ate' onde o arquivo tem dado gravado nesta corrida.

        Ler ou sortear posicao alem disso mediria o fim do arquivo (zero byte de
        volta) ou faria o NTFS zerar o buraco no meio da medida.
        """
        _registrar(self)

    @property
    def ativo(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def estado(self) -> dict:
        with self._lock:
            return {"ativo": self.ativo, "unidade": self._unidade, "fase": self._fase,
                    "progresso": self._progresso, "resultado": self._resultado,
                    "erro": self._erro}

    def iniciar(self, mount: str, opcoes: Opcoes | None = None) -> tuple[bool, str]:
        """Valida tudo o que da' para validar antes de escrever o primeiro byte.

        A validacao de espaco usa o tamanho destas opcoes, e nao um padrao fixo:
        o usuario que escolhe 4 GiB precisa ter 4 GiB mais a folga, senao o teste
        e' recusado aqui e nenhum byte chega ao disco.
        """
        if self.ativo:
            return False, "Já existe um teste em andamento."
        opcoes = (opcoes or Opcoes()).normalizar()
        ok, erro = self._validar(mount, opcoes.tamanho)
        if not ok:
            return False, erro
        with self._lock:
            self._parar = threading.Event()
            self._fase = FASE_PREPARO
            self._progresso = 0.0
            self._unidade = mount
            self._resultado = None
            self._erro = ""
            self._validos = 0
            self._roteiro = [FASE_PREPARO] + [ROTULOS_FASES[c] for c in opcoes.fases]
        self._thread = threading.Thread(target=self._rodar, args=(mount, opcoes),
                                        name="diskbench", daemon=True)
        self._thread.start()
        return True, ""

    def cancelar(self, esperar: float = 3.0) -> None:
        """Pede parada e, se for para esperar, garante que nada ficou aberto.

        Quem fecha o handle e' o proprio worker, no `finally`. Fechar daqui no
        meio de um ReadFile em andamento seria pedir corrida de handle; so' se
        faz isso como ultimo recurso, quando a thread ignorou o pedido de parada.
        """
        self._parar.set()
        t = self._thread
        if esperar <= 0 or t is None:
            return
        if t.is_alive():
            t.join(timeout=esperar)
        if t.is_alive():
            _log.warning("thread do benchmark nao parou; fechando o arquivo a força")
            self._fechar_handle()

    def _validar(self, mount: str, tamanho: int) -> tuple[bool, str]:
        if not mount:
            return False, "Nenhuma unidade escolhida."
        ok, erro = tipo_aceito(int(_kernel32.GetDriveTypeW(mount)))
        if not ok:
            return False, erro
        try:
            uso = psutil.disk_usage(mount)
        except OSError:
            return False, "Não foi possível ler o espaço livre da unidade."
        return folga_suficiente(uso.free, uso.total, tamanho)

    def _publicar(self, fase: str, progresso: float) -> None:
        """Guarda a fase e converte o avanco dela em avanco do teste inteiro.

        Quem chama passa a fracao da propria fase, que e' o que cada laco sabe.
        Publicar isso cru fazia a barra voltar ao comeco a cada troca (64%, 24%,
        14%, 5%), e barra andando para tras se le' como travamento.

        O denominador e' o roteiro desta corrida: com uma fase so' marcada, a
        barra tem de chegar ao fim ao terminar essa fase, e nao em 20%.
        """
        roteiro = self._roteiro or list(FASES)
        try:
            posicao = roteiro.index(fase)
        except ValueError:
            posicao = 0
        fracao = max(0.0, min(1.0, progresso))
        total = (posicao + fracao) / len(roteiro)
        with self._lock:
            self._fase = fase
            # Nunca deixa recuar. Cada fase repete passadas ate' fechar o tempo
            # minimo de medicao, e a fracao da passada volta a zero a cada
            # repeticao: a barra ficava indo e voltando dentro da mesma fase.
            self._progresso = max(self._progresso, total)

    def _rodar(self, mount: str, opcoes: Opcoes) -> None:
        pasta: str | None = None
        caminho: Path | None = None
        comeco = time.monotonic()
        try:
            limpar_sobras(mount)
            setor = setor_do_volume(mount)
            tamanho = max(alinhar(opcoes.tamanho, max(setor, BLOCO_SEQ)), BLOCO_SEQ)
            opcoes = replace(opcoes, tamanho=tamanho)
            pasta = tempfile.mkdtemp(prefix=PREFIXO, dir=str(_pasta_base(mount)))
            caminho = Path(pasta) / "teste.tmp"
            resultado = self._medir(caminho, mount, opcoes, setor)
            # Cancelar no meio ainda deixa medida boa das fases que terminaram; o
            # que nao pode e' entregar isso com cara de teste completo.
            cancelado = self._parar.is_set()
            with self._lock:
                self._resultado = replace(resultado, cancelado=cancelado,
                                          segundos=time.monotonic() - comeco)
                self._fase = "cancelado" if cancelado else "concluído"
                self._progresso = 0.0 if cancelado else 1.0
        except BenchError as e:
            with self._lock:
                self._erro = str(e)
                self._fase = ""
        except Exception as e:                       # noqa: BLE001
            _log.exception("benchmark de disco falhou")
            with self._lock:
                self._erro = f"O teste falhou: {type(e).__name__}."
                self._fase = ""
        finally:
            self._fechar_handle()
            _apagar(caminho, pasta)

    def _abrir(self, caminho: Path) -> bool:
        """Abre o arquivo de teste. Devolve se o cache do sistema foi evitado.

        CREATE_NEW garante que nunca se escreve por cima de arquivo existente;
        DELETE_ON_CLOSE faz o Windows apagar o arquivo mesmo se o processo cair.
        """
        base = FILE_ATTRIBUTE_NORMAL | FILE_FLAG_DELETE_ON_CLOSE
        sem_cache = base | FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH
        for flags, evitado in ((sem_cache, True), (base, False)):
            handle = _kernel32.CreateFileW(str(caminho), GENERIC_READ | GENERIC_WRITE,
                                           0, None, CREATE_NEW, flags, None)
            if handle and handle != INVALID_HANDLE_VALUE:
                self._handle = handle
                return evitado
            erro = ctypes.get_last_error()
            _log.debug("CreateFileW falhou (flags=%#x): %s", flags, erro)
        raise BenchError("Não foi possível criar o arquivo de teste na unidade.")

    def _fechar_handle(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            _kernel32.CloseHandle(wintypes.HANDLE(handle))

    def _medir(self, caminho: Path, mount: str, opcoes: Opcoes, setor: int) -> Resultado:
        evitado = self._abrir(caminho)
        alinhamento = max(setor, BLOCO_ALEA)
        buf_seq = _BufferAlinhado(BLOCO_SEQ, alinhamento)
        buf_seq.preencher(os.urandom(BLOCO_SEQ))
        buf_alea = _BufferAlinhado(BLOCO_ALEA, alinhamento)
        buf_alea.preencher(os.urandom(BLOCO_ALEA))

        tamanho = opcoes.tamanho
        fases = opcoes.fases
        minimo, maximo = opcoes.segundos_fase, opcoes.tempo_maximo
        medidas: dict[str, float | None] = {}
        iops: dict[str, float | None] = {}

        # Fora do cronometro: so' existe para as fases seguintes terem o que ler.
        if opcoes.precisa_preparar:
            self._passada(buf_seq, tamanho, escrever=True, fase=FASE_PREPARO,
                          comeco=time.monotonic(), limite=None)
            self._flush()

        if "wseq" in fases:
            medidas["wseq"] = self._sequencial(buf_seq, tamanho, escrever=True,
                                               fase=ROTULOS_FASES["wseq"],
                                               tempo_minimo=minimo, tempo_maximo=maximo)
            self._flush()
        if "rseq" in fases:
            medidas["rseq"] = self._sequencial(buf_seq, self._extensao(tamanho),
                                               escrever=False,
                                               fase=ROTULOS_FASES["rseq"],
                                               tempo_minimo=minimo, tempo_maximo=maximo)
        for chave, escrever in (("ralea", False), ("walea", True)):
            if chave not in fases:
                continue
            medidas[chave], iops[chave] = self._aleatorio(
                buf_alea, self._extensao(tamanho), escrever=escrever,
                fase=ROTULOS_FASES[chave], segundos=minimo)
        self._flush()
        return Resultado(unidade=mount, escrita_seq=medidas.get("wseq"),
                         leitura_seq=medidas.get("rseq"),
                         leitura_alea=medidas.get("ralea"),
                         escrita_alea=medidas.get("walea"),
                         iops_leitura=iops.get("ralea"), iops_escrita=iops.get("walea"),
                         bytes_arquivo=tamanho, cache_evitado=evitado, fases=fases,
                         segundos_fase=minimo, profundidade=opcoes.profundidade)

    def _extensao(self, tamanho: int) -> int:
        """Ate' onde as fases de leitura podem ir sem sair do dado gravado.

        Numa unidade lenta com arquivo grande, o teto de tempo pode cortar a
        escrita no meio; ler alem disso devolveria zero byte e o resto do arquivo
        entraria na conta como se tivesse sido lido instantaneamente.
        """
        return max(0, min(tamanho, self._validos))

    def _flush(self) -> None:
        if self._handle:
            _kernel32.FlushFileBuffers(wintypes.HANDLE(self._handle))

    def _posicionar(self, offset: int) -> None:
        novo = ctypes.c_longlong(0)
        if not _kernel32.SetFilePointerEx(wintypes.HANDLE(self._handle),
                                          ctypes.c_longlong(offset),
                                          ctypes.byref(novo), FILE_BEGIN):
            raise BenchError("O disco recusou o posicionamento no arquivo de teste.")

    def _bloco(self, buffer: _BufferAlinhado, quantos: int, escrever: bool) -> int:
        feitos = wintypes.DWORD(0)
        fn = _kernel32.WriteFile if escrever else _kernel32.ReadFile
        if not fn(wintypes.HANDLE(self._handle), buffer.ponteiro, quantos,
                  ctypes.byref(feitos), None):
            codigo = ctypes.get_last_error()
            raise BenchError("O disco recusou a "
                             f"{'escrita' if escrever else 'leitura'} do teste "
                             f"(erro {codigo}).")
        return int(feitos.value)

    def _passada(self, buffer: _BufferAlinhado, tamanho: int, escrever: bool,
                 fase: str, comeco: float, limite: float | None) -> int:
        """Uma varredura do arquivo, do inicio ao fim. Devolve os bytes movidos.

        `limite` e' o teto de tempo do conjunto (nao desta passada). A preparacao
        chama com `None`: ela nao esta' medindo nada, e parar no meio deixaria o
        arquivo pela metade justamente para quem so' quer medir leitura.
        """
        self._posicionar(0)
        feito_total = 0
        while feito_total < tamanho:
            if self._parar.is_set():
                break
            pedaco = min(buffer.tamanho, tamanho - feito_total)
            feito = self._bloco(buffer, pedaco, escrever)
            if feito <= 0:
                break
            feito_total += feito
            if escrever:
                self._validos = max(self._validos, feito_total)
            self._publicar(fase, feito_total / tamanho if tamanho else 1.0)
            if limite is not None and (time.monotonic() - comeco) >= limite:
                break
        return feito_total

    def _sequencial(self, buffer: _BufferAlinhado, tamanho: int, escrever: bool,
                    fase: str, tempo_minimo: float | None = None,
                    tempo_maximo: float | None = None) -> float | None:
        """Passa o arquivo inteiro do inicio ao fim, quantas vezes for preciso.

        Uma passada so' dura poucos decimos de segundo num NVMe rapido, e nessa
        escala o relogio e o proprio agendador dominam a medida. Repetir ate' um
        tempo minimo entrega um numero estavel sem gastar mais espaco em disco.
        """
        minimo = TEMPO_MINIMO_FASE if tempo_minimo is None else tempo_minimo
        maximo = TEMPO_MAXIMO_FASE if tempo_maximo is None else tempo_maximo
        total = 0
        comeco = time.monotonic()
        passadas = 0
        while True:
            total += self._passada(buffer, tamanho, escrever, fase, comeco, maximo)
            passadas += 1
            decorrido = time.monotonic() - comeco
            if (self._parar.is_set() or decorrido >= minimo or decorrido >= maximo
                    or passadas >= 16):
                break
        return taxa(total, time.monotonic() - comeco)

    def _aleatorio(self, buffer: _BufferAlinhado, tamanho: int, escrever: bool,
                   fase: str, segundos: float | None = None
                   ) -> tuple[float | None, float | None]:
        """4 KiB em posicoes sorteadas, fila 1: mede latencia, nao vazao de fita.

        Fila 1 nao e' escolha de conveniencia: com ReadFile/WriteFile sincronos
        nao existe outra. Ver PROFUNDIDADES.
        """
        duracao = TEMPO_ALEATORIO if segundos is None else max(0.2, segundos)
        maximo = max(0, (tamanho - BLOCO_ALEA) // BLOCO_ALEA)
        if maximo <= 0:
            return None, None
        sorteio = random.Random(20240820)
        operacoes = 0
        comeco = time.monotonic()
        while True:
            if self._parar.is_set():
                break
            decorrido = time.monotonic() - comeco
            if decorrido >= duracao:
                break
            for _ in range(64):
                self._posicionar(sorteio.randrange(maximo) * BLOCO_ALEA)
                self._bloco(buffer, BLOCO_ALEA, escrever)
                operacoes += 1
            self._publicar(fase, min(1.0, decorrido / duracao))
        decorrido = time.monotonic() - comeco
        if operacoes <= 0 or decorrido <= 0:
            return None, None
        return taxa(operacoes * BLOCO_ALEA, decorrido), operacoes / decorrido


def _apagar(caminho: Path | None, pasta: str | None) -> None:
    """Ultima linha de defesa: o DELETE_ON_CLOSE ja' deve ter apagado o arquivo."""
    if caminho is not None:
        try:
            caminho.unlink(missing_ok=True)
        except OSError as e:
            _log.warning("nao consegui apagar %s: %s", caminho, e)
    if pasta:
        try:
            os.rmdir(pasta)
        except OSError:
            shutil.rmtree(pasta, ignore_errors=True)


_ativos: weakref.WeakSet = weakref.WeakSet()
_ativos_lock = threading.Lock()


def _registrar(bench: DiskBench) -> None:
    """Registro fraco: acompanhar o motor nao pode ser motivo para mante-lo vivo."""
    with _ativos_lock:
        _ativos.add(bench)


def encerrar_tudo() -> None:
    """Cancela qualquer teste em andamento; chamado ao fechar o app.

    Sem isso a thread continuaria escrevendo enquanto o interpretador desmonta, e
    o arquivo de 1 GiB ficaria na unidade ate' alguem notar.
    """
    with _ativos_lock:
        pendentes = list(_ativos)
    for bench in pendentes:
        try:
            bench.cancelar(esperar=2.0)
        except Exception:                            # noqa: BLE001
            pass


atexit.register(encerrar_tudo)
