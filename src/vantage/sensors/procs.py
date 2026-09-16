"""Monitor de processos: top consumidores de CPU/RAM, atualizado numa cadencia propria.

Alem de olhar, a tela tambem age: encerrar, mudar prioridade e mudar afinidade
moram aqui embaixo, longe do Qt, para poderem ser testados sem abrir janela.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

import psutil

from .. import log

_log = log.get("procs")

# Processos de sistema que poluem o ranking sem serem acionaveis pelo usuario.
_HIDE = {"system idle process", "memory compression"}


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    cpu: float
    ram_mb: float
    threads: int
    is_game: bool = False


class ProcessMonitor:
    def __init__(self, interval: float = 2.5, limit: int = 40) -> None:
        self._interval = interval
        self._limit = limit
        self._procs: list[ProcInfo] = []
        self._count = 0
        self._threads_total = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cores = psutil.cpu_count(logical=True) or 1
        self._game_pids: set[int] = set()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="procs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_game_pids(self, pids) -> None:
        with self._lock:
            self._game_pids = set(pids or ())

    def snapshot(self) -> list[ProcInfo]:
        with self._lock:
            return list(self._procs)

    def totals(self) -> tuple[int, int]:
        with self._lock:
            return self._count, self._threads_total

    def _loop(self) -> None:
        for p in psutil.process_iter(["pid"]):
            try:
                p.cpu_percent(None)
            except psutil.Error:
                continue
        while not self._stop.wait(self._interval):
            try:
                self._collect()
            except Exception:
                _log.exception("erro coletando processos")

    def _collect(self) -> None:
        with self._lock:
            games = set(self._game_pids)
        rows: list[ProcInfo] = []
        threads_total = 0
        count = 0
        for p in psutil.process_iter(["pid", "name", "memory_info", "num_threads"]):
            try:
                info = p.info
                name = info["name"] or "?"
                if name.lower() in _HIDE:
                    continue
                count += 1
                threads_total += info["num_threads"] or 0
                cpu = p.cpu_percent(None) / self._cores
                mem = info["memory_info"]
                rows.append(ProcInfo(
                    pid=info["pid"], name=name, cpu=round(cpu, 1),
                    ram_mb=round((mem.rss if mem else 0) / 1024 ** 2, 1),
                    threads=info["num_threads"] or 0, is_game=info["pid"] in games))
            except (psutil.Error, AttributeError, TypeError):
                continue
        rows.sort(key=lambda r: (-r.cpu, -r.ram_mb))
        with self._lock:
            self._procs = rows[:self._limit]
            self._count = count
            self._threads_total = threads_total


def process_name(pid: int | None) -> str:
    if not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ""


def process_started_at(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        return time.time() - psutil.Process(pid).create_time()
    except psutil.Error:
        return None


# Encerrar qualquer um destes nao fecha "um programa": apaga a sessao inteira ou
# reinicia a maquina na hora. A recusa precisa vir do app, porque ele roda
# elevado: o Windows aceitaria o pedido sem nem perguntar.
_CRITICOS = {
    "system", "registry", "secure system", "system idle process",
    "memory compression", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "dwm.exe",
}

# Morrem sem drama, mas levam junto algo que o usuario nao esta' esperando.
_AVISOS = {
    "explorer.exe": ("A barra de tarefas, o menu Iniciar e os ícones da área de "
                     "trabalho somem até o Explorer voltar; o Windows costuma "
                     "reabri-lo sozinho em alguns segundos."),
}


def bloqueio_encerrar(nome: str, pid: int = -1) -> str:
    """Motivo para recusar o encerramento; string vazia quando pode encerrar.

    O padrao e' -1, e nao 0, porque aqui 0 quer dizer alguma coisa: e' o PID do
    kernel. Com zero como padrao, quem chamasse so' com o nome recebia "PID 0 e
    4 sao o nucleo do Windows" para qualquer processo, e nada poderia ser
    encerrado.
    """
    if pid in (0, 4):
        return ("PID 0 e 4 são o núcleo do próprio Windows: não há como encerrar "
                "sem derrubar a máquina.")
    if (nome or "").strip().lower() in _CRITICOS:
        return (f"{nome} é essencial para a sessão do Windows. Encerrar apaga a "
                "interface ou reinicia o PC na hora, então o app não oferece isso.")
    return ""


def aviso_encerrar(nome: str) -> str:
    """Aviso extra para quem pode ser encerrado, mas cobra um preco visivel."""
    return _AVISOS.get((nome or "").strip().lower(), "")


@dataclass(frozen=True)
class Prioridade:
    chave: str
    rotulo: str
    valor: int
    perigosa: bool = False
    dica: str = ""


# Rotulos iguais aos do Gerenciador de Tarefas: quem ja' mexeu la' nao precisa
# traduzir nada de cabeca. Os valores sao as classes de prioridade do Win32, que
# o psutil so' expoe rodando no Windows: o numero cru como reserva mantem o
# modulo importavel (e testavel) em qualquer lugar.
PRIORIDADES: tuple[Prioridade, ...] = (
    Prioridade("realtime", "Tempo real", getattr(psutil, "REALTIME_PRIORITY_CLASS", 0x100),
               True, "à frente do próprio Windows"),
    Prioridade("high", "Alta", getattr(psutil, "HIGH_PRIORITY_CLASS", 0x80),
               False, "na frente de quase tudo"),
    Prioridade("above", "Acima do normal", getattr(psutil, "ABOVE_NORMAL_PRIORITY_CLASS", 0x8000)),
    Prioridade("normal", "Normal", getattr(psutil, "NORMAL_PRIORITY_CLASS", 0x20),
               False, "o padrão do Windows"),
    Prioridade("below", "Abaixo do normal", getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)),
    Prioridade("idle", "Baixa", getattr(psutil, "IDLE_PRIORITY_CLASS", 0x40),
               False, "só roda com CPU sobrando"),
)


def prioridade_por_chave(chave: str) -> Prioridade | None:
    return next((p for p in PRIORIDADES if p.chave == chave), None)


def rotulo_prioridade(valor) -> str:
    """Traduz o valor cru do Windows para o rotulo da tela; vazio se nao conhece."""
    if valor is None:
        return ""
    return next((p.rotulo for p in PRIORIDADES if valor == p.valor), "")


def nucleos_totais() -> int:
    return psutil.cpu_count(logical=True) or 1


def parse_nucleos(texto: str, total: int) -> list[int]:
    """Le '0-3, 8 10' e devolve indices unicos e ordenados.

    O campo de texto e' atalho de teclado para quem tem muito nucleo, entao
    aceita bagunca de separador e faixa invertida. So' recusa o que teria de
    adivinhar: numero fora da CPU vira uma selecao diferente da que a pessoa
    digitou, e uma selecao errada de afinidade e' dificil de perceber depois.
    """
    nucleos: set[int] = set()
    for parte in re.split(r"[,;\s]+", (texto or "").strip()):
        if not parte:
            continue
        pedacos = parte.split("-")
        if len(pedacos) > 2 or not all(p.strip().isdigit() for p in pedacos):
            raise ValueError(f"Não entendi “{parte}”. Use números e faixas, ex.: 0-3, 8.")
        numeros = [int(p) for p in pedacos]
        if max(numeros) >= total:
            raise ValueError(f"Esta CPU tem núcleos de 0 a {total - 1}.")
        nucleos.update(range(min(numeros), max(numeros) + 1))
    return sorted(nucleos)


def formatar_nucleos(nucleos) -> str:
    """[0,1,2,3,8] -> '0-3, 8'. Dezesseis numeros soltos ninguem le'."""
    ordenados = sorted({int(n) for n in nucleos or ()})
    if not ordenados:
        return "nenhum"
    faixas: list[str] = []
    inicio = anterior = ordenados[0]
    for n in ordenados[1:]:
        if n == anterior + 1:
            anterior = n
            continue
        faixas.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
        inicio = anterior = n
    faixas.append(str(inicio) if inicio == anterior else f"{inicio}-{anterior}")
    return ", ".join(faixas)


