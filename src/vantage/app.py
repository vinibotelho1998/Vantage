"""Controlador da aplicacao: sensores, timers, janelas e ciclo de vida.

A UI nunca fala com um sensor diretamente: tudo passa por aqui, o que mantem as
telas burras (e baratas) e concentra as regras num lugar so.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from functools import partial
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import log, paths, theme
from .config import Settings
from .core import export
from .core import frames as fr
from .core.series import Accumulator, History
from .core.session import GameSession
from .platform import autostart
if os.name == "nt":
    from .platform import win, displays as dsp
    from .platform.gamepad import GamepadMouse
    from .platform.hotkeys import MOD_ALT, MOD_CONTROL, HotkeyManager
else:
    from .platform import linux_desktop as dsp
    from .sensors.linux import LinuxSensors
from .sensors import net as netmod
from .sensors import procs
from .sensors.collector import Collector
from .sensors.fps import FpsEngine
from .sensors.gpu import GpuReader
from .sensors.lhm import LhmReader
from .sensors.net import PingMonitor
from .sensors.peer import PeerFinder
from .sensors.procs import ProcessMonitor
from .ui import style
from .ui.main_window import MainWindow
from .ui.overlay import GameOverlay
from .ui.settings import SettingsDialog
from .ui.tray import Tray

_log = log.get("app")

FAST_TICK_MS = 120
FOCUS_TICK_MS = 500
GAME_EXIT_GRACE_S = 5.0
"""Confirma que o jogo fechou mesmo antes de mexer nas telas."""
ONLINE_GRACE_S = 25.0
"""Tempo de busca antes de dar a partida como local."""
SERVER_SCAN_TICKS = 5
"""Ticks de sessao (1 s cada) entre buscas do servidor do jogo."""
BENCH_HISTORY_MAX = 40
SESSION_HISTORY_MAX = 60
BACKGROUND_INTERVAL_S = 3.0
"""Passo de coleta sem ninguem olhando."""
MIN_SESSION_FRAMES = 3000
"""Menos que isso e' carregamento, nao partida."""

# metricas do snapshot que alimentam graficos e acumulador da sessao
_SERIES = (
    ("cpu_pct", lambda d, g: d.get("cpu_pct")),
    ("cpu_temp", lambda d, g: d.get("cpu_temp")),
    ("cpu_watts", lambda d, g: d.get("cpu_watts")),
    ("cpu_mhz", lambda d, g: d.get("cpu_mhz")),
    ("gpu_pct", lambda d, g: g.get("usage")),
    ("gpu_temp", lambda d, g: g.get("temp")),
    ("gpu_watts", lambda d, g: g.get("watts")),
    ("gpu_mhz", lambda d, g: g.get("freq")),
    ("gpu_mem_mhz", lambda d, g: g.get("mem_freq")),
    ("vram_pct", lambda d, g: g.get("vram_pct")),
    ("ram_pct", lambda d, g: d.get("ram_pct")),
    ("swap_pct", lambda d, g: d.get("swap_pct")),
    ("disk_r", lambda d, g: d.get("disk_r")),
    ("disk_w", lambda d, g: d.get("disk_w")),
    ("net_dl", lambda d, g: d.get("net_dl")),
    ("net_ul", lambda d, g: d.get("net_ul")),
    ("ping_ms", lambda d, g: d.get("ping_ms")),
    ("packet_loss", lambda d, g: d.get("packet_loss")),
)

_SYSTEM_KEYS = (("cpu", "cpu_pct"), ("cpu_temp", "cpu_temp"), ("cpu_watts", "cpu_watts"),
                ("gpu", "gpu_pct"), ("gpu_temp", "gpu_temp"), ("gpu_watts", "gpu_watts"),
                ("ram", "ram_pct"), ("vram", "vram_pct"))


