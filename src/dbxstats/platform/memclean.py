"""Liberar memoria no Windows: working set dos processos e lista de standby.

O que a limpeza faz de verdade
------------------------------
`EmptyWorkingSet` pede ao gerenciador de memoria que remova do working set de um
processo as paginas que ele tem residentes. Elas nao somem: as limpas vao para a
lista de standby (continuam na RAM, mas disponiveis) e as sujas vao para a lista
de modificadas e depois para o arquivo de paginacao. O processo nao morre nem
perde nada — apenas volta a puxar do disco o que precisar de novo.

`NtSetSystemInformation(SystemMemoryListInformation, MemoryPurgeStandbyList)`
descarta a lista de standby inteira. Standby e' a copia em RAM de paginas ja'
lidas do disco que o Windows guarda de graca — e' cache, nao e' memoria ocupada.

O que a limpeza NAO faz
-----------------------
Nao acelera nada por si so'. O contador de "memoria disponivel" sobe, mas o que
se ganha e' espaco vazio, nao velocidade: a lista de standby nunca esteve
atrapalhando ninguem, porque o Windows ja' a entrega no instante em que qualquer
programa pede RAM. Logo depois da limpeza o sistema tende a ficar MAIS lento por
alguns segundos ou minutos, ja' que tudo o que foi descartado precisa ser lido do
disco outra vez — e o jogo que estava aberto e' justamente quem mais sofre.

Serve para: medir consumo a partir de um estado limpo antes de um teste, e
destravar o caso especifico de um aplicativo que segurou working set enorme sem
estar usando. Fora disso, e' um botao de cosmetica.

Este modulo foi escrito a partir da documentacao publica das APIs do Win32
(EmptyWorkingSet, SetProcessWorkingSetSizeEx, AdjustTokenPrivileges e
NtSetSystemInformation). Nada aqui foi copiado de outro projeto — a licenca do
DBX Stats e' MIT e precisa continuar sendo.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field

import psutil

from .. import log

_log = log.get("memclean")

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

def _prototipos() -> None:
    """Sem prototipo, ctypes assume int de 32 bits e o handle de 64 e' truncado.

    O sintoma disso e' pior do que um erro: a chamada "funciona" e mexe em outro
    objeto, ou falha com codigo sem sentido. Vale para todo handle daqui.
    """
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.SetProcessWorkingSetSizeEx.restype = wintypes.BOOL
    _kernel32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t,
                                                     ctypes.c_size_t, wintypes.DWORD]
    _psapi.EmptyWorkingSet.restype = wintypes.BOOL
    _psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    _advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
    _ntdll.NtSetSystemInformation.restype = ctypes.c_long
    _ntdll.NtSetSystemInformation.argtypes = [ctypes.c_int, wintypes.LPVOID,
                                              ctypes.c_ulong]


PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100

TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002
ERROR_NOT_ALL_ASSIGNED = 1300

SE_PROFILE_SINGLE_PROCESS = "SeProfileSingleProcessPrivilege"

SYSTEM_MEMORY_LIST_INFORMATION = 0x50
"""SYSTEM_INFORMATION_CLASS 80 — a classe que aceita comandos de lista de memoria."""

MEMORY_PURGE_STANDBY_LIST = 4
"""SYSTEM_MEMORY_LIST_COMMAND: 2 = esvaziar working sets, 4 = descartar standby."""

STATUS_PRIVILEGE_NOT_HELD = 0xC0000061
STATUS_ACCESS_DENIED = 0xC0000022

# Processos que nao se toca. Nao e' superstição: o gerenciador de sessao e o
# subsistema de tempo de execucao segurando pagina residente e' o que mantem a
# maquina em pe', e o DWM perde o quadro na hora (a tela pisca) se o working set
# dele for zerado. Nenhum deles guarda memoria a toa — nao ha' nada a ganhar ali.
CRITICOS = frozenset({
    "system", "system idle process", "registry", "memory compression",
    "secure system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "lsaiso.exe", "fontdrvhost.exe", "dwm.exe",
})

PIDS_CRITICOS = frozenset({0, 4})

_prototipos()


@dataclass(frozen=True)
class Resultado:
    limpos: int = 0
    ignorados: int = 0
    falhas: int = 0
    standby: bool = False
    erro_standby: str = ""
    antes_gb: float | None = None
    depois_gb: float | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def liberado_gb(self) -> float | None:
        if self.antes_gb is None or self.depois_gb is None:
            return None
        return self.depois_gb - self.antes_gb


def e_critico(pid: int, nome: str) -> bool:
    """Decide se o processo fica de fora da limpeza."""
    if pid in PIDS_CRITICOS:
        return True
    return (nome or "").strip().lower() in CRITICOS


def resumo(r: Resultado) -> str:
    """Frase unica para a UI — diz o que aconteceu, sem prometer desempenho."""
    partes = [f"{r.limpos} processos liberados"]
    if r.falhas:
        partes.append(f"{r.falhas} recusaram")
    if r.ignorados:
        partes.append(f"{r.ignorados} do sistema preservados")
    partes.append("standby descartada" if r.standby else "standby mantida")
    ganho = r.liberado_gb
    if ganho is not None:
        sinal = "+" if ganho >= 0 else ""
        partes.append(f"disponível {sinal}{ganho:.2f} GB")
    return "  ·  ".join(partes)


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", wintypes.DWORD)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD),
                ("Privileges", _LUID_AND_ATTRIBUTES * 1)]


def habilitar_privilegio(nome: str = SE_PROFILE_SINGLE_PROCESS) -> tuple[bool, str]:
    """Liga um privilegio no token do processo atual.

    Todo processo elevado recebe SeProfileSingleProcessPrivilege no token, mas
    desabilitado — ter o privilegio e usa-lo sao coisas diferentes no Windows.
    Sem esse passo o NtSetSystemInformation devolve STATUS_PRIVILEGE_NOT_HELD.
    """
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(),
                                      TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                      ctypes.byref(token)):
        return False, "Não foi possível abrir o token do processo."
    try:
        luid = _LUID()
        if not _advapi32.LookupPrivilegeValueW(None, nome, ctypes.byref(luid)):
            return False, f"O Windows não reconheceu o privilégio {nome}."
        privs = _TOKEN_PRIVILEGES()
        privs.PrivilegeCount = 1
        privs.Privileges[0].Luid = luid
        privs.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ok = _advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privs),
                                             0, None, None)
        # AdjustTokenPrivileges devolve sucesso mesmo quando nao conseguiu ligar
        # tudo; quem conta a verdade e' o GetLastError logo em seguida.
        if not ok or ctypes.get_last_error() == ERROR_NOT_ALL_ASSIGNED:
            return False, ("Este processo não tem o privilégio necessário. "
                           "Abra o DBX Stats como administrador.")
        return True, ""
    finally:
        _kernel32.CloseHandle(token)


def esvaziar_working_set(pid: int) -> bool:
    """Tira da RAM as paginas residentes de um processo.

    Precisa de PROCESS_QUERY_INFORMATION + PROCESS_SET_QUOTA. Processos
    protegidos (anti-cheat, antivirus, servicos do sistema) recusam o
    OpenProcess, e isso e' esperado — a funcao devolve False e a vida segue.
    """
    for acesso in (PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA,
                   PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA):
        handle = _kernel32.OpenProcess(acesso, False, pid)
        if not handle:
            continue
        try:
            if _psapi.EmptyWorkingSet(wintypes.HANDLE(handle)):
                return True
            # Caminho alternativo documentado: minimo e maximo em (SIZE_T)-1
            # mandam o Windows encolher o working set temporariamente a zero.
            menos_um = ctypes.c_size_t(-1)
            if _kernel32.SetProcessWorkingSetSizeEx(wintypes.HANDLE(handle),
                                                    menos_um, menos_um, 0):
                return True
        finally:
            _kernel32.CloseHandle(wintypes.HANDLE(handle))
    return False


def listar_processos() -> list[tuple[int, str]]:
    saida = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            saida.append((int(proc.info["pid"]), str(proc.info["name"] or "")))
        except (psutil.Error, TypeError, ValueError):
            continue
    return saida


def limpar_standby() -> tuple[bool, str]:
    """Descarta a lista de standby (o cache de arquivos que o Windows mantem)."""
    ok, erro = habilitar_privilegio()
    if not ok:
        return False, erro
    comando = ctypes.c_int(MEMORY_PURGE_STANDBY_LIST)
    status = _ntdll.NtSetSystemInformation(SYSTEM_MEMORY_LIST_INFORMATION,
                                           ctypes.byref(comando),
                                           ctypes.sizeof(comando))
    codigo = ctypes.c_ulong(status).value
    if codigo == 0:
        return True, ""
    if codigo == STATUS_PRIVILEGE_NOT_HELD:
        return False, ("O Windows recusou: falta o privilégio de perfil de "
                       "processo. Abra o DBX Stats como administrador.")
    if codigo == STATUS_ACCESS_DENIED:
        return False, "O Windows negou acesso à lista de standby."
    return False, f"O Windows recusou a limpeza da lista de standby (status {codigo:#x})."


def _disponivel_gb() -> float | None:
    try:
        return psutil.virtual_memory().available / 1024 ** 3
    except Exception:                                # noqa: BLE001
        return None


def limpar(processos=None, esvaziar=None, standby=None, disponivel=None) -> Resultado:
    """Roda a limpeza inteira e devolve o que realmente aconteceu.

    As quatro dependencias entram por parametro para o teste poder exercitar a
    regra (quem e' preservado, como o resultado e' montado) sem esvaziar working
    set de verdade nem mexer na memoria da maquina que roda o teste.
    """
    processos = listar_processos if processos is None else processos
    esvaziar = esvaziar_working_set if esvaziar is None else esvaziar
    standby = limpar_standby if standby is None else standby
    disponivel = _disponivel_gb if disponivel is None else disponivel

    antes = disponivel()
    limpos = ignorados = falhas = 0
    for pid, nome in processos():
        if e_critico(pid, nome):
            ignorados += 1
            continue
        try:
            if esvaziar(pid):
                limpos += 1
            else:
                falhas += 1
        except OSError:
            falhas += 1

    purgada, erro = standby()
    if not purgada and erro:
        _log.info("standby nao foi limpa: %s", erro)

    avisos = []
    if falhas:
        avisos.append(f"{falhas} processos recusaram a liberação (protegidos pelo "
                      "sistema ou por anticheat) — é esperado.")
    return Resultado(limpos=limpos, ignorados=ignorados, falhas=falhas,
                     standby=purgada, erro_standby=erro, antes_gb=antes,
                     depois_gb=disponivel(), avisos=avisos)
