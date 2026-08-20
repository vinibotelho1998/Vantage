# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.dirname(SPECPATH)

# O app e' Qt Widgets puro: desenha tudo com QPainter e fala rede pelo socket do
# Python. Sem podar, o PyInstaller carrega QML, Quick, PDF, OpenGL e o
# rasterizador de OpenGL por software (opengl32sw.dll, 20 MB sozinho) — dezenas
# de megabytes que ninguem chega a abrir.
QT_SOBRANDO = (
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtMultimedia", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtSvgWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtHelp", "PySide6.QtDesigner",
)
BINARIOS_SOBRANDO = (
    "opengl32sw.dll", "qt6quick.dll", "qt6qml.dll", "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll", "qt6pdf.dll", "qt6opengl.dll", "qt6network.dll",
    "qt6multimedia.dll", "qt6charts.dll", "qt6sql.dll", "qt6test.dll",
    "qt6designer.dll", "qt6help.dll", "qt6quick3d.dll",
)


def _descartar(item):
    """True para coisa que nao vai no pacote."""
    destino = item[0].replace("\\", "/").lower()
    nome = destino.rsplit("/", 1)[-1]
    if nome in BINARIOS_SOBRANDO:
        return True
    # Traducoes do proprio Qt: so' o portugues interessa, e sao ~7 MB no total.
    if "/translations/" in destino and destino.endswith(".qm"):
        return "_pt" not in nome
    return False

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "vendor", "lhm"), "lhm"),
        (os.path.join(ROOT, "tools", "presentmon.exe"), "tools"),
        # O icone precisa vir junto: o embutido no .exe serve para o Explorer,
        # mas a barra de tarefas usa o icone da JANELA, e ele e' carregado deste
        # arquivo em tempo de execucao. Sem ele no pacote, setWindowIcon nunca
        # roda e a janela fica com o icone generico do Windows.
        (os.path.join(ROOT, "assets", "icon.ico"), "assets"),
        (os.path.join(ROOT, "assets", "icon.png"), "assets"),
    ],
    hiddenimports=["wmi", "pynvml", "clr", "win32api", "win32con", "win32gui"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", *QT_SOBRANDO],
    noarchive=False,
    optimize=0,
)
a.binaries = [b for b in a.binaries if not _descartar(b)]
a.datas = [d for d in a.datas if not _descartar(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DBXStats",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    uac_admin=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DBXStats",
)
