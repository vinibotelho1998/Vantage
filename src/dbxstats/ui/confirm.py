"""Popups de confirmacao: o de confirmar-ou-desfazer das telas e o sim/nao geral.

Mexer em resolucao, rotacao ou topologia e' a unica coisa no app que pode deixar
a maquina sem imagem. O padrao do Windows resolve isso com um dialogo modal e um
relogio correndo: se ninguem confirmar, desfaz sozinho. E' o mesmo aqui, porque
sem imagem nao ha' como clicar em nada; o relogio e' a saida de emergencia.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .. import theme


class ConfirmRevertDialog(QDialog):
    """Pergunta se a mudanca fica. Sem resposta ate' o fim do relogio, desfaz."""

    def __init__(self, description: str, seconds: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats: confirmar telas")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setMinimumWidth(theme.scaled(420))

        self._total = max(1, int(seconds))
        self._left = self._total
        self._kept = False

        root = QVBoxLayout(self)
        root.setContentsMargins(*(theme.scaled(18),) * 4)
        root.setSpacing(theme.scaled(10))

        title = QLabel("Manter esta configuração de telas?")
        title.setFont(QFont(theme.FONT_UI, max(8, theme.scaled(12)), QFont.Weight.Bold))
        title.setWordWrap(True)
        root.addWidget(title)

        detail = QLabel(description)
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color: {theme.MUTE};")
        root.addWidget(detail)

        self._count = QLabel()
        self._count.setStyleSheet(f"color: {theme.WARN};")
        root.addWidget(self._count)

        self._bar = QProgressBar()
        self._bar.setRange(0, self._total)
        self._bar.setValue(self._total)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(theme.scaled(6))
        root.addWidget(self._bar)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        undo = QPushButton("Reverter agora")
        undo.clicked.connect(self.reject)
        keep = QPushButton("Manter")
        keep.setObjectName("Accent")
        keep.setDefault(True)
        keep.clicked.connect(self._keep)
        buttons.addWidget(undo)
        buttons.addWidget(keep)
        root.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._paint()

    def _paint(self) -> None:
        self._count.setText(f"Revertendo sozinho em {self._left}s se você não confirmar.")
        self._bar.setValue(self._left)

    def _tick(self) -> None:
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.reject()
            return
        self._paint()

    def _keep(self) -> None:
        self._kept = True
        self._timer.stop()
        self.accept()

    def ask(self) -> bool:
        """Mostra o popup e devolve True se o usuario mandou manter."""
        self._place()
        self._timer.start(1000)
        self.exec()
        self._timer.stop()
        return self._kept

    def _place(self) -> None:
        """Abre na tela onde o mouse esta'.

        Se a mudanca apagou uma das telas, o cursor e' a melhor pista de onde o
        usuario ainda enxerga alguma coisa.
        """
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        self.adjustSize()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2,
                  area.center().y() - self.height() // 2)


class ConfirmDialog(QDialog):
    """Sim ou nao para uma acao que nao tem desfazer.

    Nao e' QMessageBox porque o app desenha a propria barra de titulo e vive num
    tema escuro: o dialogo nativo abre branco no meio da tela e parece de outro
    programa; justo na hora em que a pessoa precisa confiar no que esta' lendo.
    """

    def __init__(self, titulo: str, texto: str, rotulo_ok: str = "Confirmar",
                 perigo: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setMinimumWidth(theme.scaled(430))

        root = QVBoxLayout(self)
        root.setContentsMargins(*(theme.scaled(18),) * 4)
        root.setSpacing(theme.scaled(10))

        cabeca = QLabel(titulo)
        cabeca.setFont(QFont(theme.FONT_UI, max(8, theme.scaled(12)), QFont.Weight.Bold))
        cabeca.setWordWrap(True)
        root.addWidget(cabeca)

        corpo = QLabel(texto)
        corpo.setWordWrap(True)
        corpo.setStyleSheet(f"color: {theme.MUTE};")
        root.addWidget(corpo)

        linha = QHBoxLayout()
        linha.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        # Enter cai no Cancelar de proposito: acao destrutiva nunca pode ser o
        # que acontece quando alguem so' queria fechar a janela no teclado.
        cancelar.setDefault(True)
        aceitar = QPushButton(rotulo_ok)
        aceitar.setObjectName("Danger" if perigo else "Accent")
        aceitar.clicked.connect(self.accept)
        linha.addWidget(cancelar)
        linha.addWidget(aceitar)
        root.addLayout(linha)


def confirmar(titulo: str, texto: str, rotulo_ok: str = "Confirmar",
              perigo: bool = False, parent=None) -> bool:
    """Pergunta e devolve True so' se a pessoa clicou no botao de confirmar."""
    dlg = ConfirmDialog(titulo, texto, rotulo_ok, perigo, parent)
    return dlg.exec() == QDialog.DialogCode.Accepted


def confirm_or_revert(description: str, seconds: int, undo: Callable[[], None],
                      parent=None) -> bool:
    """Aplica o padrao inteiro: pergunta, e desfaz se a resposta nao vier.

    Devolve True se a mudanca ficou de pe'.
    """
    if seconds <= 0:
        return True
    if ConfirmRevertDialog(description, seconds, parent).ask():
        return True
    undo()
    return False
