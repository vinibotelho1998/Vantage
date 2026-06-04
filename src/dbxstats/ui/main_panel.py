"""Janela principal: painel dock premium com cards animados e hero de FPS."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..platform import win
from . import fpspick
from .fps_graph import FpsGraph
from .widgets import SectionCard, divider, make_font

_DIAS = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
         "Sexta-feira", "Sábado", "Domingo"]
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]
_FPS_COLS = [("inst", "INST"), ("avg", "AVG"), ("1low", "1% LOW"), ("01low", "0.1% LOW")]
_MARGIN = 16


def _fmt_bytes(b: float) -> str:
    if b < 1024:
        return f"{b:.0f} B/s"
    if b < 1 << 20:
        return f"{b / 1024:.1f} KB/s"
    if b < 1 << 30:
        return f"{b / 1024 ** 2:.1f} MB/s"
    return f"{b / 1024 ** 3:.2f} GB/s"


class PanelWindow(QWidget):
    def __init__(self, controller) -> None:
        super().__init__()
        self._ctl = controller
        self._cfg = controller.settings
        self._drag_pos: QPoint | None = None
        self._fps_layout_state: dict | None = None
        self._graph_visible = True
        self._io_tick = 0

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._build()
        self.apply_settings(self._cfg)
        self.update_clock()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)

        self._root = QFrame()
        self._root.setObjectName("Root")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setColor(QColor(0, 0, 0, 170))
        shadow.setOffset(0, 7)
        self._root.setGraphicsEffect(shadow)
        outer.addWidget(self._root)

        lay = QVBoxLayout(self._root)
        lay.setContentsMargins(13, 11, 13, 10)
        lay.setSpacing(6)

        self._build_header(lay)
        self._build_fps(lay)
        lay.addWidget(divider())
        self._build_sections(lay)
        self._build_footer(lay)

    def _build_header(self, lay: QVBoxLayout) -> None:
        top = QHBoxLayout()
        top.setSpacing(8)
        brand = QLabel("DBX")
        brand.setFont(make_font(11, QFont.Weight.Black))
        brand.setStyleSheet(f"color: {theme.accent_color(self._cfg.accent)};")
        sub = QLabel("STATS")
        sub.setFont(make_font(8.5, QFont.Weight.Bold))
        sub.setProperty("role", "faint")
        sub.setAlignment(Qt.AlignmentFlag.AlignBottom)
        top.addWidget(brand)
        top.addWidget(sub)
        top.addStretch(1)
        self._status_dot = QLabel("●")
        self._status_dot.setFont(make_font(8))
        self._status_dot.setStyleSheet(f"color: {theme.FAINT};")
        top.addWidget(self._status_dot)
        top.addSpacing(4)
        self._btn_cfg = self._header_button("⚙", self._open_menu)
        top.addWidget(self._btn_cfg)
        top.addWidget(self._header_button("—", self._ctl.toggle_panel))
        top.addWidget(self._header_button("✕", self._ctl.quit))
        lay.addLayout(top)

        self._clock = QLabel("00:00:00")
        self._clock.setFont(make_font(23, QFont.Weight.Bold))
        self._clock.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._clock)
        self._date = QLabel("")
        self._date.setProperty("role", "mute")
        self._date.setFont(make_font(8.5))
        self._date.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._date)

    def _header_button(self, text: str, callback) -> QLabel:
        b = QLabel(text)
        b.setFont(make_font(11, QFont.Weight.Bold))
        b.setStyleSheet(f"color: {theme.MUTE};")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.mousePressEvent = lambda _e: callback()
        return b

    def _build_fps(self, lay: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(2)
        self._fps_cols: dict[str, QWidget] = {}
        self._fps_vals: dict[str, QLabel] = {}
        for key, label in _FPS_COLS:
            col = QWidget()
            cl = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            cap = QLabel(label)
            cap.setProperty("role", "faint")
            cap.setFont(make_font(6.5, QFont.Weight.Bold))
            cap.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            val = QLabel("—")
            val.setFont(make_font(16, QFont.Weight.Bold))
            val.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            val.setStyleSheet(f"color: {theme.MUTE};")
            cl.addWidget(cap)
            cl.addWidget(val)
            self._fps_cols[key] = col
            self._fps_vals[key] = val
            row.addWidget(col, 1)
        lay.addLayout(row)

        sub = QHBoxLayout()
        sub.setSpacing(4)
        self._game = QLabel("Auto ▾")
        self._game.setProperty("role", "mute")
        self._game.setFont(make_font(7.5))
        self._game.setCursor(Qt.CursorShape.PointingHandCursor)
        self._game.mousePressEvent = lambda _e: self._open_game_picker()
        sub.addWidget(self._game)
        sub.addStretch(1)
        ftcap = QLabel("Frametime")
        ftcap.setProperty("role", "faint")
        ftcap.setFont(make_font(7.5))
        self._ft = QLabel("")
        self._ft.setProperty("role", "mute")
        self._ft.setFont(make_font(7.5))
        sub.addWidget(ftcap)
        sub.addWidget(self._ft)
        lay.addLayout(sub)

        self._graph = FpsGraph()
        lay.addWidget(self._graph)

    def _build_sections(self, lay: QVBoxLayout) -> None:
        self.cpu = SectionCard("CPU", theme.CPU, with_spark=True)
        for k, lbl in [("pct", "Uso"), ("freq", "Frequência"), ("temp", "Temperatura"),
                       ("watts", "Potência"), ("fan", "Cooler")]:
            self.cpu.add_row(k, lbl)
        lay.addWidget(self.cpu)

        self.ram = SectionCard("Memória", theme.RAM, with_spark=True)
        for k, lbl in [("used", "Em uso"), ("avail", "Disponível"), ("freq", "Frequência")]:
            self.ram.add_row(k, lbl)
        lay.addWidget(self.ram)

        self.gpu = SectionCard("GPU", theme.GPU, with_spark=True)
        for k, lbl in [("pct", "Uso"), ("temp", "Temperatura"), ("fan", "Cooler"),
                       ("watts", "Potência"), ("freq", "Frequência"), ("vram", "VRAM")]:
            self.gpu.add_row(k, lbl)
        lay.addWidget(self.gpu)

        self.disk = SectionCard("Disco", theme.DISK, with_spark=True, fixed_max=None)
        for k, lbl in [("used", "Uso"), ("temp", "Temperatura"),
                       ("read", "Leitura"), ("write", "Escrita")]:
            self.disk.add_row(k, lbl)
        lay.addWidget(self.disk)

        self.net = SectionCard("Rede", theme.NET, with_bar=False, with_spark=True, fixed_max=None)
        for k, lbl in [("dl", "Download"), ("ul", "Upload"), ("ping", "Ping"), ("loss", "Perda")]:
            self.net.add_row(k, lbl)
        lay.addWidget(self.net)

    def _build_footer(self, lay: QVBoxLayout) -> None:
        self._uptime = QLabel("Uptime 00:00:00")
        self._uptime.setProperty("role", "faint")
        self._uptime.setFont(make_font(7.5))
        self._uptime.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._uptime)

    # ── settings / posicionamento ──────────────────────────────────────────────
    def apply_settings(self, cfg) -> None:
        self._cfg = cfg
        self.setWindowOpacity(cfg.opacity)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if cfg.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self.windowFlags() != flags:
            self.setWindowFlags(flags)
            self.show()
        self._root.setFixedWidth(cfg.width)
        self.adjustSize()
        self.place()

    def place(self) -> None:
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        gap = 0
        pos = self._cfg.position
        right = area.right() - w + 1
        bottom = area.bottom() - h + 1
        top = area.top()
        left = area.left()
        coords = {
            "right": (right, top + 24),
            "left": (left, top + 24),
            "top-right": (right, top),
            "top-left": (left, top),
            "bottom-right": (right, bottom),
            "bottom-left": (left, bottom),
        }
        x, y = coords.get(pos, coords["bottom-right"])
        self.move(int(x) - gap, int(y))

    # ── updates ─────────────────────────────────────────────────────────────--
    def update_clock(self) -> None:
        now = datetime.now()
        self._clock.setText(now.strftime("%H:%M:%S"))
        self._date.setText(f"{_DIAS[now.weekday()]}, {now.day} de {_MESES[now.month - 1]}")

    def update_system(self, d: dict) -> None:
        if not d:
            return
        show = self._cfg.show_stats
        keys = set(self._cfg.stats_keys)
        st = self._ctl.stats
        self._io_tick += 1
        push_io = self._io_tick % 2 == 0

        if d.get("lhm_ok"):
            self._status_dot.setStyleSheet(f"color: {theme.OK};")
            self._status_dot.setToolTip("Sensores LHM ativos")
        else:
            self._status_dot.setStyleSheet(f"color: {theme.FAINT};")
            self._status_dot.setToolTip("Carregando sensores...")

        cpu_pct = d.get("cpu_pct", 0.0)
        self.cpu.set_bar(cpu_pct, theme.load_color(cpu_pct))
        self.cpu.push_spark(cpu_pct)
        self.cpu.set("pct", f"{cpu_pct:.1f}%")
        mhz = d.get("cpu_mhz")
        self.cpu.set("freq", f"{mhz / 1000:.2f} GHz" if mhz else "—")
        ct = d.get("cpu_temp")
        self.cpu.set("temp", f"{ct:.0f} °C" if ct is not None else "—", theme.temp_color(ct))
        cw = d.get("cpu_watts")
        self.cpu.set("watts", f"{cw:.1f} W" if cw is not None else "—",
                     theme.watt_color(cw, 65, 95))
        cf = d.get("cpu_fan")
        self.cpu.set("fan", f"{cf} RPM" if cf else "—")
        self.cpu.set_hint(f"{ct:.0f}°" if ct is not None else "")

        ram_pct = d.get("ram_pct", 0.0)
        self.ram.set_bar(ram_pct, theme.load_color(ram_pct))
        self.ram.push_spark(ram_pct)
        self.ram.set("used", f"{d['ram_used']:.1f} / {d['ram_total']:.0f} GB")
        self.ram.set("avail", f"{d['ram_avail']:.1f} GB livre")
        rf = d.get("ram_freq")
        self.ram.set("freq", f"{rf} MHz" if rf else "—")
        self.ram.set_hint(f"{ram_pct:.0f}%")

        g = d.get("gpu")
        if g:
            usage = g.get("usage", 0)
            self.gpu.set_bar(usage, theme.load_color(usage))
            self.gpu.push_spark(usage)
            self.gpu.set("pct", f"{usage}%")
            gt = g.get("temp")
            self.gpu.set("temp", f"{gt} °C" if gt else "—", theme.temp_color(gt))
            self.gpu.set("fan", _fan_text(g))
            gw = g.get("watts")
            est = g.get("watts_estimated", False)
            self.gpu.set("watts",
                         (f"~{gw:.0f} W" if est else f"{gw:.0f} W") if gw is not None else "—",
                         theme.watt_color(gw, 80, 130))
            self.gpu.set("freq", f"{g.get('freq', 0)} MHz")
            vu, vt = g.get("vram_used", 0), max(g.get("vram_total", 1), 1)
            self.gpu.set("vram", f"{vu / 1024:.1f} / {vt / 1024:.1f} GB")
            self.gpu.set_hint(g.get("name", "").replace("NVIDIA GeForce ", ""))
        else:
            for k in ("pct", "temp", "fan", "watts", "freq", "vram"):
                self.gpu.set(k, "—")
            self.gpu.set_hint("não detectada")

        disk_pct = d.get("disk_pct", 0.0)
        self.disk.set_bar(disk_pct, theme.load_color(disk_pct))
        if push_io:
            self.disk.push_spark(d["disk_r"] + d["disk_w"])
        self.disk.set_hint(f"{disk_pct:.0f}%")
        self.disk.set("used", f"{d['disk_used']:.0f} / {d['disk_total']:.0f} GB")
        nt = d.get("nvme_temp")
        self.disk.set("temp", f"{nt} °C" if nt is not None else "—", theme.temp_color(nt))
        self.disk.set("read", _fmt_bytes(d["disk_r"]))
        self.disk.set("write", _fmt_bytes(d["disk_w"]))

        if push_io:
            self.net.push_spark(d["net_dl"] + d["net_ul"])
        self.net.set("dl", _fmt_bytes(d["net_dl"]))
        self.net.set("ul", _fmt_bytes(d["net_ul"]))
        ping = d.get("ping_ms")
        self.net.set("ping", f"{ping} ms" if ping is not None else "—", theme.ping_color(ping))
        loss = d.get("packet_loss")
        self.net.set("loss", f"{loss}%" if loss is not None else "—", theme.loss_color(loss))

        self._uptime.setText(f"Uptime  {d.get('uptime', '—')}")

        for sk, sec, rk, dec, unit, fn in self._stats_map():
            st.update(sk, fn(d))
            self.__dict__[sec].set_stat(rk, st.fmt(sk, dec, " " + unit) if (show and sk in keys) else "")

    def _stats_map(self):
        return [
            ("cpu_pct", "cpu", "pct", 1, "%", lambda d: d.get("cpu_pct")),
            ("cpu_temp", "cpu", "temp", 0, "°C", lambda d: d.get("cpu_temp")),
            ("cpu_watts", "cpu", "watts", 1, "W", lambda d: d.get("cpu_watts")),
            ("ram_pct", "ram", "used", 1, "%", lambda d: d.get("ram_pct")),
            ("gpu_pct", "gpu", "pct", 0, "%", lambda d: (d.get("gpu") or {}).get("usage")),
            ("gpu_temp", "gpu", "temp", 0, "°C", lambda d: (d.get("gpu") or {}).get("temp")),
            ("gpu_watts", "gpu", "watts", 0, "W", lambda d: (d.get("gpu") or {}).get("watts")),
            ("nvme_temp", "disk", "temp", 0, "°C", lambda d: d.get("nvme_temp")),
            ("ping_ms", "net", "ping", 0, "ms", lambda d: d.get("ping_ms")),
        ]

    def update_fps(self) -> None:
        by_pid = self._ctl.fps.snapshot()
        fg = win.foreground_pid()
        chosen = fpspick.pick(by_pid, fg, self._cfg.fps_pin)
        metrics = set(self._cfg.fps_metrics)
        self._sync_fps_layout(metrics)

        if chosen:
            inst = chosen[4]
            avg = chosen[3] if self._cfg.fps_source == "display" else chosen[0]
            low = chosen[5]
            low01 = chosen[6]
            values = {"inst": inst, "avg": avg, "1low": low, "01low": low01}
            for key, val in values.items():
                self._fps_vals[key].setText(str(val))
                self._fps_vals[key].setStyleSheet(f"color: {theme.fps_color(val)};")
            game = chosen[1] or "Auto"
            self._game.setText(f"{game} ▾")
            self._ft.setText(f"{1000 / inst:.1f} ms" if inst > 0 else "—")
            self._ctl.stats.update("fps", inst)
            pid = next((p for p, v in by_pid.items() if v is chosen), None)
            if self._graph_visible and pid is not None:
                self._graph.set_buffer(self._ctl.fps.graph_buffer(pid))
        else:
            for val in self._fps_vals.values():
                val.setText("—")
                val.setStyleSheet(f"color: {theme.MUTE};")
            pin = self._cfg.fps_pin
            self._game.setText(f"{pin} ▾" if pin else "Auto ▾")
            self._ft.setText("")
            if self._graph_visible:
                self._graph.set_buffer([])

    def _sync_fps_layout(self, metrics: set) -> None:
        want = {k: (k in metrics) for k, _ in _FPS_COLS}
        graph = "graph" in metrics
        ft = "frametime" in metrics
        state = (tuple(want.items()), graph, ft)
        if state == self._fps_layout_state:
            return
        self._fps_layout_state = state
        for key, _ in _FPS_COLS:
            self._fps_cols[key].setVisible(want[key])
        self._graph.setVisible(graph)
        self._graph_visible = graph
        self._ft.setVisible(ft)
        self.adjustSize()
        self.place()

    # ── interacao ───────────────────────────────────────────────────────────--
    def _open_game_picker(self) -> None:
        menu = QMenu(self)
        menu.addAction("Auto (janela ativa)", lambda: self._pick_game(""))
        by_pid = self._ctl.fps.snapshot()
        seen: dict[str, int] = {}
        for _, tup in by_pid.items():
            app, fps = tup[1], tup[0]
            if app not in seen or fps > seen[app]:
                seen[app] = fps
        if seen:
            menu.addSeparator()
            for app, fps in sorted(seen.items(), key=lambda x: -x[1]):
                menu.addAction(f"{app}   {fps} fps", lambda a=app: self._pick_game(a))
        menu.exec(self._game.mapToGlobal(QPoint(0, self._game.height() + 2)))

    def _pick_game(self, name: str) -> None:
        self._cfg.fps_pin = name
        self._ctl.save_settings()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and not self._cfg.locked:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_pos is not None and not self._cfg.locked:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, _e) -> None:
        self._drag_pos = None

    def _build_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Configurações", lambda: self._ctl.open_settings(0))
        m.addAction("FPS", lambda: self._ctl.open_settings(1))
        m.addAction("Estatísticas", lambda: self._ctl.open_settings(2))
        m.addSeparator()
        top = QAction("Sempre no topo", self, checkable=True)
        top.setChecked(self._cfg.always_on_top)
        top.triggered.connect(lambda v: self._ctl.set_always_on_top(v))
        m.addAction(top)
        lock = QAction("Travar posição", self, checkable=True)
        lock.setChecked(self._cfg.locked)
        lock.triggered.connect(lambda v: self._ctl.set_locked(v))
        m.addAction(lock)
        overlay = QAction("Modo Jogo (overlay)", self, checkable=True)
        overlay.setChecked(self._ctl.overlay_active())
        overlay.triggered.connect(lambda _v: self._ctl.toggle_overlay())
        m.addAction(overlay)
        m.addSeparator()
        m.addAction("Zerar estatísticas", self._ctl.clear_stats)
        m.addAction("Fechar", self._ctl.quit)
        return m

    def contextMenuEvent(self, e) -> None:
        self._build_menu().exec(e.globalPos())

    def _open_menu(self) -> None:
        self._build_menu().exec(
            self._btn_cfg.mapToGlobal(QPoint(0, self._btn_cfg.height() + 2)))


def _fan_text(g: dict) -> str:
    rpm, pct = g.get("fan_rpm"), g.get("fan_pct")
    if rpm is not None and pct is not None:
        return f"{rpm} RPM ({pct}%)"
    if rpm is not None:
        return f"{rpm} RPM"
    if pct is not None:
        return f"{pct}%"
    return "—"
