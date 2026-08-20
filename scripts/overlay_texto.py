"""Desenha o overlay sem tela e imprime o arranjo como texto.

Conferir o overlay abrindo um jogo a cada mexida e' caro e nao repete: aqui ele
e' montado de verdade (a mesma classe do app), o Qt faz o layout, e a geometria
final de cada rotulo vira uma grade de caracteres. Da' para ver o que colapsa
quando falta sensor, o que acontece em duas colunas e onde o painel cai para o
modo compacto — tudo no terminal.

    python scripts/overlay_texto.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Dados isolados: script de desenvolvimento nunca pode gravar por cima do
# settings.json de verdade.
os.environ.setdefault("DBXSTATS_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "dbxstats-dev"))
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from PySide6.QtGui import QFontMetricsF, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from dbxstats.config import OVERLAY_METRICS, Settings  # noqa: E402
from dbxstats.core import frames as fr  # noqa: E402
from dbxstats.ui.charts import Sparkline  # noqa: E402
from dbxstats.ui.overlay import GameOverlay  # noqa: E402

_TAG = re.compile(r"<[^>]+>")


class _Metrics:
    frames = 5200
    fps_now = 98.0
    fps_avg = 141.0
    low_1 = 62.0
    low_01 = 51.0
    ft_avg = 10.2
    stutter_pct = 2.8
    bottleneck = fr.BOTTLENECK_GPU
    cpu_bound_pct = 2.0
    gpu_bound_pct = 96.0
    capped_pct = 1.0


class _Stream:
    app = "cyberpunk2077.exe"
    pid = 4242
    metrics = _Metrics()


class _Hist:
    def values(self, _chave):
        base = [138, 142, 151, 147, 139, 144, 158, 152, 146, 141, 120, 99, 92, 98]
        return [b + (i % 3) for i, b in enumerate(base * 6)]


class _Ping:
    target_label = "8.8.8.8"
    following_game = False


class _Ctl:
    def __init__(self, cfg, dados, stream) -> None:
        self.settings = cfg
        self.ping = _Ping()
        self.history = _Hist()
        self._d = dados
        self._s = stream

    def last_data(self):
        return self._d

    def active_stream(self):
        return self._s


def snapshot_completo() -> dict:
    """Numeros plausiveis desta maquina com um jogo pesado na frente."""
    return {
        "lhm_ok": True,
        "cpu_pct": 38.0, "cpu_mhz": 5200, "cpu_watts": 71.0,
        "cpu_temp": 82.0, "cpu_temp_cores": 69.0, "cpu_temp_package": 82.0,
        "cpu_volts": 1.118, "cpu_volts_src": "rail", "cpu_volts_rail": "Voltage #1",
        "cpu_vid": 0.769,
        "ram_used": 27.9, "ram_total": 31.6, "ram_pct": 88.0, "ram_freq": 6000,
        "ram_temp": 47.0,
        "ram_modules": [{"slot": "DIMM #1", "temp": 47.0, "high": 55.0,
                         "critical": 85.0, "model": "A-DATA AX5U6000 (#1)"},
                        {"slot": "DIMM #3", "temp": 45.5, "high": 55.0,
                         "critical": 85.0, "model": "A-DATA AX5U6000 (#3)"}],
        "game_pid": 4242, "game_name": "cyberpunk2077.exe",
        "game_ram_private": 14950.0, "game_ram_wset": 12390.0,
        "ping_ms": 23.0, "packet_loss": 0.0,
        "gpu": {"usage": 99.0, "freq": 2440, "volts": 0.928, "watts": 289.0,
                "temp": 81, "temp_hotspot": 104, "temp_vram": 101,
                "mem_ctrl": 94.0, "mem_freq": 2518, "power_limit": 330.0,
                "vram_used": 15810, "vram_total": 16384, "vram_pct": 96.5},
    }


def snapshot_pelado() -> dict:
    """Maquina sem LHM, sem GPU dedicada, sem sensor de pente e sem jogo."""
    return {
        "lhm_ok": False,
        "cpu_pct": 12.0, "cpu_mhz": None, "cpu_watts": None, "cpu_temp": None,
        "cpu_temp_cores": None, "cpu_temp_package": None, "cpu_volts": None,
        "cpu_vid": None,
        "ram_used": 7.8, "ram_total": 16.0, "ram_pct": 48.0, "ram_freq": None,
        "ram_temp": None, "ram_modules": None,
        "ping_ms": None, "packet_loss": None,
        "gpu": None,
    }


def texto_do_overlay(ov: GameOverlay) -> str:
    """Reconstroi o painel numa grade de caracteres a partir da geometria real."""
    # isVisibleTo, e nao isHidden: a linha do gargalo desligada esconde a caixa
    # inteira, e os filhos dela seguem "nao escondidos" com geometria de widget
    # recem-criado — entrariam no desenho no lugar errado.
    labels = [w for w in ov.findChildren(QLabel) if w.isVisibleTo(ov) and w.text()]
    sparks = [w for w in ov.findChildren(Sparkline) if w.isVisibleTo(ov)]
    if not labels:
        return "(painel vazio)"
    char = min(QFontMetricsF(w.font()).horizontalAdvance("0") or 99 for w in labels)
    char = max(4.0, min(char, 12.0))
    largura = int(ov.width() / char) + 2

    itens = []
    for w in labels:
        pos = w.mapTo(ov, w.rect().topLeft())
        itens.append((pos.y(), pos.y() + w.height(), pos.x(),
                      _TAG.sub("", w.text()).replace("&nbsp;", " ")))
    for w in sparks:
        pos = w.mapTo(ov, w.rect().topLeft())
        itens.append((pos.y(), pos.y() + w.height(), pos.x(),
                      "▁" * max(1, int(w.width() / char))))

    itens.sort(key=lambda it: (it[0], it[2]))
    linhas: list[list] = []
    for item in itens:
        centro = (item[0] + item[1]) / 2
        for linha in linhas:
            if linha[0][0] - 2 <= centro <= linha[0][1] + 2:
                linha.append(item)
                break
        else:
            linhas.append([item])

    saida = ["┌" + "─" * largura + "┐"]
    for linha in linhas:
        grade = [" "] * largura
        for _topo, _base, x, texto in sorted(linha, key=lambda it: it[2]):
            col = int(round(x / char))
            for i, ch in enumerate(texto):
                if 0 <= col + i < largura:
                    grade[col + i] = ch
        saida.append("│" + "".join(grade) + "│")
    saida.append("└" + "─" * largura + "┘")
    saida.append(f"   {ov.width()} x {ov.height()} px")
    return "\n".join(saida)


def cenario(titulo: str, cfg: Settings, dados, stream) -> None:
    ov = GameOverlay(_Ctl(cfg, dados, stream))
    ov.refresh()
    ov.adjustSize()
    ov.render(QPixmap(ov.size()))     # pintura de verdade: pega erro de QSS
    print(f"\n=== {titulo} ===")
    print(texto_do_overlay(ov))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    QApplication(sys.argv)

    cenario("padrão de fábrica", Settings(), snapshot_completo(), _Stream())

    tudo = Settings()
    tudo.overlay_metrics = [k for k, _ in OVERLAY_METRICS]
    cenario("todas as métricas ligadas", tudo, snapshot_completo(), _Stream())

    duas = Settings()
    duas.overlay_columns = 2
    cenario("duas colunas", duas, snapshot_completo(), _Stream())

    grande = Settings()
    grande.overlay_scale = 1.6
    cenario("escala 1.6 (cai sozinho para o compacto)", grande,
            snapshot_completo(), _Stream())

    cenario("sem sensores, sem GPU, sem jogo", Settings(), snapshot_pelado(), None)

    meio = snapshot_completo()
    meio["cpu_volts"] = None
    meio["gpu"]["volts"] = None
    meio["ram_temp"] = None
    meio["gpu"]["temp_vram"] = None
    meio.pop("game_ram_private")
    meio.pop("game_pid")
    cenario("sem tensões, sem temp de memória e sem RAM do jogo",
            Settings(), meio, _Stream())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
