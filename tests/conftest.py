"""Isola os testes do app instalado: nada de escrever no %APPDATA% de verdade."""
import os
import tempfile

os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")
os.environ.setdefault("DBXSTATS_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "dbxstats-tests"))
