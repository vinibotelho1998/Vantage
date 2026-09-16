"""Smoke test da engine de sensores, headless (sem UI)."""
from __future__ import annotations

import time

from vantage.sensors.collector import Collector
from vantage.sensors.gpu import GpuReader
from vantage.sensors.lhm import LhmReader
from vantage.sensors.net import PingMonitor


def main() -> int:
    lhm = LhmReader()
    lhm.start()
    gpu = GpuReader()
    gpu.start_smi()
    ping = PingMonitor()
    ping.start()
    col = Collector(lhm, gpu, ping, update_interval=0.5)
    col.start()

    try:
        for i in range(6):
            time.sleep(1)
            d = col.snapshot()
            if not d:
                print(f"[{i}] (aguardando primeiro ciclo)")
                continue
            g = d.get("gpu") or {}
            print(
                f"[{i}] cpu={d['cpu_pct']:.0f}% temp={d.get('cpu_temp')} "
                f"mhz={d.get('cpu_mhz')} watts={d.get('cpu_watts')} fan={d.get('cpu_fan')} "
                f"| ram={d['ram_used']:.1f}/{d['ram_total']:.0f}G ({d['ram_pct']:.0f}%) freq={d.get('ram_freq')} "
                f"| gpu={g.get('name')} use={g.get('usage')} t={g.get('temp')} w={g.get('watts')} "
                f"| disk={d['disk_used']:.0f}/{d['disk_total']:.0f}G nvme={d.get('nvme_temp')} "
                f"| net dl={d['net_dl'] / 1024:.0f}KB/s ping={d.get('ping_ms')}")
    finally:
        print(f"\nlhm_ready={lhm.ready}  lhm_err={lhm.error!r}  nvml_ok={gpu.nvml_ok}")
        col.stop()
        ping.stop()
        lhm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