def _abrir(pid: int, nome: str) -> psutil.Process:
    """Abre o processo conferindo que o PID ainda e' de quem a tabela mostrava.

    O Windows reaproveita PID depressa e a linha clicada pode ser de ate' 2,5 s
    atras. Sem essa conferencia, um clique em "Finalizar" acertaria o processo
    novo que herdou o numero, e ninguem entenderia por que o programa errado
    morreu.
    """
    proc = psutil.Process(pid)
    if nome and proc.name().lower() != nome.strip().lower():
        raise psutil.NoSuchProcess(pid)
    return proc


def _falha(acao: str, nome: str, erro: Exception) -> str:
    """Traduz a excecao do psutil para uma frase que explica o que fazer."""
    if isinstance(erro, psutil.NoSuchProcess):
        return f"{nome} já não está em execução."
    if isinstance(erro, psutil.AccessDenied):
        return (f"O Windows negou permissão para {acao} {nome}. Processos "
                "protegidos do sistema recusam até para administradores.")
    return f"Não foi possível {acao} {nome}: {erro}"


def detalhes(pid: int, nome: str = "") -> dict:
    """Prioridade e afinidade atuais para preencher os dialogos.

    Le' so' na hora de abrir a janela: buscar isso no laco de coleta obrigaria a
    abrir um handle por processo a cada 2,5 s, e o monitor ficaria mais caro que
    a coisa que ele monitora. Cada leitura vai separada porque um processo pode
    deixar ler a prioridade e recusar a afinidade.
    """
    dados: dict = {"prioridade": None, "nucleos": None}
    try:
        proc = _abrir(pid, nome)
    except (psutil.Error, OSError):
        return dados
    for chave, leitura in (("prioridade", proc.nice), ("nucleos", proc.cpu_affinity)):
        try:
            dados[chave] = leitura()
        except (psutil.Error, OSError, AttributeError, NotImplementedError):
            continue
    return dados


