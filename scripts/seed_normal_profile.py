"""Guarda o arranjo de telas atual como o perfil padrao ("Normal").

Util depois de deixar as telas do jeito que se usa no dia a dia: roda uma vez e
o app passa a ter para onde voltar quando um jogo fecha ou quando ele mesmo e'
fechado. Sem isso ele usa uma fotografia tirada na hora em que abriu, que pode
ter pego a maquina ja' fora do arranjo de sempre.

    python scripts/seed_normal_profile.py [nome]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from vantage.config import Settings  # noqa: E402
from vantage.platform import displays as D  # noqa: E402


def main(nome: str = "Normal") -> int:
    entries = D.snapshot()
    ligadas = [e for e in entries if e.get("active")]
    if not ligadas:
        print("nenhuma tela ligada; nada a guardar")
        return 1

    cfg = Settings.load()
    perfil = {"name": nome, "hotkey": "",
              "topology": "clone" if D.looks_cloned() else "",
              "entries": entries}
    cfg.display_profiles = [p for p in cfg.display_profiles if p["name"] != nome] + [perfil]
    cfg.display_default_profile = nome
    cfg.sanitize()
    cfg.save()

    print(f"perfil '{nome}' salvo como padrao:")
    for e in entries:
        estado = "ligada" if e["active"] else "desligada"
        modo = f"{e['mode'][0]}x{e['mode'][1]} @ {e['mode'][2]} Hz" if e.get("mode") else "-"
        marca = "  (primaria)" if e.get("primary") else ""
        print(f"  {e['name']:16} {estado:10} {modo:22} pos={tuple(e['position'])}{marca}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "Normal"))