class App:
    def __init__(self, qt: QApplication) -> None:
        self.qt = qt
        self.settings = Settings.load()
        theme.set_scale(self.settings.ui_scale)

        self.stats = Accumulator()
        self.history = History(self._history_depth())
        self.lhm = LhmReader() if os.name == "nt" else LinuxSensors()
        self.gpu = GpuReader()
        self.ping = PingMonitor(self.settings.ping_host, self.settings.ping_port)
        self.fps = FpsEngine(self.settings.fps_window, self.settings.fps_now_window)
        self.procs = ProcessMonitor()
        self.peers = PeerFinder()
        self.collector = Collector(self.lhm, self.gpu, self.ping,
                                   self.settings.update_interval)
        self.gamepad = GamepadMouse(self.settings, qt) if os.name == "nt" else None
        if self.gamepad:
            self.gamepad.reset_pedido.connect(self._reset_pelo_controle)

        self._data: dict = {}
        self._stream = None
        self._fg_pid = 0
        self._fg_fullscreen = False
        self._overlay: GameOverlay | None = None
        self._dialog: SettingsDialog | None = None
        self._hotkeys: HotkeyManager | None = None
        self._t_sys: QTimer | None = None
        self._display_boot: list[dict] = []
        self._displays_seen: frozenset[str] | None = None
        """Monitores conectados no ultimo tique; ver _watch_displays."""
        self._displays_pending: frozenset[str] | None = None
        """Conjunto novo aguardando confirmacao no tique seguinte."""
        self._session: GameSession | None = None
        self._session_restore: list[dict] | None = None
        self._session_primary = ""
        """monitor_id da primaria de antes, quando so' a primaria mudou."""
        self._session_off = ""
        """monitor_id da tela que ligamos para o jogo e voltara a desligar."""
        self._session_name = ""
        self._session_bench_pid = 0
        """Processo que o gravador da partida esta' seguindo agora."""
        self._session_bench = False
        """O atalho aberto pediu para gravar a partida."""
        self._session_priority = ""
        self._session_env = Accumulator()
        """Sistema durante a partida gravada; ver _close_session_bench."""
        self.session_history: list[dict] = _load_session_history()
        self._game_pid = 0
        self._game_name = ""
        self._game_seen_at = 0.0
        self._server_countdown = 1
        self._alerted: dict[str, bool] = {}
        self._tray_hinted = False
        self._load_now = ""
        """Perfil de esforco em uso; ver _apply_load_profile."""
        self._bigpicture = None
        self._bp_off = ""
        """Tela que o Big Picture acendeu e vai apagar ao sair."""
        self._bp_mouse_antes = False
        self._bp_back_desde = 0.0
        self._bp_back_pronto = False
        """So' arma depois de ver o Back solto uma vez; ver _vigiar_atalho_do_sofa."""
        self._bp_voltar = False
        self._session_off_pendente = ""
        """Tela acesa pelo Big Picture, a caminho de virar responsabilidade da sessao."""

        self._bench_active = False
        self._bench_started = 0.0
        self._bench_total = 0.0
        self._bench_game = ""
        self._bench_pid: int | None = None
        self._bench_env = Accumulator()
        self._bench_result: dict | None = None
        self._bench_rev = 0
        self.bench_history: list[dict] = _load_bench_history()
        # O ultimo resultado volta com o app: fechar a janela nao pode apagar o
        # benchmark que a pessoa acabou de rodar.
        self._bench_result = _load_last_bench()

        qt.setQuitOnLastWindowClosed(False)
        qt.setPalette(style.build_palette(self.settings.accent))
        qt.setStyleSheet(style.build_qss(self.settings.accent))
        self.window = MainWindow(self)
        self.tray = Tray(self)

    def run(self) -> int:
        self.boot()
        return self.qt.exec()

    def boot(self) -> None:
        # Fotografia das telas antes de qualquer coisa: e' para onde tudo volta
        # quando o app fecha, para nao deixar a maquina num arranjo de TV.
        self._display_boot = dsp.snapshot() if os.name == "nt" else []
        self.lhm.mem_rail = self.settings.mem_volt_rail
        self.lhm.start()
        self.gpu.start_smi()
        self.ping.start()
        self.fps.start()
        self.procs.start()
        self.peers.start()
        self.collector.start()

        self.window.restore_geometry()
        from PySide6.QtWidgets import QSystemTrayIcon
        if not self.settings.start_minimized or not QSystemTrayIcon.isSystemTrayAvailable():
            self.window.show()
        self._apply_overlay()
        # Antes dos timers: se a maquina abriu com a primaria na tela errada
        # (TV ligada por ultimo, por exemplo), a janela ja' nasce no lugar certo.
        nome = self._enforce_display_defaults() if os.name == "nt" and self.settings.display_apply_on_start else ""
        if nome:
            self.notify("Vantage", f"{nome} de volta como tela principal.")
        self._init_timers()
        self._init_hotkeys()
        # A escuta do controle fica sempre de pe'. Ela nao mexe em nada sozinha:
        # o modo mouse so' assume quando o usuario aperta Back + Start no controle.
        if self.gamepad:
            self.gamepad.start()
        autostart.set_enabled(self.settings.autostart)

    def _init_timers(self) -> None:
        self._t_sys = QTimer(self.qt)
        self._t_sys.timeout.connect(self._tick_system)
        self._t_sys.start(int(self.settings.update_interval * 1000))

        self._t_fast = QTimer(self.qt)
        self._t_fast.timeout.connect(self._tick_fast)
        self._t_fast.start(FAST_TICK_MS)

        self._t_focus = QTimer(self.qt)
        self._t_focus.timeout.connect(self._tick_focus)
        self._t_focus.start(FOCUS_TICK_MS)

        self._t_clock = QTimer(self.qt)
        self._t_clock.timeout.connect(self.window.tick_clock)
        self._t_clock.start(1000)

        # Varredura de processo custa caro, mas so' roda com sessao aberta, e a
        # espera depois do jogo fechar e' o que o usuario sente, entao 1 s.
        self._t_session = QTimer(self.qt)
        self._t_session.timeout.connect(self._tick_session)
        self._t_session.start(1000)

    def _init_hotkeys(self) -> None:
        if os.name != "nt":
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QShortcut, QKeySequence
            for sequence, action in (("Ctrl+Alt+R", self._hotkey_reset),
                                     ("Ctrl+Alt+O", self.toggle_overlay),
                                     ("Ctrl+Alt+B", self._hotkey_benchmark),
                                     ("Ctrl+Alt+G", self.big_picture_toggle)):
                shortcut = QShortcut(QKeySequence(sequence), self.window)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
                shortcut.activated.connect(action)
            return
        self._hotkeys = HotkeyManager()
        self.qt.installNativeEventFilter(self._hotkeys)
        mods = MOD_CONTROL | MOD_ALT
        bindings = ((0x52, self._hotkey_reset, "Ctrl+Alt+R"),
                    (0x4F, self.toggle_overlay, "Ctrl+Alt+O"),
                    (0x42, self._hotkey_benchmark, "Ctrl+Alt+B"),
                    (0x47, self.big_picture_toggle, "Ctrl+Alt+G"))
        for vk, callback, name in bindings:
            if not self._hotkeys.register(mods, vk, callback):
                _log.warning("nao foi possivel registrar %s (em uso por outro app?)", name)

        # Ctrl+Alt+1 ate 9 aplicam os perfis de tela na ordem em que aparecem.
        # Sao globais de proposito: no perfil de TV os monitores da mesa apagam, e
        # o atalho e' o unico caminho de volta sem enxergar a tela.
        for slot in range(9):
            vk = 0x31 + slot
            if not self._hotkeys.register(mods, vk, partial(self._hotkey_profile, slot)):
                _log.warning("nao foi possivel registrar Ctrl+Alt+%d", slot + 1)

    def _hotkey_profile(self, slot: int) -> None:
        try:
            profile = self.settings.display_profiles[slot]
        except IndexError:
            return
        ok, err = dsp.apply_profile(profile["entries"], profile.get("topology", ""))
        if ok:
            _log.info("perfil de tela '%s' aplicado", profile["name"])
        else:
            _log.warning("perfil de tela '%s' falhou: %s", profile["name"], err)
        view = self.window.views.get("displays")
        if view is not None:
            view.reload()

    def quit(self) -> None:
        self.window.store_geometry()
        self.settings.save()
        _save_bench_history(self.bench_history)
        if self._hotkeys is not None:
            self._hotkeys.unregister_all()
        if self.gamepad:
            self.gamepad.stop()
        self.peers.stop()
        try:
            self._restore_displays()
        except Exception:
            # Falhar aqui nao pode travar o resto: e' logo abaixo que o
            # PresentMon recebe o pedido de sair. Sem isso o app ficava
            # pendurado, e mata-lo a forca deixava a sessao ETW orfa.
            _log.exception("falha devolvendo as telas ao fechar")
        self.collector.stop()
        self.procs.stop()
        self.ping.stop()
        self.gpu.stop()
        self.fps.stop()
        if self._overlay is not None:
            self._overlay.close()
        self.tray.hide()
        self.lhm.close()
        self.qt.quit()

    def play_item(self, item: dict) -> tuple[bool, str]:
        """Prepara as telas, abre o jogo e agenda a volta para quando ele fechar."""
        antes = dsp.snapshot()
        antes_primaria = next((d["monitor_id"] for d in antes if d.get("primary")), "")
        trocou, msg = self._apply_target(item.get("target", ""))
        so_primaria = trocou and item.get("target", "").startswith("primary:")

        session = GameSession(item["path"], item.get("args", ""))
        started, err = session.start()
        if not started:
            if trocou and item.get("restore", True):
                if so_primaria and antes_primaria:
                    self._restore_primary(antes_primaria, self._session_off)
                else:
                    dsp.apply_profile(antes)
            self._session_off = ""
            return False, f"não consegui abrir: {err}"

        self._session = session
        # So' promete devolver as telas se elas realmente mudaram por causa daqui.
        # Trocar so' a primaria se desfaz trocando so' a primaria de volta: mandar
        # o perfil inteiro apaga as tres telas por varios segundos sem precisar.
        devolver = trocou and item.get("restore", True)
        self._session_primary = antes_primaria if (devolver and so_primaria) else ""
        self._session_restore = antes if (devolver and not so_primaria) else None
        if not devolver:
            self._session_off = ""
        self._session_name = item.get("name") or Path(item["path"]).stem
        # Grava a partida inteira desde ja', quando o atalho pede. O pid do jogo
        # ainda nao existe: quem descobre e' o proprio motor de FPS, entao o
        # gravador comeca solto e passa a seguir o processo assim que ele aparece.
        self._session_bench = os.name == "nt" and bool(item.get("bench", True))
        self._bp_voltar = bool(item.get("voltar_bp", False))
        if self._session_bench:
            self._session_env = Accumulator()
            self.fps.session_start(0)
        self._session_bench_pid = 0
        self._session_priority = str(item.get("priority", ""))
        aviso = f"{self._session_name} abrindo"
        return True, f"{aviso}: {msg}" if msg else aviso

    def _apply_target(self, target: str) -> tuple[bool, str]:
        """Traduz o alvo do atalho numa mudanca de tela. Sem alvo, nao mexe.

        Falhar aqui nunca cancela o jogo: quem clicou em Jogar quer jogar. O que
        deu errado vira aviso, e o primeiro item do retorno diz se alguma coisa
        mudou de fato; so' isso e' que gera promessa de devolver depois.
        """
        self._session_off = ""
        if os.name != "nt":
            return False, ""
        if not target:
            return False, ""
        tipo, _, valor = target.partition(":")
        if tipo == "primary":
            alvo = next((d for d in dsp.list_displays(with_modes=False)
                         if d.monitor_id == valor), None)
            if alvo is None:
                return False, "a tela desse atalho não está conectada, abri assim mesmo"
            aviso = ""
            if not alvo.active:
                # A TV vive desligada e so' acorda para jogar. Ligar aqui e' o
                # que permite manter esse arranjo como o normal da casa, em vez
                # de deixar uma tela preta ocupando area de trabalho o dia todo.
                ok, err = dsp.set_enabled(alvo.device, True)
                if not ok:
                    return False, f"não consegui ligar a {alvo.name}: {err}"
                self._session_off = alvo.monitor_id
                aviso = f"{alvo.name} ligada e "
            ok, err = dsp.set_primary(alvo.device)
            if not ok and self._session_off:
                dsp.set_enabled(alvo.device, False)
                self._session_off = ""
            return (True, f"{aviso}virou a primária") if ok else (False, err)
        if tipo == "profile":
            profile = next((p for p in self.settings.display_profiles
                            if p["name"] == valor), None)
            if profile is None:
                return False, f"perfil '{valor}' não existe mais, abri assim mesmo"
            ok, err = dsp.apply_profile(profile["entries"], profile.get("topology", ""))
            return (True, f"perfil '{valor}' aplicado") if ok else (False, err)
        return False, ""

    def _tick_session(self) -> None:
        """Vigia o jogo: o que abrimos e o que o usuario abriu por fora."""
        if os.name == "nt":
            self._watch_displays()
        self._watch_any_game()
        self._follow_game_server()
        session = self._session
        if session is None:
            return
        self._adopt_game_process(session)
        if session.running():
            return

        self._session = None
        self._close_session_bench()
        if self._bp_voltar and (os.name == "nt" or session.ever_started):
            # Voltou do jogo: a grade reaparece na TV, e nao a janela de mesa;
            # quem esta' no sofa nao alcanca o teclado para reabrir. So' acontece
            # nos atalhos marcados para isso; quem abre o jogo da mesa espera a
            # janela normal de volta.
            self._bp_voltar = False
            QTimer.singleShot(1200, self.big_picture_abrir)
        restore = self._session_restore
        primaria = self._session_primary
        desligar = self._session_off
        self._session_restore = None
        self._session_primary = ""
        self._session_off = ""
        if restore is None and not primaria:
            return
        if not session.ever_started:
            # Nunca reconhecemos o jogo. Mexer nas telas agora seria pior que nao
            # fazer nada: se ele estiver rodando, a mudanca cai em cima do jogo.
            _log.warning("nao consegui acompanhar o processo de %s; telas ficam como estao",
                         self._session_name)
            self.notify("Vantage",
                        f"não consegui acompanhar {self._session_name}. "
                        "As telas ficam como estão; use a aba Telas quando terminar.")
            return
        if primaria:
            self._restore_primary(primaria, desligar)
            return
        restore = self._normal_layout() or restore
        try:
            if not _same_layout(restore, dsp.snapshot()):
                dsp.apply_profile(restore)
                self.notify("Vantage", f"{self._session_name} fechou: telas de volta")
        except Exception:
            _log.exception("falha devolvendo as telas depois do jogo")

    def _watch_displays(self) -> None:
        """Reimpoe o arranjo padrao quando um monitor e' conectado.

        O Windows guarda, para cada conjunto de monitores, a ultima topologia
        usada com aquele conjunto. Como a ultima vez que a TV esteve junto foi
        num perfil que apaga os monitores de mesa, plugar a TV de volta apagava
        os dois, sem o app ter feito nada. Aqui a gente devolve o padrao assim
        que percebe a mudanca.

        So' reagimos a monitor entrando ou saindo, nunca a tela sendo ligada ou
        promovida: isso o proprio app faz o tempo todo, e reagir a isso viraria
        uma queda de braco com a troca que acabamos de pedir. Consultar as telas
        custa 0,6 ms, entao cabe no tique de um segundo sem pesar.
        """
        try:
            conectados = frozenset(d.monitor_id for d in dsp.list_displays(with_modes=False)
                                   if d.monitor_id)
        except Exception:
            return
        if self._displays_seen is None:
            self._displays_seen = conectados
            return
        if conectados == self._displays_seen:
            self._displays_pending = None
            return
        # Espera o conjunto se acomodar antes de agir. Aplicar um arranjo faz o
        # Windows soltar e reanexar caminhos por um instante; agir nesse piscar
        # desfazia a mudanca que o usuario tinha acabado de aplicar.
        if self._displays_pending != conectados:
            self._displays_pending = conectados
            return
        self._displays_seen = conectados
        self._displays_pending = None
        if self._session is not None:
            return
        _log.info("conjunto de telas mudou: %d conectadas", len(conectados))
        try:
            # Aqui NAO se reimpoe perfil nenhum. Perfil mexe em tudo (topologia,
            # modos, posicoes) e reaplica-lo por causa de um monitor plugado
            # apagava o arranjo que a pessoa tinha acabado de montar na mao. O
            # que vale sao as duas escolhas explicitas: quem manda e quem apaga.
            self._enforce_display_defaults()
        finally:
            # A aba Telas so' se redesenhava ao ser aberta. Plugar a TV com ela
            # ja' na frente nao mostrava nada; a tela nova simplesmente nao
            # aparecia. Redesenhar aqui vale ate' quando nao ha' perfil padrao:
            # a lista tem de refletir o que esta' ligado na maquina, sempre.
            self.window.reload_displays()

    def _enforce_display_defaults(self) -> str:
        """Poe as telas no arranjo escolhido como o normal da casa.

        Quatro passos, e a ordem nao e' negociavel:

        1. acende o que deveria estar aceso, inclusive a tela que vai mandar,
           porque o Windows nao promove tela apagada;
        2. entrega a primaria a quem foi escolhido;
        3. apaga o que deveria estar apagado, agora que ela nao manda mais;
        4. devolve cada tela acesa ao modo nativo.

        O passo 4 existe porque o Windows chuta um modo conservador ao reanexar
        uma tela; e' o que fazia a maquina abrir "com resolucao doida" depois
        de um jogo ter mexido nas telas, ou depois de um reinicio.

        So' roda quando um monitor entra ou sai, e na abertura do app. Nao e'
        um vigia constante de proposito: ligar a TV na mao pela aba Telas tem
        de continuar funcionando sem o app apaga-la um segundo depois.
        """
        if self._session is not None:
            return self._enforce_primary()

        apagar = set(self.settings.display_off_by_default)
        for d in dsp.list_displays(with_modes=False):
            if d.active or d.monitor_id in apagar or not d.monitor_id:
                continue
            ok, err = dsp.set_enabled(d.device, True)
            _log.info("%s acesa por padrao (%s)", d.name, "ok" if ok else err)

        nome = self._enforce_primary()

        apagou = False
        for d in dsp.list_displays(with_modes=False):
            if d.monitor_id not in apagar or not d.active or d.primary:
                continue
            ok, err = dsp.set_enabled(d.device, False)
            apagou = apagou or ok
            _log.info("%s apagada por padrao (%s)", d.name, "ok" if ok else err)

        if apagou:
            # Apagar uma tela faz o Windows reatribuir a primaria por conta
            # propria, ignorando a que acabamos de definir. Medido: pedimos a
            # ULTRAWIDE, a TV foi apagada em seguida, e a primaria terminou na
            # ULTRAGEAR. Confirmar depois e' o que fecha o arranjo.
            nome = self._enforce_primary() or nome

        self._enforce_native_modes()
        return nome

    def _tem_arranjo_padrao(self) -> bool:
        """Ha' um arranjo padrao escolhido, ou o app nao sabe o que impor?"""
        return bool(self.settings.display_primary_default
                    or self.settings.display_off_by_default)

    def _enforce_native_modes(self) -> None:
        """Devolve cada tela acesa a' resolucao e taxa nativas do painel.

        O Windows escolhe um modo conservador ao reanexar uma tela: numa TV 4K
        isso vira 4096x2160 a 60 Hz, ou 3840x2160 a 120 em vez de 144. Quem
        escolheu outro modo de proposito na aba Telas percebe, porque isso so'
        acontece na abertura e quando um monitor entra ou sai, nao a cada
        segundo.
        """
        if not self.settings.display_force_native:
            return
        for d in dsp.list_displays():
            if not d.active or not d.mode:
                continue
            melhor = dsp.best_mode(d.device)
            if melhor is None or melhor.as_key() == d.mode.as_key():
                continue
            ok, err = dsp.set_mode(d.device, melhor)
            _log.info("%s -> %s (%s)", d.name, melhor.label, "ok" if ok else err)

    def _enforce_primary(self) -> str:
        """Devolve o comando para a tela escolhida como principal da casa.

        Conectar a TV entrega a primaria a ela: o Windows promove sozinho a
        tela que acabou de chegar. Como quase todo o uso do PC acontece no
        monitor da mesa, a barra de tarefas e as janelas novas iam parar numa
        tela que muitas vezes nem esta' ligada.

        Sai de fininho quando ha' jogo aberto: nesse caso a primaria foi
        trocada de proposito, e por nos.
        """
        alvo_id = self.settings.display_primary_default
        if not alvo_id or self._session is not None:
            return ""
        alvo = next((d for d in dsp.list_displays(with_modes=False)
                     if d.monitor_id == alvo_id and d.active), None)
        if alvo is None or alvo.primary:
            return ""
        ok, err = dsp.set_primary(alvo.device)
        if not ok:
            _log.warning("nao consegui devolver a principal para %s: %s", alvo.name, err)
            return ""
        _log.info("principal devolvida para %s", alvo.name)
        return alvo.name

    def _apply_launch_priority(self, pid: int) -> None:
        """Promove o jogo assim que descobrimos qual processo e' ele.

        Nao da' para fazer isso na hora de abrir: atalho de loja sobe o cliente,
        e o jogo aparece depois com outro nome. Quem sabe a resposta e' o motor
        de FPS, que ve' quem esta' desenhando, entao a promocao espera por ele.
        """
        chave = self._session_priority
        if not chave:
            return
        self._session_priority = ""      # uma vez por sessao, nao a cada tique
        # O nome tem de ser o do EXECUTAVEL, e nao o apelido do atalho: a funcao
        # confere nome contra pid antes de agir; guarda contra o Windows
        # reciclar numero, e "CrimsonDesert" nunca casa com "CrimsonDesert.exe".
        # O atalho chamado "Forza" entao falhava calado, dizendo que o jogo ja'
        # nao estava em execucao bem no instante em que ele acabara de abrir.
        nome = _process_name(pid) or self._session_name or "jogo"
        ok, msg = procs.mudar_prioridade(pid, nome, chave)
        _log.info("prioridade do jogo: %s", msg)
        if not ok:
            self.notify("Vantage", msg)

    def _close_session_bench(self) -> None:
        """Fecha a gravacao da partida e guarda o resumo.

        Sessao curta demais nao vira registro: alguns segundos de jogo dizem
        mais sobre o carregamento do que sobre o desempenho, e encheriam a
        lista de linhas inuteis.
        """
        self._session_bench_pid = 0
        if not self._session_bench:
            return
        self._session_bench = False
        resumo = self.fps.session_stop()
        if not resumo or resumo.get("frames", 0) < MIN_SESSION_FRAMES:
            return
        registro = {
            "quando": datetime.now().strftime("%d/%m %H:%M"),
            "game": self._session_name or resumo.get("game", "jogo"),
            **resumo,
        }
        # A media sai do acumulador da propria partida. O relatorio diz "media do
        # sistema durante a partida", e o numero vinha do acumulador do app
        # inteiro: horas de area de trabalho parada entravam na media do jogo.
        for chave, _fonte in _SYSTEM_KEYS:
            agg = self._session_env.get(chave)
            if agg:
                registro[chave] = round(agg[1], 1)
        self.session_history.append(registro)
        del self.session_history[:-SESSION_HISTORY_MAX]
        _save_session_history(self.session_history)
        minutos = registro.get("duracao_s", 0) / 60.0
        self.notify("Vantage",
                    f"{registro['game']}: {minutos:.0f} min, "
                    f"{registro.get('fps_avg', 0):.0f} fps médio, "
                    f"1% low {registro.get('low_1', 0):.0f}")
        self.show_view("benchmark")

    def save_session_history(self) -> None:
        """Grava o historico como esta' agora.

        Existe para a aba Benchmark poder excluir partidas: ela mexe na lista em
        memoria, e sem um jeito de mandar gravar a exclusao voltaria sozinha na
        proxima abertura do app.
        """
        _save_session_history(self.session_history)

    def big_picture_toggle(self) -> None:
        if self._bigpicture is not None and self._bigpicture.isVisible():
            self._big_picture_fechar()
        else:
            self.big_picture_abrir()

    def big_picture_abrir(self) -> None:
        """Abre a grade de jogos na tela de jogar, acendendo-a se preciso.

        Nao troca a primaria de proposito. Quem manda continua sendo assunto do
        atalho, dentro de play_item; dois donos para a mesma regra viraria
        briga com a principal padrao da casa.
        """
        if os.name != "nt":
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            if not QDesktopServices.openUrl(QUrl("steam://open/bigpicture")):
                self.notify("Steam", "Instale ou abra o Steam para usar o Big Picture.")
            return
        from .ui.bigpicture import BigPicture

        if self._bigpicture is None:
            self._bigpicture = BigPicture(self)
            self._bigpicture.escolheu.connect(self._big_picture_jogar)
            self._bigpicture.fechou.connect(self._big_picture_fechar)

        tela = self._acender_tela_de_jogo()
        self.window.store_geometry()
        self.window.hide()
        self._bp_mouse_antes = self.gamepad.active
        self.gamepad.deactivate()
        self.gamepad.set_consumer(self._bigpicture.tratar_pad)
        self._bigpicture.abrir(tela)

    def _acender_tela_de_jogo(self):
        """Liga a tela onde o Big Picture deve abrir e devolve o QScreen dela.

        A escolha e' do usuario, como e' a de cada jogo: `bigpicture_target`
        guarda a tela, no mesmo formato do atalho. Antes a grade sempre nascia na
        tela marcada para ficar apagada; servia para a TV da sala, e nao servia
        para mais nada: quem quisesse a grade no monitor de cima nao tinha onde
        dizer isso.

        Vazio mantem o comportamento antigo, que continua sendo o certo para o
        caso mais comum: a grade acompanha a TV que so' acorda para jogar.
        """
        escolhido = str(getattr(self.settings, "bigpicture_target", "") or "")
        if escolhido.startswith("screen:"):
            alvo_id = escolhido.split(":", 1)[1]
        else:
            alvo_id = next(iter(self.settings.display_off_by_default), "")
        if not alvo_id:
            return None
        alvo = next((d for d in dsp.list_displays(with_modes=False)
                     if d.monitor_id == alvo_id), None)
        if alvo is None:
            return None
        if not alvo.active:
            ok, err = dsp.set_enabled(alvo.device, True)
            if not ok:
                _log.warning("nao consegui acender %s: %s", alvo.name, err)
                return None
            self._bp_off = alvo.monitor_id
        return _tela_qt(alvo.name)

    def _big_picture_jogar(self, item: dict) -> None:
        from .platform.gamepad import rumble

        # Do sofa, a vibracao e' a unica confirmacao de que o A pegou antes de a
        # TV trocar de modo e ficar preta por um instante.
        rumble(self.gamepad.slots, 20000, 20000)
        QTimer.singleShot(180, lambda: rumble(self.gamepad.slots, 0, 0))
        QTimer.singleShot(600, lambda: self._big_picture_disparar(item))

    def _big_picture_disparar(self, item: dict) -> None:
        # Passagem de bastao: quem acendeu a TV foi o Big Picture, mas quem vai
        # apaga-la e' o fim da sessao. Sem isso play_item veria a tela ja' acesa,
        # nao marcaria nada para desligar, e a TV ficaria ligada para sempre.
        if self._bp_off:
            self._session_off_pendente = self._bp_off
            self._bp_off = ""
        self._soltar_controle()
        ok, msg = self.play_item(item)
        if self._session_off_pendente:
            self._session_off = self._session_off_pendente
            self._session_off_pendente = ""
        if not ok:
            self.notify("Vantage", msg)
            self._bp_voltar = False
            self.big_picture_abrir()

    def _soltar_controle(self) -> None:
        """Esconde a grade E devolve o controle a quem estava usando.

        Esconder sem soltar deixava o consumidor preso: o Big Picture continuava
        engolindo o controle de dentro de uma janela invisivel, e quem estava
        com o modo mouse ligado via o cursor parar de responder sem entender por
        que.
        """
        self.gamepad.set_consumer(None)
        if self._bigpicture is not None:
            self._bigpicture.hide()

    def _big_picture_fechar(self) -> None:
        self.gamepad.set_consumer(None)
        if self._bp_mouse_antes:
            self.gamepad.toggle()
        if self._bigpicture is not None:
            self._bigpicture.hide()
        apagar, self._bp_off = self._bp_off, ""
        self._bp_voltar = False
        self._voltar_ao_padrao(apagar)
        self.window.show()
        self.window.raise_()

    def _reset_pelo_controle(self) -> None:
        """LT+RT+L3+R3 duas vezes: devolve as telas ao perfil padrao.

        Do sofa nao ha' teclado nem aba Telas ao alcance, e um jogo que fechou
        errado (ou um perfil aplicado por engano) deixava a casa num arranjo
        que so' dava para desfazer levantando. Este e' o caminho de volta.

        Reaproveita o mesmo caminho do fim do Big Picture: um so' lugar decide o
        que "padrao" significa, e ele sempre le' o perfil marcado como padrao
        agora, nao um nome gravado em algum lugar.
        """
        nome = self.settings.display_default_profile
        if not nome:
            self.notify("Vantage", "Nenhum perfil de telas está marcado como "
                                     "padrão; marque um na aba Telas.")
            return
        self._voltar_ao_padrao()
        self.notify("Vantage", f"Telas de volta ao perfil “{nome}”")

    def _voltar_ao_padrao(self, apagar: str = "") -> None:
        """Fecha a cascata do sofa: sair da grade devolve a mesa como ela era.

        O caminho de volta tem tres degraus (jogo, grade, mesa) e o ultimo
        faltava. Quando o jogo devolve para a grade (`voltar_bp`), quem acendeu a
        TV foi a sessao, e nao esta abertura do Big Picture: `_bp_off` ja' foi
        entregue para a sessao la' em `_big_picture_disparar`. Chegava aqui vazio,
        nao havia o que apagar, e a TV ficava ligada com a grade fechada.

        Por isso a volta e' pelo perfil padrao inteiro, e nao pela tela que esta
        abertura por acaso acendeu: o perfil ja' descreve o estado certo da mesa,
        TV apagada inclusive, venha a TV de onde vier.
        """
        alvo = self._normal_layout()
        if alvo is None:
            # Sem perfil padrao nao ha' estado conhecido para voltar. Resta
            # desfazer o que esta abertura fez, que e' o comportamento antigo.
            if apagar:
                tela = next((d for d in dsp.list_displays(with_modes=False)
                             if d.monitor_id == apagar and d.active and not d.primary),
                            None)
                if tela is not None:
                    dsp.set_enabled(tela.device, False)
            return
        try:
            # Abrir a grade da mesa e fechar sem jogar nao pode fazer as telas
            # piscarem por segundos a' toa.
            if _same_layout(alvo, dsp.snapshot()):
                return
            ok, err = dsp.apply_profile(alvo, self._normal_topology())
            if ok:
                _log.info("Big Picture fechou; telas de volta ao padrao")
            else:
                _log.warning("nao consegui voltar ao perfil padrao: %s", err)
        except Exception:
            _log.exception("falha devolvendo as telas ao fechar o Big Picture")

    def _restore_primary(self, monitor_id: str, desligar: str = "") -> None:
        """Devolve a primaria e, se ligamos alguma tela para o jogo, apaga de novo.

        Reaplicar o perfil inteiro para desfazer uma troca de primaria e' o que
        fazia as tres telas apagarem por varios segundos toda vez que um jogo
        fechava. Aqui sao uma ou duas chamadas, e as telas que nunca mudaram nem
        piscam.

        A ordem importa: a primaria volta antes de a TV se apagar, porque o
        Windows nao desliga a tela que esta' mandando.
        """
        telas = dsp.list_displays(with_modes=False)
        alvo = next((d for d in telas if d.monitor_id == monitor_id and d.active), None)
        if alvo is None:
            _log.warning("a tela primaria de antes (%s) nao esta mais ligada", monitor_id)
        elif alvo.primary:
            pass
        else:
            ok, err = dsp.set_primary(alvo.device)
            if ok:
                self.notify("Vantage",
                            f"{self._session_name} fechou: {alvo.name} de volta")
            else:
                _log.warning("nao consegui devolver a primaria: %s", err)
                return

        if not desligar:
            return
        tv = next((d for d in dsp.list_displays(with_modes=False)
                   if d.monitor_id == desligar and d.active), None)
        if tv is None:
            return
        ok, err = dsp.set_enabled(tv.device, False)
        if not ok:
            _log.warning("nao consegui desligar a %s de volta: %s", tv.name, err)

    def _follow_game_server(self) -> None:
        """Aponta o ping para o servidor do jogo em foco.

        Latencia de DNS publico nao diz nada sobre a partida. Enumerar conexoes
        de outro processo e' caro, entao so' de poucos em poucos segundos.
        """
        self._server_countdown -= 1
        if self._server_countdown > 0:
            return
        self._server_countdown = SERVER_SCAN_TICKS
        stream = self._stream
        if stream is None:
            self.peers.watch(0)
            self.ping.set_measured(None, None, "")
            self.ping.set_auto_target(None)
            return
        # Tabela de conexoes primeiro (barata). Jogo so' de UDP nao aparece la',
        # e ai' entra o farejador, que cruza porta local com trafego real.
        self.peers.watch(stream.pid)
        rtt, jitter = self.peers.latency
        self.ping.set_measured(rtt, jitter, stream.app or "jogo")
        alvo = netmod.game_server(stream.pid) or self.peers.peer
        if alvo is None:
            self.ping.set_auto_target(None)
            return
        self.ping.set_auto_target(alvo[0], alvo[1], stream.app or "jogo")

    def _watch_any_game(self) -> None:
        """Volta ao arranjo padrao quando QUALQUER jogo fecha.

        O atalho do app so' cobre o que foi aberto por ele. Na pratica o jogo
        entra por fora (pelo launcher da loja, pelo atalho da area de trabalho)
        e a TV ficava ligada depois de fechar. Aqui a regra e' simples: enquanto
        houver jogo em tela cheia apresentando quadros, guarda o pid; quando esse
        processo morre e as telas nao estao no padrao, devolve o padrao.
        """
        agora = time.monotonic()
        pid = self._fg_pid if self._fg_fullscreen else 0
        if pid and self.fps.stream(pid) is not None:
            nome = _process_name(pid)
            if nome and nome.lower() not in _NOT_A_GAME:
                self._game_pid = pid
                self._game_name = nome
                self._game_seen_at = agora
                return

        if not self._game_pid:
            return
        if _pid_alive(self._game_pid):
            self._game_seen_at = agora
            return
        if agora - self._game_seen_at < GAME_EXIT_GRACE_S:
            return

        nome, self._game_name = self._game_name, ""
        self._game_pid = 0
        if not self.settings.display_restore_after_game:
            return
        alvo = self._normal_layout()
        if alvo is None or _same_layout(alvo, dsp.snapshot()):
            return
        ok, err = dsp.apply_profile(alvo, self._normal_topology())
        _log.info("%s fechou; telas de volta ao padrao (%s)", nome, "ok" if ok else err)
        if ok:
            self.notify("Vantage", f"{nome} fechou: telas de volta ao padrão")

    def _normal_topology(self) -> str:
        nome = self.settings.display_default_profile
        profile = next((p for p in self.settings.display_profiles
                        if p["name"] == nome), None)
        return profile.get("topology", "") if profile else ""

    def _normal_layout(self) -> list[dict] | None:
        """Entradas do perfil marcado como padrao, se houver um."""
        nome = self.settings.display_default_profile
        if not nome:
            return None
        profile = next((p for p in self.settings.display_profiles
                        if p["name"] == nome), None)
        return profile["entries"] if profile else None

    def _adopt_game_process(self, session) -> None:
        """Descobre o processo real do jogo e ensina a sessao a segui-lo.

        Atalho de loja (.url, .lnk de protocolo) abre o cliente, e o jogo sobe
        depois com outro nome; o nome do atalho nao serve de nada. Quem sabe a
        resposta e' o que ja' esta' na mao: a janela em tela cheia em foco, com o
        PresentMon confirmando que ela esta' apresentando quadros.
        """
        if session.adopted or not self._fg_fullscreen or not self._fg_pid:
            return
        stream = self.fps.stream(self._fg_pid)
        nome = stream.app if stream is not None else _process_name(self._fg_pid)
        if not nome or nome.lower() in _NOT_A_GAME:
            return
        session.watch({nome})
        session.adopted = True
        _log.info("sessao '%s' seguindo o processo %s", self._session_name, nome)

    def _restore_displays(self) -> None:
        """Devolve as telas ao arranjo de quando o app abriu.

        Perfil de TV apaga os monitores da mesa. Fechar o app com a maquina nesse
        estado deixa o usuario sem imagem onde ele esta', e sem o app para
        desfazer. Entao a volta e' automatica, e so' acontece se algo mudou.
        """
        if os.name != "nt" or not self.settings.display_restore_on_exit:
            return
        # Com um arranjo padrao definido, ele manda tambem na saida: e' o mesmo
        # estado que o app impoe ao abrir, e as duas pontas concordarem e' o que
        # torna o comportamento previsivel. Sem padrao definido, sobra o retrato
        # de antes, que e' o que existia antes desta opcao.
        if self._tem_arranjo_padrao():
            self._enforce_display_defaults()
            return
        # Fechar com jogo aberto volta para o estado de antes do jogo, que e' mais
        # recente que o do boot; e' o que o usuario reconhece como "o normal".
        # A ordem tambem e' a de preferencia quando um alvo nao da' para aplicar.
        candidatos = [c for c in (self._normal_layout(), self._session_restore,
                                  self._display_boot) if c]
        if not candidatos:
            return
        try:
            atual = dsp.snapshot()
            erros = []
            for alvo in candidatos:
                if _same_layout(alvo, atual):
                    return
                # Se a unica diferenca e' quem manda, trocar a primaria basta.
                # Mandar o perfil inteiro por causa disso apagava as tres telas
                # por varios segundos, justo na hora em que o app esta' sumindo
                # e nao tem mais como desfazer nada.
                so_primaria = _only_primary_differs(alvo, atual)
                if so_primaria:
                    self._restore_primary(so_primaria)
                    return
                ok, err = dsp.apply_profile(alvo)
                if ok:
                    _log.info("telas restauradas ao fechar")
                    return
                erros.append(err)
            # Perfil salvo envelhece: basta trocar um monitor de porta para ele
            # apontar para telas que nao existem mais. Antes o app parava na
            # primeira recusa e fechava deixando o arranjo de TV na maquina;
            # agora ele tenta o retrato do proprio boot antes de desistir.
            _log.warning("nao consegui restaurar as telas: %s", "; ".join(erros))
        except Exception:
            _log.exception("falha restaurando as telas ao fechar")

    def _tick_system(self) -> None:
        data = self.collector.snapshot()
        if not data:
            return
        self._data = data
        gpu = data.get("gpu") or {}

        for key, getter in _SERIES:
            value = getter(data, gpu)
            self.history.push(key, value)
            self.stats.update(key, value)

        stream = self._stream
        if stream is not None:
            m = stream.metrics
            self.history.push("fps", m.fps_now)
            self.history.push("fps_low1", m.low_1)
            self.history.push("fps_low01", m.low_01)
            self.stats.update("fps", m.fps_now)
        else:
            self.history.push("fps", None)
            self.history.push("fps_low1", None)
            self.history.push("fps_low01", None)

        for node in self.lhm.tree():
            self.stats.update(node.key, node.value)

        if self._bench_active:
            for key, source in _SYSTEM_KEYS:
                self._bench_env.update(key, self.stats.last(source))
        if self._session_bench:
            for key, source in _SYSTEM_KEYS:
                self._session_env.update(key, self.stats.last(source))

        if self.window.isVisible():
            self.window.tick_system(data)
        self._check_alerts(data, gpu)
        self._update_tray_tooltip(data, gpu)

    def _tick_fast(self) -> None:
        self._stream = self._select_stream()
        # O coletor mede a RAM do jogo, mas quem sabe qual e' o jogo e' o motor de
        # FPS. Avisar aqui, e nao no ciclo de 1 s, faz a medida acabar junto com o
        # jogo em vez de sobreviver um segundo a mais apontando para um pid morto.
        pid = self._stream.pid if self._stream is not None else 0
        if os.name != "nt" and self._session is not None:
            pid = self._session.native_pid or 0
            if pid and self._session_priority:
                self._apply_launch_priority(pid)
        self.collector.set_game_pid(pid)
        if self._session is not None and self._stream is not None:
            pid = self._stream.pid
            if pid != self._session_bench_pid:
                self._session_bench_pid = pid
                if self._session_bench:
                    self.fps.session_follow(pid)
                self._apply_launch_priority(pid)
        if self.window.isVisible():
            self.window.tick_fps()
        if self._overlay is not None:
            self._overlay.refresh()
            if os.name == "nt":
                win.keep_topmost(int(self._overlay.winId()))
        if self._bench_active and time.monotonic() - self._bench_started >= self._bench_total:
            self.benchmark_stop()

    def _load_profile(self) -> str:
        """Quanto esforco vale a pena agora: "painel", "overlay" ou "fundo".

        Ler todos os sensores custa ~17 ms, e a 1 Hz isso e' quase 2% de um
        nucleo o tempo todo. Com um jogo na frente, esse nucleo faz falta, e
        ninguem esta' vendo o painel. Entao o ritmo passa a seguir quem esta'
        de fato olhando: a janela aberta, o overlay, ou ninguem.
        """
        # A condicao e' "tem jogo na frente", nao "tem janela grande na frente".
        # Usar tela cheia como criterio fazia o app cair para o ritmo de fundo
        # com um terminal maximizado por cima, e ai' o painel, aberto na outra
        # tela, atualizava a cada tres segundos sem motivo.
        if self.window.isVisible() and not self.game_in_focus():
            return "painel"
        if self._overlay is not None and self._overlay.isVisible():
            return "overlay"
        return "fundo"

    def _apply_load_profile(self) -> None:
        perfil = self._load_profile()
        if perfil == self._load_now:
            return
        self._load_now = perfil
        base = self.settings.update_interval
        if perfil == "painel":
            intervalo = base
        elif perfil == "overlay":
            # Nada de medir mais rapido do que o overlay desenha: seria trabalho
            # que ninguem chega a ver.
            intervalo = max(base, 1.0 / max(0.5, self.settings.overlay_refresh_hz))
        else:
            # Sem janela e sem overlay so' restam a bandeja e o historico, que
            # aguentam bem um passo mais largo.
            intervalo = max(base, BACKGROUND_INTERVAL_S)
        self.collector.set_interval(intervalo)
        if self._t_sys is not None:
            self._t_sys.setInterval(int(intervalo * 1000))
        _log.info("ritmo de coleta: %s (%.1f s por leitura)", perfil, intervalo)

    def _tick_focus(self) -> None:
        fullscreen, hwnd = win.is_foreground_fullscreen() if os.name == "nt" else (False, 0)
        own = {int(self.window.winId())}
        if self._overlay is not None:
            own.add(int(self._overlay.winId()))
        if self._bigpicture is not None:
            # Sem isso o Big Picture, que e' tela cheia, seria julgado como o
            # jogo em foco, e o app passaria a medir a si mesmo.
            own.add(int(self._bigpicture.winId()))
        self._fg_fullscreen = fullscreen and hwnd not in own
        self._fg_pid = win.window_pid(hwnd) if os.name == "nt" and hwnd not in own else 0
        self.fps.expect(self._fg_pid if self._fg_fullscreen else None)
        self.procs.set_game_pids(self.fps.snapshot().keys())
        if self.settings.overlay_enabled and self.settings.overlay_auto_game:
            self._sync_overlay_visibility()
        self._apply_load_profile()
        if (self._bigpicture is not None and self._bigpicture.isVisible()
                and self.game_in_focus()):
            # Um jogo subiu por fora. Uma janela em tela cheia disputando o
            # primeiro plano com ele so' atrapalha.
            self._soltar_controle()
        if self.gamepad is None:
            return
        if not self.gamepad.connected and self._bigpicture is not None:
            self._bigpicture.sem_controle()
        self._vigiar_atalho_do_sofa()

    def _vigiar_atalho_do_sofa(self) -> None:
        """Segurar Back por um segundo abre o Big Picture.

        Back esta' livre de proposito no mapeamento, e segurar evita colidir com
        o combo Back+Start, que assume o mouse. Do sofa, e' o unico jeito de
        chamar a grade sem levantar.
        """
        if self._bigpicture is not None and self._bigpicture.isVisible():
            self._bp_back_desde = 0.0
            return
        from .platform.gamepad import BTN_BACK, BTN_START
        pad = self.gamepad.last
        segurando = pad is not None and (pad.wButtons & BTN_BACK) and not (
            pad.wButtons & BTN_START)
        agora = time.monotonic()
        if not segurando:
            self._bp_back_desde = 0.0
            self._bp_back_pronto = True
            return
        # So' conta o segurar que COMECOU com a gente olhando. Sem exigir a
        # borda, um controle que ja' estava com Back apertado (ou que reporta o
        # botao preso) abria a grade sozinho um segundo depois de o app subir.
        if not self._bp_back_pronto:
            return
        if not self._bp_back_desde:
            self._bp_back_desde = agora
        elif agora - self._bp_back_desde >= 1.0:
            self._bp_back_desde = 0.0
            self._bp_back_pronto = False
            self.big_picture_abrir()

    def _select_stream(self):
        streams = self.fps.snapshot()
        if not streams:
            return None
        pin = self.settings.fps_pin
        if pin:
            matches = [s for s in streams.values() if s.app.lower() == pin.lower()]
            return max(matches, key=lambda s: s.metrics.frames) if matches else None
        if self.settings.fps_only_fullscreen:
            if not self._fg_fullscreen:
                return None
            return streams.get(self._fg_pid)
        if self._fg_pid in streams:
            return streams[self._fg_pid]
        return max(streams.values(), key=lambda s: s.metrics.frames)

    def active_stream(self):
        return self._stream

    def last_data(self) -> dict:
        return self._data

    def fps_hint(self) -> str:
        if not self.fps.running:
            return self.fps.status
        if self.settings.fps_pin:
            return f"aguardando {self.settings.fps_pin}"
        if self.settings.fps_only_fullscreen and not self._fg_fullscreen:
            return "nenhum jogo em tela cheia"
        return "nenhum jogo apresentando quadros"

    def _check_alerts(self, d: dict, gpu: dict) -> None:
        if not self.settings.alerts_enabled:
            return
        checks = (
            ("cpu_temp", self.settings.alert_cpu_temp, d.get("cpu_temp"),
             "Temperatura da CPU", "°C"),
            ("gpu_temp", self.settings.alert_gpu_temp, gpu.get("temp"),
             "Temperatura da GPU", "°C"),
            ("ram", self.settings.alert_ram_pct, d.get("ram_pct"), "Uso de RAM", "%"),
            ("vram", self.settings.alert_vram_pct, gpu.get("vram_pct"), "Uso de VRAM", "%"),
        )
        for key, limit, value, name, unit in checks:
            if not limit or value is None:
                continue
            if value >= limit and not self._alerted.get(key):
                self._alerted[key] = True
                self.notify("Vantage: alerta",
                            f"{name}: {value:.0f}{unit} (limite {limit}{unit})")
            elif value <= limit - 4:
                self._alerted[key] = False

    def _update_tray_tooltip(self, d: dict, gpu: dict) -> None:
        parts = [f"CPU {d.get('cpu_pct', 0):.0f}%"]
        if d.get("cpu_temp"):
            parts.append(f"{d['cpu_temp']:.0f}°C")
        # Placa que nao publica carga entra com travessao: formatar o None
        # derrubava a dica inteira, e um "0%" inventado seria pior ainda.
        if gpu.get("usage") is not None:
            parts.append(f"GPU {gpu['usage']:.0f}%")
        if gpu.get("temp"):
            parts.append(f"{gpu['temp']:.0f}°C")
        if self._stream is not None:
            fps = self._stream.metrics.fps_now
            if fps:
                parts.append(f"{fps:.0f} fps")
        self.tray.set_tooltip("Vantage: " + "  ·  ".join(parts))

    def notify(self, title: str, message: str) -> None:
        self.tray.notify(title, message)

    def notify_tray_hint(self) -> None:
        if not self._tray_hinted:
            self._tray_hinted = True
            self.notify("Vantage", "Continua rodando na bandeja. Clique no ícone "
                                     "para reabrir.")

    def trazer_para_frente(self) -> None:
        """Mostra a janela porque outra copia do app tentou abrir.

        Vem de uma thread propria (a que espera o evento nomeado), e mexer em
        widget fora do laco do Qt trava a interface de formas dificeis de
        reproduzir. O singleShot de zero devolve a chamada para a thread certa
        antes de qualquer coisa acontecer.

        O `self.qt` no meio e' o que faz isso funcionar. Sem objeto de contexto o
        timer nasce na thread que chamou, que nao tem laco de eventos, e nunca
        dispara: a segunda copia saia avisando que tinha trazido a primeira, e a
        primeira continuava escondida na bandeja.
        """
        QTimer.singleShot(0, self.qt, self._trazer_agora)

    def _trazer_agora(self) -> None:
        # Minimizada ou escondida na bandeja sao estados diferentes, e os dois
        # precisam voltar: `show` resolve a bandeja, `showNormal` desfaz a
        # minimizacao, e sem os dois a janela "aparece" sem aparecer.
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.store_geometry()
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def show_view(self, key: str) -> None:
        if not self.window.isVisible():
            self.window.show()
        self.window.show_view(key)
        self.window.raise_()
        self.window.activateWindow()

    def save_settings(self) -> None:
        self.settings.save()

    def open_settings(self, tab: int = 0) -> None:
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._dialog = SettingsDialog(self, tab)
        self._dialog.finished.connect(lambda _r: setattr(self, "_dialog", None))
        self._dialog.show()

    def on_settings_changed(self) -> None:
        cfg = self.settings
        self.qt.setPalette(style.build_palette(cfg.accent))
        self.qt.setStyleSheet(style.build_qss(cfg.accent))
        self.lhm.mem_rail = cfg.mem_volt_rail
        self.ping.configure(cfg.ping_host, cfg.ping_port)
        self.fps.set_windows(cfg.fps_window, cfg.fps_now_window)
        self.history.resize(self._history_depth())
        self.window.apply_settings()
        self._apply_overlay()
        # O ritmo sai do perfil de quem esta' olhando, e nao direto do intervalo
        # base: salvar pela bandeja, com a janela fechada, deixava o coletor no
        # ritmo cheio e o perfil em cache dizendo "fundo", sem nada que corrigisse.
        self._load_now = ""
        self._apply_load_profile()
        self.tray.sync()
        autostart.set_enabled(cfg.autostart)
        cfg.save()

    def set_fps_pin(self, name: str) -> None:
        self.settings.fps_pin = name
        self.settings.save()
        self.window.apply_settings()

    def set_fps_window(self, seconds: float) -> None:
        self.settings.fps_window = seconds
        self.settings.sanitize()
        self.fps.set_windows(self.settings.fps_window, self.settings.fps_now_window)
        self.settings.save()
        self.window.apply_settings()

    def restart_capture(self) -> None:
        if os.name != "nt":
            self.notify("Vantage", self.fps.status)
            return
        self.fps.restart()
        self.notify("Vantage", "Captura de FPS reiniciada.")

    def clear_stats(self) -> None:
        self.stats.clear()
        self.history.clear()
        self.fps.reset()

    def _hotkey_reset(self) -> None:
        self.clear_stats()
        self.notify("Vantage", "Sessão zerada (Ctrl+Alt+R)")

    def _hotkey_benchmark(self) -> None:
        if self._bench_active:
            self.benchmark_stop()
        else:
            self.benchmark_start(self.settings.bench_seconds)

    def _history_depth(self) -> int:
        return max(80, int(self.settings.history_window / self.settings.update_interval) + 4)

    def toggle_overlay(self) -> None:
        self.settings.overlay_enabled = not self.settings.overlay_enabled
        self.settings.save()
        self._apply_overlay()
        self.window.titlebar.sync_overlay_button()
        self.tray.sync()

    def _apply_overlay(self) -> None:
        if not self.settings.overlay_enabled:
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None
            return
        if self._overlay is None:
            self._overlay = GameOverlay(self)
        else:
            self._overlay.rebuild()
        self._sync_overlay_visibility()

    def jogo_online(self) -> bool | None:
        """A partida em curso fala com algum servidor?

        True quando descobrimos o servidor do jogo ou medimos latencia no
        trafego dele; False quando procuramos tempo suficiente e nao apareceu
        nada: jogo local, treino contra bot, campanha. None enquanto ainda da'
        para aparecer, porque a busca leva alguns segundos e chamar de "local"
        cedo demais e' pior que ficar calado.
        """
        if not self._game_pid:
            return None
        if self.ping.following_game or self.ping.measuring_game:
            return True
        if time.monotonic() - self._game_seen_at < ONLINE_GRACE_S:
            return None
        return False

    def game_in_focus(self) -> bool:
        """Ha' um jogo de verdade na tela agora.

        "Alguem apresentando quadros" nao serve como criterio: no desktop o
        navegador e o Discord tambem apresentam, e o overlay aparecia por cima
        da area de trabalho. Jogo e' o processo em foco que esta' apresentando
        quadros: em tela cheia, ou em janela mas com o foco na mao dele.
        """
        # Tela cheia e' o que separa jogo de janela qualquer: o terminal e o
        # navegador tambem apresentam quadros, e sem esse criterio o overlay
        # aparecia por cima da area de trabalho.
        if not self._fg_fullscreen or not self._fg_pid:
            return False
        nome = _process_name(self._fg_pid).lower()
        if nome in _NOT_A_GAME:
            return False
        if self.fps.stream(self._fg_pid) is not None:
            return True
        # Nem sempre quem tem a janela e' quem desenha: ha' jogo em que o
        # PresentMon reporta um processo filho, e exigir o pid exato deixava o
        # overlay fora da tela justamente onde ele serve. O nome do executavel
        # ainda amarra o quadro ao que esta' em foco.
        atual = self._stream
        return atual is not None and bool(nome) and atual.app.lower() == nome

    def _sync_overlay_visibility(self) -> None:
        if self._overlay is None:
            return
        show = True
        if os.name == "nt" and self.settings.overlay_auto_game:
            show = self.game_in_focus()
        if show and not self._overlay.isVisible():
            self._overlay.show()
        elif not show and self._overlay.isVisible():
            self._overlay.hide()

    def benchmark_active(self) -> bool:
        return self._bench_active

    def benchmark_state(self) -> dict:
        return {
            "active": self._bench_active,
            "elapsed": (time.monotonic() - self._bench_started) if self._bench_active else 0.0,
            "total": self._bench_total,
            "frames": self.fps.capture_peek() if self._bench_active else 0,
            "game": self._bench_game,
        }

    def benchmark_last(self) -> dict | None:
        return self._bench_result

    def benchmark_start(self, seconds: int) -> None:
        if os.name != "nt":
            self.notify("Benchmark", self.fps.status)
            return
        if self._bench_active:
            return
        stream = self._stream
        if stream is None:
            self.notify("Vantage", "Nenhum jogo detectado para o benchmark.")
            return
        self._bench_active = True
        self._bench_pid = stream.pid
        self._bench_game = stream.app or "jogo"
        self._bench_started = time.monotonic()
        self._bench_total = float(seconds)
        self._bench_env = Accumulator()
        self.fps.capture_start(stream.pid)
        self.notify("Vantage", f"Benchmark iniciado: {seconds}s de {self._bench_game}")

    def benchmark_stop(self) -> None:
        if not self._bench_active:
            return
        self._bench_active = False
        samples = self.fps.capture_stop()
        if len(samples) < 20:
            self.notify("Vantage", "Benchmark sem amostras suficientes.")
            return
        metrics = fr.compute(samples, self.settings.fps_now_window)
        system = {}
        for key, _source in _SYSTEM_KEYS:
            agg = self._bench_env.get(key)
            if agg:
                system[key] = (agg[1], agg[2])
        self._bench_rev += 1
        self._bench_result = {
            "_rev": self._bench_rev,
            "game": self._bench_game,
            "metrics": metrics,
            "frametimes": [s[fr.FT] for s in samples],
            "samples": samples,
            "system": system,
        }
        self.bench_history.append({
            "time": datetime.now().strftime("%d/%m %H:%M"),
            "game": self._bench_game,
            "avg": metrics.fps_avg or 0.0,
            "low1": metrics.low_1 or 0.0,
            "low01": metrics.low_01 or 0.0,
            "smooth": metrics.smoothness or 0.0,
        })
        del self.bench_history[:-BENCH_HISTORY_MAX]
        _save_bench_history(self.bench_history)
        _save_last_bench(self._bench_result)
        if self.settings.bench_autosave:
            export.export_benchmark(_summary_row(metrics), self._bench_game)
        self.notify("Vantage",
                    f"Benchmark concluído: {metrics.fps_avg:.0f} fps médio, "
                    f"1% low {metrics.low_1:.0f}")
        self.show_view("benchmark")

    def benchmark_export(self):
        if not self._bench_result:
            return None
        # O resultado que voltou do disco nao traz as amostras cruas, so' os
        # frametimes: exportar dele gravava um CSV so' com o cabecalho, e a tela
        # ainda anunciava "exportado".
        amostras = (self._bench_result.get("samples")
                    or _amostras_dos_frametimes(self._bench_result.get("frametimes") or []))
        if not amostras:
            return None
        return export.export_frames(amostras, self._bench_result["game"])