def encerrar(pid: int, nome: str) -> tuple[bool, str]:
    """Encerra o processo. Nunca levanta: devolve (deu certo, frase para a tela)."""
    bloqueio = bloqueio_encerrar(nome, pid)
    if bloqueio:
        return False, bloqueio
    try:
        proc = _abrir(pid, nome)
        proc.terminate()
        try:
            # No Windows terminate() ja' e' TerminateProcess, mas o processo so'
            # some quando o kernel termina de fecha-lo. Esperar evita anunciar
            # "encerrado" para algo que ficou pendurado; e o kill() cobre o caso
            # do processo que esta' preso em I/O e ignora o primeiro pedido.
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except psutil.TimeoutExpired:
        return False, f"{nome} não respondeu ao pedido de encerrar."
    except (psutil.Error, OSError) as erro:
        return False, _falha("encerrar", nome, erro)
    return True, f"{nome} (PID {pid}) foi encerrado."


def mudar_prioridade(pid: int, nome: str, chave: str) -> tuple[bool, str]:
    """Muda a classe de prioridade. Vale so' ate' o processo fechar."""
    prio = prioridade_por_chave(chave)
    if prio is None:
        return False, "Prioridade desconhecida."
    try:
        _abrir(pid, nome).nice(prio.valor)
    except (psutil.Error, OSError) as erro:
        return False, _falha("mudar a prioridade de", nome, erro)
    return True, f"{nome} agora está em prioridade {prio.rotulo.lower()}."


def mudar_afinidade(pid: int, nome: str, nucleos) -> tuple[bool, str]:
    """Prende o processo aos nucleos escolhidos. Tambem vale so' ate' ele fechar."""
    escolhidos = sorted({int(n) for n in nucleos or ()})
    total = nucleos_totais()
    if not escolhidos:
        return False, "Escolha pelo menos um núcleo: sem nenhum, o processo não roda."
    if escolhidos[0] < 0 or escolhidos[-1] >= total:
        return False, f"Esta CPU tem núcleos de 0 a {total - 1}."
    try:
        _abrir(pid, nome).cpu_affinity(escolhidos)
    except (psutil.Error, OSError, AttributeError, NotImplementedError) as erro:
        return False, _falha("mudar a afinidade de", nome, erro)
    if len(escolhidos) == total:
        return True, f"{nome} voltou a usar todos os núcleos."
    return True, f"{nome} agora roda só nos núcleos {formatar_nucleos(escolhidos)}."
