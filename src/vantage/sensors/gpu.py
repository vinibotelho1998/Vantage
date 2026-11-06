"""GPU NVIDIA via NVML: uso, clocks, VRAM, potencia, PCIe e motivos de throttle.

nvidia-smi e uma estimativa por curva servem de fallback quando o driver nao
expoe potencia (comum em notebooks e em algumas GPUs mobile).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading

from .. import log

_log = log.get("gpu")

# nvmlClocksThrottleReasons: bitmask -> rotulo legivel
THROTTLE_REASONS = (
    (0x0000000000000001, "Ocioso"),
    (0x0000000000000002, "Limite de clock do usuário"),
    (0x0000000000000004, "Limite de potência (SW)"),
    (0x0000000000000008, "Proteção térmica (HW)"),
    (0x0000000000000040, "Limite térmico (SW)"),
    (0x0000000000000080, "Limite de potência (HW)"),
    (0x0000000000000100, "Queda de tensão (HW)"),
    (0x0000000000000200, "Display ativo"),
)

# NVML_FI_DEV_MEMORY_TEMP: a temperatura da VRAM nao tem funcao propria na NVML,
# so' existe pela tabela de campos. Nas placas que nao expoem o campo a chamada
# volta com erro por campo: dai' o desligamento apos a primeira recusa, para nao
# pagar uma ida ao driver por segundo por um numero que nunca vem.
_FI_MEMORY_TEMP = 82

# nvmlValueType -> membro da union que carrega o numero
_FIELD_MEMBERS = {0: "dVal", 1: "uiVal", 2: "ulVal", 3: "ullVal", 4: "sllVal",
                  5: "siVal", 6: "usVal"}


class GpuReader:
    def __init__(self) -> None:
        self._pynvml = None
        self._hdl = None
        self._ok = False
        self._name: str | None = None
        self._static: dict = {}
        self._identity: dict = {}
        self._watts_est: float | None = None
        self._smi_watts: float | None = None
        self._smi_lock = threading.Lock()
        self._smi_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._mem_temp_ok = True
        self._init_nvml()

    def _init_nvml(self) -> None:
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import pynvml
            pynvml.nvmlInit()
            self._hdl = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._pynvml = pynvml
            self._ok = True
            self._load_static()
            self._load_identity()
            _log.info("NVML inicializado: %s", self._name)
        except Exception as e:
            _log.info("NVML indisponivel: %s", e)

    def start_smi(self) -> None:
        if self._smi_thread is None:
            self._smi_thread = threading.Thread(target=self._smi_loop, name="nvidia-smi",
                                                daemon=True)
            self._smi_thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def nvml_ok(self) -> bool:
        return self._ok

    @property
    def static(self) -> dict:
        return dict(self._static)

    @property
    def identity(self) -> dict:
        """Identidade da placa consultada e inventario para evitar nomes ambiguos."""
        return dict(self._identity)

    def _load_identity(self) -> None:
        p, h = self._pynvml, self._hdl
        identity = {"index": 0, "name": self._name}
        for key, fn in (("uuid", lambda: p.nvmlDeviceGetUUID(h)),
                        ("pci_bus_id", lambda: p.nvmlDeviceGetPciInfo(h).busId)):
            try:
                value = fn()
                identity[key] = value.decode() if isinstance(value, bytes) else str(value)
            except Exception:
                pass
        try:
            names = []
            for index in range(p.nvmlDeviceGetCount()):
                value = p.nvmlDeviceGetName(p.nvmlDeviceGetHandleByIndex(index))
                names.append(value.decode() if isinstance(value, bytes) else str(value))
            identity["names"] = tuple(names)
        except Exception:
            # Uma placa sem nome pode ser igual a selecionada. Inventario parcial
            # nao comprova que o modelo seja unico e nao autoriza a fusao.
            identity["names"] = None
        self._identity = identity

    def reset_estimate(self) -> None:
        self._watts_est = None

    def _load_static(self) -> None:
        p, h = self._pynvml, self._hdl
        info: dict = {}
        for key, fn in (
            ("name", lambda: p.nvmlDeviceGetName(h)),
            ("driver", lambda: p.nvmlSystemGetDriverVersion()),
            ("vbios", lambda: p.nvmlDeviceGetVbiosVersion(h)),
            ("power_limit", lambda: p.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0),
            ("max_clock", lambda: p.nvmlDeviceGetMaxClockInfo(h, p.NVML_CLOCK_GRAPHICS)),
            ("max_mem_clock", lambda: p.nvmlDeviceGetMaxClockInfo(h, p.NVML_CLOCK_MEM)),
            ("pcie_gen", lambda: p.nvmlDeviceGetCurrPcieLinkGeneration(h)),
            ("pcie_width", lambda: p.nvmlDeviceGetCurrPcieLinkWidth(h)),
            ("temp_slowdown", lambda: p.nvmlDeviceGetTemperatureThreshold(
                h, p.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN)),
        ):
            try:
                v = fn()
                info[key] = v.decode() if isinstance(v, bytes) else v
            except Exception:
                continue
        self._name = info.get("name")
        self._static = info

    def read_nvml(self) -> dict | None:
        if not self._ok:
            return None
        p, h = self._pynvml, self._hdl
        try:
            util = p.nvmlDeviceGetUtilizationRates(h)
            mem = p.nvmlDeviceGetMemoryInfo(h)
            return {
                "name": self._name or "GPU",
                "usage": util.gpu,
                "mem_ctrl": util.memory,
                "temp": p.nvmlDeviceGetTemperature(h, p.NVML_TEMPERATURE_GPU),
                "temp_vram": self.mem_temp(),
                "vram_used": mem.used // 1024 ** 2,
                "vram_total": mem.total // 1024 ** 2,
                "freq": p.nvmlDeviceGetClockInfo(h, p.NVML_CLOCK_GRAPHICS),
                "mem_freq": p.nvmlDeviceGetClockInfo(h, p.NVML_CLOCK_MEM),
                "watts": self._try(lambda: round(p.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)),
                "fan_pct": self._try(lambda: p.nvmlDeviceGetFanSpeed(h)),
                "pcie_tx": self._try(
                    lambda: p.nvmlDeviceGetPcieThroughput(h, p.NVML_PCIE_UTIL_TX_BYTES)),
                "pcie_rx": self._try(
                    lambda: p.nvmlDeviceGetPcieThroughput(h, p.NVML_PCIE_UTIL_RX_BYTES)),
                "encoder": self._try(lambda: p.nvmlDeviceGetEncoderUtilization(h)[0]),
                "decoder": self._try(lambda: p.nvmlDeviceGetDecoderUtilization(h)[0]),
                "throttle": self.throttle_reasons(),
            }
        except Exception as e:
            _log.debug("erro NVML: %s", e)
            return None

    def throttle_reasons(self) -> list[str]:
        if not self._ok:
            return []
        try:
            mask = self._pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(self._hdl)
        except Exception:
            return []
        return [label for bit, label in THROTTLE_REASONS if mask & bit]

    def mem_temp(self) -> int | None:
        """Temperatura da VRAM, quando a placa publica o campo."""
        if not self._ok or not self._mem_temp_ok:
            return None
        try:
            campos = self._pynvml.nvmlDeviceGetFieldValues(self._hdl, [_FI_MEMORY_TEMP])
            valor = _field_number(campos[0]) if campos else None
        except Exception as e:
            _log.debug("temperatura da VRAM via NVML: %s", e)
            valor = None
        if valor is None:
            self._mem_temp_ok = False
            return None
        return int(valor)

    def vram(self) -> tuple[int, int] | None:
        if not self._ok:
            return None
        try:
            mem = self._pynvml.nvmlDeviceGetMemoryInfo(self._hdl)
            return mem.used // 1024 ** 2, mem.total // 1024 ** 2
        except Exception:
            return None

    def watts_nvml(self) -> float | None:
        if not self._ok:
            return None
        return self._try(
            lambda: round(self._pynvml.nvmlDeviceGetPowerUsage(self._hdl) / 1000.0, 1))

    def watts_smi(self) -> float | None:
        with self._smi_lock:
            return self._smi_watts

    def watts_estimate(self, usage=None, freq=None) -> float | None:
        """Modelo potencia x (uso, clock) suavizado, so quando nao ha leitura real."""
        if not self._ok:
            return None
        p, h = self._pynvml, self._hdl
        try:
            limit = self._static.get("power_limit") or p.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0
            if usage is None:
                usage = float(p.nvmlDeviceGetUtilizationRates(h).gpu)
            if freq is None:
                freq = float(p.nvmlDeviceGetClockInfo(h, p.NVML_CLOCK_GRAPHICS))
            max_clk = float(self._static.get("max_clock")
                            or p.nvmlDeviceGetMaxClockInfo(h, p.NVML_CLOCK_GRAPHICS))
            util_r = max(0.0, min(1.0, float(usage) / 100.0))
            clk_r = max(0.0, min(1.0, (float(freq) / max_clk) if max_clk > 0 else util_r))
            idle = max(8.0, limit * 0.08)
            load = 0.70 * util_r + 0.30 * clk_r
            est = idle + (limit - idle) * (load ** 0.9)
            self._watts_est = est if self._watts_est is None else (
                self._watts_est * 0.70 + est * 0.30)
            return round(self._watts_est, 1)
        except Exception:
            return None

    def _try(self, fn):
        try:
            return fn()
        except Exception:
            return None

    def _smi_loop(self) -> None:
        candidates = [
            shutil.which("nvidia-smi"),
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]
        nsmi = next((p for p in candidates if p and os.path.exists(p)), None)
        if not nsmi:
            _log.info("nvidia-smi nao encontrado; fallback de watts desativado")
            return
        while not self._stop.is_set():
            # Reserva e' so' reserva: com a NVML entregando o consumo, subir um
            # processo a cada dois segundos a partida inteira e' custo no pior
            # momento. O valor antigo sai junto, para nao ficar parado na tela.
            if self.watts_nvml() is not None:
                with self._smi_lock:
                    self._smi_watts = None
                self._stop.wait(2.0)
                continue
            try:
                out = subprocess.check_output(
                    [nsmi, "--id=0", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
                    timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    stderr=subprocess.DEVNULL)
                v = _parse_smi_watts(out.decode(errors="ignore"))
                with self._smi_lock:
                    self._smi_watts = None if v is None else round(v, 1)
            except Exception as e:
                with self._smi_lock:
                    self._smi_watts = None
                _log.debug("nvidia-smi: %s", e)
            self._stop.wait(2.0)


def _field_number(campo) -> float | None:
    """Le o numero de um nvmlFieldValue_t.

    O valor chega numa union: ler o membro errado nao levanta erro nenhum, so'
    devolve outro numero: 45 °C viraria algo como 1,1e-43. Por isso o tipo
    declarado no proprio campo e' quem escolhe o membro, e campo que voltou com
    erro (placa que nao publica aquilo) nao vira leitura.
    """
    if getattr(campo, "nvmlReturn", 1) != 0:
        return None
    membro = _FIELD_MEMBERS.get(int(campo.valueType))
    if membro is None:
        return None
    return float(getattr(campo.value, membro))


def _parse_smi_watts(text: str) -> float | None:
    for raw in text.splitlines():
        tok = raw.strip().replace(" W", "").replace(",", ".")
        if tok.lower() in ("n/a", "[n/a]", "[not supported]", ""):
            continue
        try:
            return float(tok)
        except ValueError:
            continue
    return None
