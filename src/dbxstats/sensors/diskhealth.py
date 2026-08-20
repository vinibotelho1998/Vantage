"""Saude das unidades: vida restante, escrita acumulada, horas ligado e erros.

Duas fontes, nessa ordem de preferencia:

1. LibreHardwareMonitor. Ja' esta' aberto para os outros sensores e le' o SMART
   (ou o log de saude NVMe) direto do controlador, entao sai de graca no mesmo
   ciclo de coleta. E' de la' que vem vida restante, total escrito e temperatura.
2. Storage Spaces (`Get-PhysicalDisk` + `Get-StorageReliabilityCounter`). Cobre o
   que o LHM nao expoe — horas ligado, contadores de erro, temperatura maxima — e
   e' quem da' nome, serial, barramento e as letras de cada disco fisico.

A regra que vale para as duas: dado que a maquina nao entrega simplesmente nao
aparece. Zero e' leitura legitima num contador de erro e seria mentira em vida
restante; preencher buraco com 0 transformaria "nao sei" em "esta' zerado", que
e' exatamente o tipo de numero que faz alguem trocar um disco saudavel.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time

from .. import log

_log = log.get("diskhealth")

INTERVALO_S = 60.0
"""Vida util, horas ligado e contador de erro mudam em escala de dias.

Consultar o CIM custa mais de um segundo e nao pode entrar no ciclo do coletor;
uma vez por minuto ja' e' mais frequente do que o dado muda.
"""

_TIMEOUT_S = 25.0

# Get-StorageReliabilityCounter abre o disco fisico; sem elevacao o WMI recusa
# com "acesso a um recurso CIM nao estava disponivel". Como o app inteiro pede
# elevacao, isso so' aparece se alguem rodar o fonte sem ser admin.
_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$letras = @{}
foreach ($p in Get-Partition) {
  if ($p.DriveLetter) {
    $k = [string]$p.DiskNumber
    if (-not $letras.ContainsKey($k)) { $letras[$k] = @() }
    $letras[$k] += ([string]$p.DriveLetter + ':')
  }
}
$saida = @()
foreach ($d in Get-PhysicalDisk) {
  $c = $null
  try { $c = $d | Get-StorageReliabilityCounter -ErrorAction Stop } catch { $c = $null }
  $saida += [pscustomobject]@{
    id = "$($d.DeviceId)"; nome = "$($d.FriendlyName)"; serial = "$($d.SerialNumber)"
    barramento = "$($d.BusType)"; midia = "$($d.MediaType)"; tamanho = $d.Size
    saude = "$($d.HealthStatus)"; letras = @($letras["$($d.DeviceId)"])
    temp = $c.Temperature; temp_max = $c.TemperatureMax; desgaste = $c.Wear
    horas = $c.PowerOnHours; erros_leitura = $c.ReadErrorsUncorrected
    erros_escrita = $c.WriteErrorsUncorrected; ciclos = $c.StartStopCycleCount
  }
}
ConvertTo-Json -InputObject @($saida) -Depth 3 -Compress
"""


