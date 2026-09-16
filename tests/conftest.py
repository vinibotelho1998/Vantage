"""Isola os testes do app instalado: nada de escrever no %APPDATA% de verdade."""
import os
import tempfile

os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")
os.environ.setdefault("VANTAGE_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "vantage-tests"))
