"""Leitura de sensores via LibreHardwareMonitorLib (.NET / pythonnet).

Alem do dicionario curado usado pelos cards, expoe a arvore completa de sensores
(estilo HWMonitor) numa unica varredura por ciclo.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

from .. import log, paths

_log = log.get("lhm")

# Package primeiro: Tctl/Tdie e' a temperatura do encapsulamento, que e' a que o
# proprio processador usa para decidir boost e limite. CCD e' o die individual —
# util para detalhe, mas nao e' o numero que representa a peca.
_CPU_TEMP_PRIORITY = (
    "Core (Tctl/Tdie)", "Tctl/Tdie", "Tdie", "CPU Package", "Package",
    "CCD", "Core Max", "Core Average",
)

_GPU_DISCRETE_KW = ("rtx", "gtx", "rx ", " arc", "radeon pro", "quadro", "tesla", "geforce")
_GPU_INTEGRATED_KW = ("uhd graphics", "iris", "radeon(tm) graphics", "radeon graphics",
                      "hd graphics", "vega")

# Vcore de verdade x VID. No Ryzen 9800X3D o "Core #N VID" marcou 0,463 V com o
# pacote em 98 W e os oito nucleos a 5225 MHz — fisicamente impossivel — e mal se
# moveu (0,469→0,531 V) enquanto o pacote ia de 39 para 63 W. Aquilo e' o pedido
# de tensao codificado, nao a tensao entregue, e sem elevacao trava em 1,550 V.
# Publicar VID como "voltagem da CPU" e' um numero errado com cara de certo,
# entao ele sai numa chave propria e o Vcore vem do rail da placa.
_VCORE_NOMES = ("vcore", "cpu core", "cpu vcore", "core voltage", "cpu voltage")
# Faixa plausivel de Vcore em desktop atual: abaixo e' sensor morto, acima sao os
# rails de 1,8 V / 2,5 V / 3,3 V / 5 V / 12 V.
_VCORE_FAIXA = (0.40, 1.70)
# Movimento minimo para adotar um rail anonimo como Vcore. Medido nesta X870M:
# numa janela de 15 s o Vcore andou 0,060 V e todos os outros rails da faixa
# ficaram cravados em 0,000 — 0,020 V passa longe do ruido e longe do sinal.
_VCORE_MOVIMENTO = 0.02
# Ordem de confianca da tensao publicada; ver _publicar_volts.
_VOLTS_RANK = {"vcore": 3, "cpu": 2, "rail": 1}

# Ler os dois pentes DDR5 custa ~2,2 ms por ciclo (mais que a CPU inteira, que
# gasta 2,5 ms com 64 sensores) porque cada um e' uma conversa por SMBus. E' o
# sensor mais lento da maquina em todo sentido: nao mudou nem 0,01 °C em 15 s.
# Fora do ritmo do resto, ele deixa de pesar sem esconder nada.
_SPD_INTERVALO_S = 10.0

UNITS = {
    "Voltage": "V", "Current": "A", "Power": "W", "Clock": "MHz",
    "Temperature": "°C", "Load": "%", "Frequency": "Hz", "Fan": "RPM",
    "Flow": "L/h", "Control": "%", "Level": "%", "Factor": "",
    "Data": "GB", "SmallData": "MB", "Throughput": "B/s", "TimeSpan": "s",
    "Energy": "mWh", "Noise": "dBA",
}

HW_LABELS = {
    "Cpu": "Processador", "GpuNvidia": "GPU NVIDIA", "GpuAmd": "GPU AMD",
    "GpuIntel": "GPU Intel", "Memory": "Memória", "Motherboard": "Placa-mãe",
    "SuperIO": "Controlador (Super I/O)", "Storage": "Armazenamento",
    "Network": "Rede", "Cooler": "Water cooler", "Psu": "Fonte", "Battery": "Bateria",
}


@dataclass(frozen=True)
class SensorNode:
    key: str
    hardware: str
    hw_type: str
    name: str
    kind: str
    unit: str
    value: float


def _gpu_score(g: dict) -> tuple:
    name = g.get("name", "").lower()
    vram = g.get("vram_total", 0) or 0
    discrete = (g.get("type") == "GpuNvidia"
                or any(k in name for k in _GPU_DISCRETE_KW)
                or vram >= 3000)
    integrated = (any(k in name for k in _GPU_INTEGRATED_KW)
                  and not any(k in name for k in _GPU_DISCRETE_KW))
    rank = 1 if (discrete and not integrated) else 0
    return (rank, vram, g.get("usage", 0) or 0)


def _explicar(erro: Exception) -> str:
    """Traduz a falha do LHM no que o usuario precisa fazer."""
    texto = f"{type(erro).__name__}: {erro}".lower()
    if "clr" in texto and "no module" in texto:
        return ("A ponte com o .NET (pythonnet) nao carregou. "
                "Reinstale o DBX Stats para repor as dependencias.")
    if "hostfxr" in texto or "runtimeconfig" in texto or "coreclr" in texto:
        return ("O .NET Desktop Runtime nao esta instalado. "
                "Instale o .NET Desktop Runtime 8 (x64) e abra o app de novo.")
    if "access" in texto or "denied" in texto or "0x80070005" in texto:
        return ("Sem permissao para ler os sensores. "
                "Abra o DBX Stats como administrador.")
    if "librehardwaremonitorlib" in texto or "could not add reference" in texto:
        return ("Os arquivos do LibreHardwareMonitor nao foram encontrados. "
                "Reinstale o DBX Stats.")
    return f"{type(erro).__name__}: {erro}"


class LhmReader:
    def __init__(self) -> None:
        self._computer = None
        self._ready = False
        self._error = ""
        self._lock = threading.Lock()
        self._tree: list[SensorNode] = []
        self._tree_lock = threading.Lock()
        self._rails: dict[str, tuple[float, float]] = {}
        """Minimo e maximo ja' vistos de cada voltagem da placa; ver _vcore."""
        self._spd_at = 0.0

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> str:
        return self._error

    def start(self) -> None:
        threading.Thread(target=self._init, name="lhm-init", daemon=True).start()

    def _init(self) -> None:
        """Sobe o LibreHardwareMonitor.

        Falhar aqui e' o modo mais comum de o app "nao pegar nada" em outra
        maquina, e cada causa pede uma acao diferente do usuario. Por isso o erro
        vira uma frase que diz o que fazer, e nao so' a excecao crua.
        """
        try:
            lhm_dir = str(paths.lhm_dir())
            if lhm_dir not in sys.path:
                sys.path.insert(0, lhm_dir)
            import clr
            clr.AddReference(os.path.join(lhm_dir, "LibreHardwareMonitorLib"))
            from LibreHardwareMonitor.Hardware import Computer

            c = Computer()
            c.IsCpuEnabled = True
            c.IsGpuEnabled = True
            c.IsMemoryEnabled = True
            c.IsStorageEnabled = True
            c.IsMotherboardEnabled = True
            c.IsControllerEnabled = True
            c.IsPsuEnabled = True
            c.IsBatteryEnabled = True
            c.IsNetworkEnabled = False
            c.Open()
            with self._lock:
                self._computer = c
                self._ready = True
            _log.info("LHM aberto (%s)", lhm_dir)
        except Exception as e:
            self._error = _explicar(e)
            _log.exception("falha inicializando LHM")

    def read(self) -> dict:
        """Varre todo o hardware uma vez: devolve o dict curado e atualiza a arvore."""
        if not self._ready:
            return {}
        result: dict = {}
        gpus: list[dict] = []
        tree: list[SensorNode] = []
        try:
            with self._lock:
                if self._computer is None:
                    return {}
                hw_list = list(self._computer.Hardware)
            spd = self._spd_vencido()
            for hw in hw_list:
                if spd or not _e_modulo_spd(hw):
                    hw.Update()
                self._dispatch(hw, result, gpus)
                self._collect_tree(hw, tree)
                for sub in hw.SubHardware:
                    self._collect_tree(sub, tree, parent=str(hw.Name))
            self._pick_gpu(result, gpus)
            result["gpu_list"] = [g.get("name", "GPU") for g in gpus]
            with self._tree_lock:
                self._tree = tree
        except Exception as e:
            _log.debug("erro lendo LHM: %s", e)
        return result

    def tree(self) -> list[SensorNode]:
        with self._tree_lock:
            return list(self._tree)

    def _spd_vencido(self) -> bool:
        """Diz se ja' passou tempo bastante para conversar com os pentes de novo.

        O valor antigo continua na arvore entre uma leitura e outra: o LHM guarda
        o ultimo numero lido, entao pular o Update() envelhece a temperatura em
        segundos — e nao ha temperatura de RAM que ande nesse prazo.
        """
        agora = time.monotonic()
        if agora - self._spd_at < _SPD_INTERVALO_S:
            return False
        self._spd_at = agora
        return True

    def close(self) -> None:
        with self._lock:
            if self._computer is not None:
                try:
                    self._computer.Close()
                except Exception:
                    pass
                self._computer = None
                self._ready = False

    # ── arvore completa ──────────────────────────────────────────────────────
    def _collect_tree(self, hw, out: list[SensorNode], parent: str = "") -> None:
        hw_type = str(hw.HardwareType)
        hw_name = str(hw.Name)
        label = f"{parent} · {hw_name}" if parent else hw_name
        for s in hw.Sensors:
            value = s.Value
            if value is None:
                continue
            kind = str(s.SensorType)
            name = str(s.Name)
            out.append(SensorNode(
                key=f"{label}/{kind}/{name}", hardware=label, hw_type=hw_type,
                name=name, kind=kind, unit=UNITS.get(kind, ""), value=float(value)))

    # ── leitura curada ───────────────────────────────────────────────────────
    def _dispatch(self, hw, result: dict, gpus: list) -> None:
        hw_type = str(hw.HardwareType)
        if hw_type == "Cpu":
            self._read_cpu(hw, result)
        elif hw_type in ("GpuNvidia", "GpuAmd", "GpuIntel"):
            self._read_gpu(hw, hw_type, gpus)
        elif hw_type == "Memory":
            self._read_memory(hw, result)
        elif hw_type == "Motherboard":
            self._read_motherboard(hw, result)
        elif hw_type == "Storage":
            self._read_storage(hw, result)

    def _read_cpu(self, hw, result: dict) -> None:
        result.setdefault("cpu_name", str(hw.Name))
        temps_by_name: dict[str, float] = {}
        core_temps: list[float] = []
        core_clocks: list[float] = []
        core_loads: list[tuple[int, float]] = []
        vids: list[float] = []
        volts: list[float] = []
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature":
                temps_by_name[name] = f
                if ("CCD" not in name and "Core" in name and "Max" not in name
                        and "Average" not in name and "Tctl" not in name):
                    core_temps.append(f)
            elif st == "Clock":
                if "Average)" in name and "Effective" not in name:
                    result["cpu_mhz_avg"] = int(f)
                elif "Core #" in name and "Effective" not in name:
                    core_clocks.append(f)
            elif st == "Load":
                if name == "CPU Total":
                    result["cpu_pct_lhm"] = round(f, 1)
                elif name.startswith("CPU Core #") and "Thread" not in name:
                    core_loads.append((_core_index(name), round(f, 1)))
            elif st == "Power":
                if name in ("Package", "CPU Package") and f > 0:
                    result["cpu_watts"] = round(f, 1)
                elif name in ("CPU Cores", "Cores") and f > 0:
                    result["cpu_watts_cores"] = round(f, 1)
            elif st == "Fan" and f > 0:
                result.setdefault("cpu_fan", int(f))
            elif st == "Voltage" and "VID" in name:
                vids.append(f)
            elif st == "Voltage" and "Core" in name:
                volts.append(f)

        if vids:
            result["cpu_vid"] = round(max(vids), 3)
        if volts:
            _publicar_volts(result, max(volts), "cpu")

        # Duas leituras contam historia diferente e o overlay mostra as duas:
        # Tctl/Tdie e' o ponto mais quente do encapsulamento, que e' quem dita
        # boost e limite; a media dos dies (ou dos nucleos, quando existem) e' a
        # temperatura de trabalho. So' o pico assusta a toa; so' a media esconde
        # throttle.
        pacote = None
        for key in ("Core (Tctl/Tdie)", "Tctl/Tdie", "Tdie", "CPU Package", "Package"):
            achados = [v for nm, v in temps_by_name.items() if key in nm and v > 0]
            if achados:
                pacote = max(achados)
                break
        if pacote:
            result["cpu_temp_package"] = round(pacote, 1)

        medias = [t for t in core_temps if t > 0]
        if not medias:
            # Ryzen nao expoe nucleo a nucleo; o que ele da' e' um sensor por CCD.
            medias = [v for nm, v in temps_by_name.items() if "CCD" in nm and v > 0]
        if medias:
            result["cpu_temp_cores"] = round(sum(medias) / len(medias), 1)

        temp = None
        for key in _CPU_TEMP_PRIORITY:
            matches = [v for nm, v in temps_by_name.items() if key in nm and v > 0]
            if matches:
                temp = max(matches)
                break
        if temp is None and core_temps:
            valid = [t for t in core_temps if t > 0]
            temp = max(valid) if valid else None
        if temp is not None and temp > 0:
            result["cpu_temp"] = round(temp, 1)
        if core_clocks:
            result["cpu_mhz_max"] = int(max(core_clocks))
            result["cpu_core_clocks"] = [int(c) for c in core_clocks]
        if core_loads:
            result["cpu_core_loads"] = [v for _, v in sorted(core_loads)]
        if core_temps:
            result["cpu_core_temps"] = [round(t, 1) for t in core_temps]

    def _read_gpu(self, hw, hw_type: str, gpus: list) -> None:
        g: dict = {"name": str(hw.Name), "type": hw_type}
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature" and name == "GPU Core" and f > 0:
                g["temp"] = int(f)
            elif st == "Temperature" and "Hot Spot" in name and f > 0:
                g["temp_hotspot"] = int(f)
            elif st == "Temperature" and "Memory" in name and f > 0:
                g["temp_vram"] = int(f)
            elif st == "Power" and f > 0 and "watts" not in g:
                g["watts"] = round(f, 1)
            elif st == "Clock" and name == "GPU Core":
                g["freq"] = int(f)
            elif st == "Clock" and "GPU Memory" in name:
                g["mem_freq"] = int(f)
            elif st == "Load" and name == "GPU Core":
                g["usage"] = int(f)
            elif st == "Load" and "Memory Controller" in name:
                g["mem_ctrl"] = int(f)
            elif st == "Load" and "Video Engine" in name:
                g["video_engine"] = int(f)
            elif st == "SmallData" and "GPU Memory Used" in name:
                g["vram_used"] = int(f)
            elif st == "SmallData" and "GPU Memory Total" in name:
                g["vram_total"] = int(f)
            elif st == "Fan" and "GPU Fan" in name:
                g["fan_rpm"] = int(f)
            elif st == "Control" and "GPU Fan" in name:
                g["fan_pct"] = int(f)
            elif st == "Voltage" and "GPU Core" in name and f > 0:
                g["volts"] = round(f, 3)
            elif st == "Voltage" and f > 0 and _e_volt_de_nucleo(name):
                # Nem todo driver escreve exatamente "GPU Core", mas o rail do
                # nucleo sempre se identifica pelo nome. Rail sem "core" no nome
                # (SoC, VRAM) fica de fora: seria outra tensao com outro rotulo.
                g.setdefault("volts_alt", round(f, 3))
        alt = g.pop("volts_alt", None)
        if "volts" not in g and alt is not None:
            g["volts"] = alt
        gpus.append(g)

    def _pick_gpu(self, result: dict, gpus: list) -> None:
        if not gpus:
            return
        best = max(gpus, key=_gpu_score)
        result["gpu_ok"] = True
        result["gpu_name"] = best.get("name", "GPU")
        result["_gpu_type"] = best.get("type")
        for key in ("temp", "temp_hotspot", "temp_vram", "freq", "mem_freq", "usage",
                    "mem_ctrl", "video_engine", "vram_used", "vram_total",
                    "fan_rpm", "fan_pct", "watts", "volts"):
            if key in best:
                result["gpu_" + key] = best[key]

    def _read_memory(self, hw, result: dict) -> None:
        if str(hw.Name) != "Total Memory":
            self._read_dimm(hw, result)
            return
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Data" and "Virtual" in name and "Used" in name:
                result["swap_used_lhm"] = round(f, 2)
            elif st == "Data" and "Used" in name:
                result["ram_used_lhm"] = round(f, 2)
            elif st == "Data" and "Available" in name:
                result["ram_avail_lhm"] = round(f, 2)
            elif st == "Load" and "Virtual" in name:
                result["swap_pct_lhm"] = round(f, 1)
            elif st == "Load" and "Memory" in name:
                result["ram_pct_lhm"] = round(f, 1)

    def _read_dimm(self, hw, result: dict) -> None:
        """Temperatura de um pente de RAM, lida do proprio modulo pelo SPD.

        So' existe com o app elevado: sem admin estes hardwares nem aparecem na
        arvore do LHM — nao ha erro, eles simplesmente somem, que e' o jeito mais
        facil de alguem concluir que a maquina nao tem o sensor.
        """
        modulo: dict = {}
        for s in hw.Sensors:
            if str(s.SensorType) != "Temperature" or s.Value is None:
                continue
            name = str(s.Name)
            f = round(float(s.Value), 2)
            # Os limites vem de fabrica no proprio pente: e' a faixa certa para
            # colorir a leitura, em vez de um numero chutado no app.
            if "Critical High" in name:
                modulo["critical"] = f
            elif "High Limit" in name:
                modulo["high"] = f
            elif "Resolution" in name or "Low" in name:
                continue
            elif f > 0:
                modulo["slot"] = name
                modulo["temp"] = f
        if "temp" not in modulo:
            return
        modulo["model"] = _limpar_spd(str(hw.Name))
        result.setdefault("ram_modules", []).append(modulo)
        anterior = result.get("ram_temp")
        result["ram_temp"] = (modulo["temp"] if anterior is None
                              else max(anterior, modulo["temp"]))

    def _read_motherboard(self, hw, result: dict) -> None:
        result.setdefault("board_name", str(hw.Name))
        fans: list[int] = []
        rails: list[tuple[str, str, float]] = []
        for sub in hw.SubHardware:
            sub.Update()
            for s in sub.Sensors:
                if s.Value is None:
                    continue
                st = str(s.SensorType)
                nome = str(s.Name)
                nl = nome.lower()
                f = float(s.Value)
                if st == "Fan" and f > 0:
                    fans.append(int(f))
                    if "cpu" in nl:
                        result["cpu_fan"] = int(f)
                elif st == "Temperature" and ("system" in nl or "motherboard" in nl) and f > 0:
                    result.setdefault("board_temp", round(f, 1))
                elif st == "Voltage" and f > 0:
                    rails.append((f"{sub.Name}/{nome}", nome, f))
        self._vcore(rails, result)
        if fans:
            result["fans"] = fans
            result.setdefault("cpu_fan", fans[0])

    def _vcore(self, rails: list[tuple[str, str, float]], result: dict) -> None:
        """Acha a tensao real do processador entre as voltagens da placa.

        Placa sem perfil no LHM entrega os rails como "Voltage #1"…"#7": sete
        numeros anonimos, e um deles e' o Vcore. O que separa o Vcore dos outros
        nao e' o nome, e' o comportamento — ele e' o unico que anda junto com a
        carga. Por isso o rail so' e' adotado depois de se mexer de verdade;
        enquanto nao se mexeu, o app prefere nao ter numero a ter um chute.
        """
        for _, nome, valor in rails:
            if any(t in nome.lower() for t in _VCORE_NOMES):
                _publicar_volts(result, valor, "vcore")
                return
        melhor: tuple[float, float, str] | None = None
        for chave, nome, valor in rails:
            if not _VCORE_FAIXA[0] <= valor <= _VCORE_FAIXA[1]:
                continue
            baixo, alto = self._rails.get(chave, (valor, valor))
            baixo, alto = min(baixo, valor), max(alto, valor)
            self._rails[chave] = (baixo, alto)
            movimento = alto - baixo
            if movimento >= _VCORE_MOVIMENTO and (melhor is None or movimento > melhor[0]):
                melhor = (movimento, valor, nome)
        if melhor is not None:
            _publicar_volts(result, melhor[1], "rail", melhor[2])

    def _read_storage(self, hw, result: dict) -> None:
        disks = result.setdefault("disks_lhm", [])
        entry = {"name": str(hw.Name)}
        for s in hw.Sensors:
            st = str(s.SensorType)
            name = str(s.Name)
            val = s.Value
            if val is None:
                continue
            f = float(val)
            if st == "Temperature" and ("Composite" in name or name == "Temperature") and f > 0:
                entry["temp"] = round(f, 1)
            elif st == "Data" and "Total Space" in name:
                entry["total"] = round(f, 1)
            elif st == "Load" and "Used Space" in name:
                entry["used_pct"] = round(f, 1)
            elif st == "Level" and "Remaining Life" in name:
                entry["life"] = round(f, 1)
            elif st == "Data" and "Host Writes" in name:
                entry["written"] = round(f, 1)
            elif st == "Throughput" and "Read" in name:
                entry["read"] = f
            elif st == "Throughput" and "Write" in name:
                entry["write"] = f
        disks.append(entry)
        if "temp" in entry and "nvme_temp" not in result:
            result["nvme_temp"] = entry["temp"]


