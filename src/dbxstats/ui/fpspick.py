"""Selecao do processo de FPS a exibir: pin, janela ativa ou melhor candidato."""
from __future__ import annotations

SYS_PROCS = {"dwm.exe", "explorer.exe", "shellexperiencehost.exe",
             "searchhost.exe", "widgetservice.exe", "textinputhost.exe"}


def pick(by_pid: dict, fg_pid: int, pin: str):
    if pin and by_pid:
        matches = [v for v in by_pid.values() if v[1].lower() == pin.lower()]
        return max(matches, key=lambda x: x[0]) if matches else None
    if fg_pid in by_pid:
        return by_pid[fg_pid]
    if by_pid:
        pool = {p: v for p, v in by_pid.items() if v[1].lower() not in SYS_PROCS} or by_pid
        return max(pool.values(), key=lambda x: x[0])
    return None


def pid_of(by_pid: dict, entry) -> int | None:
    return next((p for p, v in by_pid.items() if v is entry), None)
