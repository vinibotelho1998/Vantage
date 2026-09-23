"""O monitor guarda todos os processos, nao so' os que mais usam CPU.

Com o corte em 40, a aba Processos nao mostrava o navegador parado a 0% de CPU
comendo gigas de RAM, e o filtro por nome nao achava o app travado.
"""
from types import SimpleNamespace

from vantage.sensors import procs as P


class _Proc:
    def __init__(self, pid: int, cpu: float, rss_mb: float) -> None:
        self.info = {"pid": pid, "name": f"p{pid}.exe",
                     "memory_info": SimpleNamespace(rss=int(rss_mb * 1024 ** 2)),
                     "num_threads": 2}
        self._cpu = cpu

    def cpu_percent(self, _intervalo):
        return self._cpu


def test_processo_parado_com_muita_ram_continua_na_lista(monkeypatch):
    ocupados = [_Proc(pid, 50.0, 10.0) for pid in range(1, 61)]
    parado = _Proc(9999, 0.0, 3000.0)
    monkeypatch.setattr(P.psutil, "process_iter", lambda _attrs: iter(ocupados + [parado]))
    mon = P.ProcessMonitor()
    mon._cores = 1
    mon._collect()
    lista = mon.snapshot()
    assert len(lista) == 61
    assert any(p.pid == 9999 for p in lista)
    assert lista[0].cpu >= lista[-1].cpu
