"""Uma instância por diretório de dados e foco ao executar de novo."""
import fcntl

from PySide6.QtCore import QTimer

from ..paths import data_dir


class InstanciaUnica:
    def assumir(self):
        self.lock = (data_dir() / "instance.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            return False
        return True

    @staticmethod
    def pedir_foco():
        (data_dir() / "show.request").touch()
        return True

    def ouvir(self, mostrar):
        pedido = data_dir() / "show.request"

        def receber():
            try:
                pedido.unlink()
            except FileNotFoundError:
                return
            mostrar()

        self.timer = QTimer()
        self.timer.timeout.connect(receber)
        self.timer.start(500)

    def liberar(self):
        self.timer.stop()
        self.lock.close()