_NOT_A_GAME = {
    "explorer.exe", "dwm.exe", "applicationframehost.exe", "shellexperiencehost.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
    "pythonw.exe", "vantage.exe",
}
"""Janelas que podem ficar em tela cheia sem serem o jogo que acabamos de abrir."""


def _tela_qt(nome: str):
    """QScreen cujo nome bate com o da tela, quando da' para casar.

    O Qt demora um instante para enxergar uma tela recem-acesa. Nao achando,
    devolve None e o Big Picture abre na primaria, melhor do que nao abrir.
    """
    from PySide6.QtWidgets import QApplication
    alvo = (nome or "").strip().lower()
    for tela in QApplication.screens():
        if alvo and alvo in (tela.name() or "").strip().lower():
            return tela
    return None


def _process_name(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return False


def _same_layout(a: list[dict], b: list[dict]) -> bool:
    """Compara dois retratos de tela pelo que importa: quem esta' ligada e como."""
    def chave(entries: list[dict]) -> set:
        return {(e.get("monitor_id") or e.get("device"), bool(e.get("active")),
                 bool(e.get("primary")), tuple(e.get("position") or ()),
                 tuple(e.get("mode") or ()))
                for e in entries}
    return chave(a) == chave(b)


def _only_primary_differs(alvo: list[dict], atual: list[dict]) -> str:
    """monitor_id que deveria ser a primaria, se for a unica diferenca.

    Devolve "" quando ha' qualquer outra mudanca (tela ligada, resolucao,
    posicao): nesse caso so' o perfil inteiro resolve.
    """
    def sem_primaria(entries: list[dict]) -> set:
        return {(e.get("monitor_id") or e.get("device"), bool(e.get("active")),
                 tuple(e.get("position") or ()), tuple(e.get("mode") or ()))
                for e in entries}

    if sem_primaria(alvo) != sem_primaria(atual):
        return ""
    quer = next((e.get("monitor_id") for e in alvo if e.get("primary")), "")
    tem = next((e.get("monitor_id") for e in atual if e.get("primary")), "")
    return quer if (quer and quer != tem) else ""


def _summary_row(m: fr.FrameMetrics) -> dict:
    return {k: v for k, v in m.as_dict().items() if isinstance(v, (int, float))}


def _amostras_dos_frametimes(frametimes) -> list[tuple]:
    """Amostras so' com tempo e frametime, montadas do que ficou gravado.

    O tempo e' o frametime acumulado, em segundos a partir do primeiro quadro; as
    colunas que so' a captura ao vivo tinha saem vazias no CSV, e nao zeradas.
    """
    saida: list[tuple] = []
    tempo = 0.0
    for bruto in frametimes:
        try:
            ft = float(bruto)
        except (TypeError, ValueError):
            continue
        if not 0.0 < ft < 1e6:          # zero, negativo, NaN e infinito ficam de fora
            continue
        tempo += ft / 1000.0
        saida.append((tempo, ft) + (fr.NAN,) * 6)
    return saida


def _gravar_json(caminho: Path, dados) -> None:
    """Grava inteiro ou nao grava: escreve ao lado e troca de uma vez.

    Escrever direto no arquivo trunca antes de gravar. Disco cheio, ou o app
    derrubado no meio, deixava o historico vazio; a abertura seguinte lia lista
    nenhuma e a proxima gravacao confirmava a perda por cima. E' o mesmo
    cuidado que o settings.json ja' tinha.
    """
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        os.replace(temporario, caminho)
    except Exception:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _so_registros(dados) -> list[dict]:
    """Lista de registros, ou lista vazia: outro formato nao vira historico.

    Um texto no lugar da lista passava pelo fatiamento (texto tambem fatia) e
    o `append` da partida seguinte derrubava o app.
    """
    if not isinstance(dados, list):
        return []
    return [r for r in dados if isinstance(r, dict)]


def _session_file():
    return paths.data_dir() / "sessoes.json"


def _load_session_history() -> list[dict]:
    try:
        dados = json.loads(_session_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    return _so_registros(dados)[-SESSION_HISTORY_MAX:]


def _save_session_history(history: list[dict]) -> None:
    try:
        _gravar_json(_session_file(), history)
    except OSError:
        _log.warning("nao consegui guardar o historico de sessoes")


def _bench_file():
    return paths.data_dir() / "benchmarks.json"


def _last_bench_file():
    return paths.data_dir() / "ultimo-benchmark.json"


def _save_last_bench(resultado: dict) -> None:
    """Guarda o resultado inteiro, menos as amostras cruas.

    Frametime a frametime sao dezenas de milhares de numeros: o suficiente para
    o histograma e a curva de percentis ja' esta' na lista de frametimes, e o
    resto do relatorio sai das metricas.
    """
    try:
        m = resultado["metrics"]
        _gravar_json(_last_bench_file(), {
            "quando": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "game": resultado.get("game", ""),
            "metrics": {k: v for k, v in m.as_dict().items()
                        if isinstance(v, (int, float, str)) or v is None},
            "frametimes": [round(f, 3) for f in resultado.get("frametimes", [])],
            "system": {k: list(v) for k, v in (resultado.get("system") or {}).items()},
        })
    except Exception:
        _log.exception("nao consegui guardar o ultimo benchmark")


def _load_last_bench() -> dict | None:
    """O ultimo resultado salvo, ou None se o arquivo nao servir.

    Roda dentro do construtor do App: qualquer excecao aqui era o app que nao
    abria mais, ate' alguem achar o arquivo e apaga-lo na mao.
    """
    try:
        bruto = json.loads(_last_bench_file().read_text(encoding="utf-8"))
        metrics = fr.FrameMetrics()
        for chave, valor in (bruto.get("metrics") or {}).items():
            if hasattr(metrics, chave):
                setattr(metrics, chave, valor)
        return {
            "_rev": 0,
            "quando": bruto.get("quando", ""),
            "game": bruto.get("game", ""),
            "metrics": metrics,
            "frametimes": list(bruto.get("frametimes") or []),
            "samples": [],
            "system": {k: tuple(v) for k, v in (bruto.get("system") or {}).items()},
        }
    except Exception:
        return None


def _load_bench_history() -> list[dict]:
    try:
        dados = json.loads(_bench_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    return _so_registros(dados)[-BENCH_HISTORY_MAX:]


def _save_bench_history(history: list[dict]) -> None:
    try:
        _gravar_json(_bench_file(), history)
    except OSError:
        pass