# ── LibreHardwareMonitor ─────────────────────────────────────────────────────
def _limpo(valor) -> float | None:
    """Descarta o que nao da' para tratar como leitura."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return None if f != f else f       # NaN nao e' leitura


def from_lhm_tree(nodes) -> list[dict]:
    """Extrai a saude de cada disco da arvore de sensores do LHM.

    Os nomes de sensor mudam entre versoes do LHM e entre tipos de disco (NVMe
    publica "Data Written" e "Percentage Used"; SSD SATA publica "Total Host
    Writes" e "Remaining Life"; HDD nao publica quase nada). Por isso o casamento
    e' por palavra-chave no nome, e nao por igualdade: o que existir entra, o
    resto fica de fora.
    """
    por_disco: dict[str, dict] = {}
    for node in nodes:
        if getattr(node, "hw_type", "") != "Storage":
            continue
        valor = _limpo(getattr(node, "value", None))
        if valor is None:
            continue
        entrada = por_disco.setdefault(node.hardware, {"name": node.hardware})
        _aplicar_sensor(entrada, str(node.kind), str(node.name).lower(), valor)

    saida = []
    for entrada in por_disco.values():
        # "Percentage Used" e' o inverso de vida restante. Quando o disco so'
        # publica o desgaste, a conversao e' exata — nao e' estimativa.
        if "life" not in entrada and "used_pct" in entrada:
            entrada["life"] = round(max(0.0, 100.0 - entrada.pop("used_pct")), 1)
        entrada.pop("used_pct", None)
        saida.append(entrada)
    return saida


def _aplicar_sensor(entrada: dict, kind: str, nome: str, valor: float) -> None:
    """Traduz um sensor de Storage do LHM para o campo correspondente."""
    if kind == "Temperature":
        # Varios NVMe publicam sensor por chip alem do composto; o composto e' o
        # numero que representa o disco, os outros so' entram se nao houver ele.
        if "composite" in nome or nome == "temperature":
            entrada["temp"] = round(valor, 1)
        elif "temp" not in entrada and valor > 0:
            entrada["temp"] = round(valor, 1)
    elif kind == "Level":
        if "threshold" in nome:
            return                      # limite de alarme, nao e' leitura de estado
        if "spare" in nome:
            entrada["spare"] = round(valor, 1)
        elif "percentage used" in nome or "wear" in nome:
            entrada["used_pct"] = valor
        elif "life" in nome:
            entrada["life"] = round(valor, 1)
    elif kind == "Data":
        # SensorType.Data no LHM vem em GB.
        if "written" in nome or "host writes" in nome:
            entrada["written_gb"] = round(valor, 1)
        elif "read" in nome or "host reads" in nome:
            entrada["read_gb"] = round(valor, 1)
    elif kind == "Load":
        if "used space" in nome:
            entrada["used_pct_disco"] = round(valor, 1)
    elif "hours" in nome:
        entrada["hours"] = valor
    elif "power on count" in nome or "power cycle" in nome:
        entrada["power_cycles"] = valor
    elif "unsafe shutdown" in nome:
        entrada["unsafe_shutdowns"] = valor
    elif "error" in nome:
        entrada["errors"] = valor


# ── Storage Spaces / CIM ─────────────────────────────────────────────────────
def _numero(bruto) -> float | None:
    if bruto is None or isinstance(bruto, bool):
        return None
    try:
        return float(bruto)
    except (TypeError, ValueError):
        return None


def parse_physical(texto: str) -> list[dict]:
    """Le' o JSON do PowerShell. Campo nulo do CIM nao vira campo aqui."""
    bruto = (texto or "").strip()
    if not bruto:
        return []
    try:
        dados = json.loads(bruto)
    except ValueError:
        return []
    if isinstance(dados, dict):
        # ConvertTo-Json com um item so' devolve objeto, nao lista.
        dados = [dados]
    if not isinstance(dados, list):
        # Pipeline vazio vira o literal 'null'; nao ha' disco para listar.
        return []
    saida = []
    for item in dados:
        if not isinstance(item, dict):
            continue
        disco: dict = {"id": str(item.get("id", "")), "name": (item.get("nome") or "").strip()}
        for chave_json, chave in (("serial", "serial"), ("barramento", "bus"),
                                  ("midia", "media"), ("saude", "health")):
            texto_valor = (item.get(chave_json) or "").strip()
            if texto_valor:
                disco[chave] = texto_valor
        letras = item.get("letras")
        if isinstance(letras, list):
            disco["letters"] = [str(x) for x in letras if x]
        elif letras:
            disco["letters"] = [str(letras)]
        for chave_json, chave in (("tamanho", "size"), ("temp", "temp"),
                                  ("temp_max", "temp_max"), ("horas", "hours"),
                                  ("erros_leitura", "errors_read"),
                                  ("erros_escrita", "errors_write"),
                                  ("ciclos", "power_cycles")):
            valor = _numero(item.get(chave_json))
            if valor is not None:
                disco[chave] = valor
        desgaste = _numero(item.get("desgaste"))
        if desgaste is not None:
            # Wear do Storage Spaces e' desgaste em porcentagem; vira vida restante.
            disco["life"] = round(max(0.0, 100.0 - desgaste), 1)
        saida.append(disco)
    return saida


def _chave(nome: str) -> str:
    """Normaliza modelo para comparar: 'SSD M.2  NVME 2TB' == 'ssdm2nvme2tb'."""
    return re.sub(r"[^a-z0-9]", "", (nome or "").lower())


def combinar(fisicos: list[dict], do_lhm: list[dict]) -> list[dict]:
    """Funde as duas fontes num disco fisico so'.

    A lista do Windows manda, porque e' ela que sabe quantos discos existem e
    quais letras moram em cada um. O LHM entra por cima com o que so' ele tem
    (vida restante, total escrito, temperatura do controlador).

    O casamento e' pelo modelo normalizado. Quando o nome nao bate — acontece com
    adaptador USB e com RAID, onde o LHM ve' um nome e o Windows outro — cai para
    a ordem de enumeracao, que e' a mesma nas duas APIs na esmagadora maioria das
    maquinas. Um disco do LHM que nao casa com nenhum entra sozinho: e' melhor
    mostrar um disco a mais do que esconder a vida util de um deles.
    """
    if not fisicos:
        return [dict(e) for e in do_lhm]

    sobrando = list(do_lhm)
    saida = [dict(f) for f in fisicos]
    sem_par: list[int] = []
    for indice, entrada in enumerate(saida):
        alvo = _chave(entrada.get("name", ""))
        casado = None
        for cand in sobrando:
            chave_cand = _chave(cand.get("name", ""))
            if alvo and chave_cand and (alvo == chave_cand
                                        or alvo in chave_cand or chave_cand in alvo):
                casado = cand
                break
        if casado is None:
            sem_par.append(indice)
            continue
        sobrando.remove(casado)
        _fundir(entrada, casado)

    # Sobrou exatamente um candidato para cada disco sem par: a ordem de
    # enumeracao resolve. Se as contas nao fecham, ninguem casa por chute.
    if sem_par and len(sem_par) == len(sobrando):
        for indice, cand in zip(sem_par, sobrando, strict=True):
            _fundir(saida[indice], cand)
        sobrando = []

    saida.extend(dict(e) for e in sobrando)
    return saida


def _fundir(destino: dict, origem: dict) -> None:
    """Copia o que o destino ainda nao tem. O nome do Windows tem preferencia."""
    for chave, valor in origem.items():
        if chave != "name":
            destino.setdefault(chave, valor)


def tem_dado(disco: dict) -> bool:
    """Ha' alguma leitura de saude de verdade, ou so' o nome do disco?"""
    return any(chave in disco for chave in
               ("life", "written_gb", "read_gb", "hours", "temp", "temp_max",
                "errors_read", "errors_write", "errors", "spare", "power_cycles",
                "unsafe_shutdowns", "health"))


class ReliabilityProbe:
    """Consulta o Storage Spaces numa thread propria, com cache por tempo.

    Fica fora do coletor de proposito: e' um subprocesso de mais de um segundo e
    o ciclo de sensores nao pode esperar por ele. A UI pergunta `read()` quando
    quiser; se o cache venceu, dispara a atualizacao e devolve o que ja' tinha.
    """

    def __init__(self, intervalo: float = INTERVALO_S) -> None:
        self._intervalo = intervalo
        self._lock = threading.Lock()
        self._dados: list[dict] = []
        self._erro = ""
        self._quando = 0.0
        self._ocupado = False

    @property
    def erro(self) -> str:
        with self._lock:
            return self._erro

    def read(self) -> list[dict]:
        """Devolve o cache e agenda a proxima leitura se ela ja' venceu."""
        with self._lock:
            vencido = (time.monotonic() - self._quando) > self._intervalo
            dados = list(self._dados)
            ocupado = self._ocupado
            if vencido and not ocupado:
                self._ocupado = True
        if vencido and not ocupado:
            threading.Thread(target=self._consultar, name="diskhealth",
                             daemon=True).start()
        return dados

    def _consultar(self) -> None:
        dados: list[dict] = []
        erro = ""
        try:
            saida = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
                capture_output=True, text=True, timeout=_TIMEOUT_S,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            dados = parse_physical(saida.stdout)
            if not dados:
                erro = _explicar(saida.stderr)
        except subprocess.TimeoutExpired:
            erro = "A consulta de saúde dos discos demorou demais e foi cancelada."
        except (OSError, subprocess.SubprocessError) as e:
            _log.debug("Get-PhysicalDisk falhou: %s", e)
            erro = "Não foi possível consultar a saúde dos discos nesta máquina."
        with self._lock:
            self._dados = dados
            self._erro = erro
            self._quando = time.monotonic()
            self._ocupado = False


def _explicar(stderr: str) -> str:
    """Transforma a reclamacao do PowerShell no que o usuario pode fazer."""
    texto = (stderr or "").lower()
    if "cim" in texto or "acesso" in texto or "access" in texto or "denied" in texto:
        return ("Sem permissão para ler a saúde dos discos. "
                "Abra o DBX Stats como administrador.")
    if "not recognized" in texto or "não é reconhecido" in texto:
        return "Este Windows não tem os comandos de armazenamento (Get-PhysicalDisk)."
    return "Nenhum disco físico respondeu à consulta de saúde."
