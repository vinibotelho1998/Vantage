"""Inventário das telas do compositor e dos controles do kernel."""
from pathlib import Path
import shutil
import subprocess

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from .base import View


class DisplaysView(View):
    key, title, glyph = "displays", "Telas", "▣"
    subtitle = "Monitores ativos nesta sessão"

    def __init__(self, app):
        super().__init__(app)
        layout = QVBoxLayout(self)
        self.state = QLabel()
        layout.addWidget(self.state)
        commands = (("kcmshell6", "kcm_kscreen"), ("gnome-control-center", "display"),
                    ("xfce4-display-settings",))
        command = next((args for args in commands if shutil.which(args[0])), None)
        if command:
            button = QPushButton("Configurar telas no sistema")
            button.clicked.connect(lambda: subprocess.Popen(command))
            layout.addWidget(button)
        layout.addStretch()
        self.reload()

    def reload(self):
        lines = []
        for screen in QGuiApplication.screens():
            size = screen.size() * screen.devicePixelRatio()
            title = screen.name() + (" · principal" if screen == QGuiApplication.primaryScreen() else "")
            lines.append(f"{title}\n{size.width()} × {size.height()} · {screen.refreshRate():g} Hz")
        self.state.setText("\n\n".join(lines))

    on_activate = reload


class GamepadView(View):
    key, title, glyph = "gamepad", "Controle", "✥"
    subtitle = "Controles detectados pelo Linux"

    def __init__(self, app):
        super().__init__(app)
        layout = QVBoxLayout(self)
        self.state = QLabel()
        layout.addWidget(self.state)
        layout.addStretch()
        self.on_activate()

    def on_activate(self):
        names = []
        for port in sorted(Path("/sys/class/input").glob("js[0-9]*")):
            try:
                names.append(port.joinpath("device/name").read_text().strip())
            except OSError:
                continue
        self.state.setText("\n".join(names) or "Nenhum joystick detectado pelo kernel.")

    def on_system(self, data):
        self.on_activate()