def _core_index(name: str) -> int:
    try:
        return int(name.split("#")[1].split()[0])
    except (IndexError, ValueError):
        return 999


def _e_modulo_spd(hw) -> bool:
    """Pente fisico de RAM, e nao os totais que o LHM calcula sozinho."""
    return (str(hw.HardwareType) == "Memory"
            and str(hw.Name) not in ("Total Memory", "Virtual Memory"))


def _e_volt_de_nucleo(name: str) -> bool:
    return "core" in name.lower() or name.strip().lower() in ("gpu voltage", "voltage")


def _limpar_spd(nome: str) -> str:
    """Tira o lixo binario do nome que veio do SPD do pente.

    Numa das leituras o modulo do slot #3 se apresentou como
    'A-DATA … DCLARBK>\\x00} (#3)' e na seguinte veio limpo: a string do SPD nem
    sempre termina onde deveria. Rotulo com byte nulo no meio parece app
    quebrado, entao o que nao e' imprimivel cai fora antes de virar texto.
    """
    limpo = "".join(c for c in nome if c.isprintable() and c not in "<>{}|")
    return " ".join(limpo.split())


def _publicar_volts(result: dict, valor: float, origem: str, rail: str = "") -> None:
    """Guarda a melhor tensao de CPU disponivel, com a procedencia junto.

    Ordem de confianca: rail que a placa nomeia como Vcore > sensor de nucleo do
    proprio processador > rail generico identificado por movimento. A ordem tem
    de valer independente de qual hardware o LHM entregou primeiro, e a tela
    precisa da procedencia para nao apresentar palpite como medida.
    """
    if _VOLTS_RANK[origem] <= _VOLTS_RANK.get(result.get("cpu_volts_src", ""), 0):
        return
    result["cpu_volts"] = round(valor, 3)
    result["cpu_volts_src"] = origem
    if rail:
        result["cpu_volts_rail"] = rail
    else:
        result.pop("cpu_volts_rail", None)
