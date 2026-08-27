"""Capa de cada jogo, para a grade do Big Picture nao ser so' retangulo colorido.

Tres fontes, da melhor para a pior, e a primeira que responder vence:

1. a imagem que o usuario escolheu no atalho: sempre ganha, porque e' a unica
   que ele controla e a unica que serve para jogo nenhum launcher conhece;
2. a arte da biblioteca do Steam, quando o jogo e' do Steam. E' capa de verdade,
   ja' esta' no disco e nao custa rede;
3. o icone do proprio executavel, extraido e guardado como PNG. E' pobre num
   card de TV, mas e' melhor que nada e nunca falta.

Sem rede em nenhum caminho: a grade abre do sofa, e uma tela que depende de
download trava esperando justamente quando ninguem tem teclado na mao.
"""
from __future__ import annotations

import ctypes
import hashlib
import re
from ctypes import wintypes
from pathlib import Path

from .. import log, paths

_log = log.get("art")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# Nomes que a Valve usa dentro da pasta do jogo no cache. A pasta intermediaria
# tem nome hasheado e opaco, mas o ARQUIVO nunca mudou de nome: entao a busca e'
# por nome, em qualquer profundidade, e o hash deixa de importar.
_STEAM_ART = ("library_header.jpg", "library_capsule.jpg", "header.jpg",
              "library_600x900.jpg", "library_hero.jpg")
"""Ordem de preferencia pela FORMA, nao pelo tamanho.

O card e' deitado (altura ~0.62 da largura). O header ja' nasce deitado e cobre
o card inteiro sem cortar nada importante; o capsule e' retrato e perde as
pontas; o hero e' largo demais e viraria uma tira do meio da imagem.
"""


def _steam_root() -> Path | None:
    """Onde o Steam esta' instalado, segundo o proprio Steam."""
    import winreg

    for hive, chave in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
        try:
            with winreg.OpenKey(hive, chave) as k:
                for valor in ("SteamPath", "InstallPath"):
                    try:
                        caminho = Path(winreg.QueryValueEx(k, valor)[0])
                    except OSError:
                        continue
                    if caminho.is_dir():
                        return caminho
        except OSError:
            continue
    padrao = Path(r"C:\Program Files (x86)\Steam")
    return padrao if padrao.is_dir() else None


def _steam_libraries(root: Path) -> list[Path]:
    """Todas as pastas de biblioteca, nao so' a da instalacao.

    Quem tem SSD e HD tem jogo nos dois, e o `libraryfolders.vdf` e' a lista que
    o proprio cliente mantem.
    """
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        texto = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libs
    for bruto in re.findall(r'"path"\s+"([^"]+)"', texto):
        caminho = Path(bruto.replace("\\\\", "\\"))
        if caminho.is_dir() and caminho not in libs:
            libs.append(caminho)
    return libs


_apps_cache: dict[str, dict[str, str]] = {}
"""Manifestos ja' lidos, por raiz do Steam.

A aba Jogos pergunta a origem da capa uma vez por linha, e o Big Picture uma vez
por card. Sem isto, cada pergunta reabriria todos os `appmanifest_*.acf` de todas
as bibliotecas: dezenas de arquivos para responder sobre um jogo so'.
"""


def invalidate() -> None:
    """Esquece os manifestos lidos. Para depois de instalar jogo novo."""
    _apps_cache.clear()


def _steam_apps(root: Path) -> dict[str, str]:
    """Pasta de instalacao (minuscula) -> appid, lida dos manifestos."""
    em_cache = _apps_cache.get(str(root))
    if em_cache is not None:
        return em_cache
    mapa: dict[str, str] = {}
    for lib in _steam_libraries(root):
        pasta = lib / "steamapps"
        try:
            manifestos = list(pasta.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for acf in manifestos:
            try:
                texto = acf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', texto)
            instalado = re.search(r'"installdir"\s+"([^"]+)"', texto)
            if not appid or not instalado:
                continue
            destino = pasta / "common" / instalado.group(1)
            mapa[str(destino).lower()] = appid.group(1)
    _apps_cache[str(root)] = mapa
    return mapa


def _appid_do_url(caminho: Path) -> str:
    """Le o appid de um atalho .url do Steam.

    Atalho de jogo do Steam e' um .url apontando para `steam://rungameid/<id>`,
    e nao ha' executavel nenhum no caminho: sem isto, jogo instalado pelo Steam
    e fixado na area de trabalho ficaria sem capa.
    """
    try:
        texto = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    achou = re.search(r"steam://rungameid/(\d+)", texto)
    return achou.group(1) if achou else ""


def _appid(path: Path, root: Path) -> str:
    if path.suffix.lower() == ".url":
        return _appid_do_url(path)
    alvo = str(path).lower()
    for pasta, appid in _steam_apps(root).items():
        # Compara pelo prefixo da pasta: o exe costuma estar varios niveis
        # abaixo dela (bin64\\Jogo.exe), entao igualdade nunca casaria.
        if alvo.startswith(pasta + "\\") or alvo == pasta:
            return appid
    return ""


def _steam_art(appid: str, root: Path) -> Path | None:
    cache = root / "appcache" / "librarycache"
    pasta = cache / appid
    for nome in _STEAM_ART:
        if pasta.is_dir():
            achado = next(pasta.rglob(nome), None)
            if achado is not None and achado.is_file():
                return achado
        # Layout antigo, tudo achatado num diretorio so'.
        antigo = cache / f"{appid}_{nome}"
        if antigo.is_file():
            return antigo
    return None


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


def _setup_prototypes() -> None:
    """Sem isto o ctypes assume `int` para todo handle.

    Em 64 bits um HBITMAP nao cabe num int, e a chamada morre com OverflowError
    justamente na hora de liberar o recurso, vazando o bitmap junto.
    """
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT]
    user32.PrivateExtractIconsW.restype = wintypes.UINT
    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                wintypes.UINT, ctypes.c_void_p,
                                ctypes.POINTER(BITMAPINFO), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL


_setup_prototypes()

BI_RGB = 0
DIB_RGB_COLORS = 0
_TAMANHOS = (256, 128, 96, 64, 48, 32)
"""Do maior para o menor. Um card de TV com icone de 32 px fica vergonhoso, mas
o exe pode simplesmente nao ter nada maior: entao se pede o maior e desce."""


def _hicon(caminho: Path, tamanho: int):
    """Um HICON do tamanho pedido, ou None se o arquivo nao tiver esse tamanho."""
    icone = wintypes.HICON()
    ident = wintypes.UINT()
    quantos = user32.PrivateExtractIconsW(
        str(caminho), 0, tamanho, tamanho, ctypes.byref(icone),
        ctypes.byref(ident), 1, 0)
    if quantos != 1 or not icone.value:
        return None
    return icone


def _qimage_do_icone(icone) -> object | None:
    """Converte HICON em QImage passando pelo DIB, que e' o unico formato que os
    dois lados entendem: o GDI escreve BGRA e o Qt le' ARGB32, que na memoria de
    maquina little-endian e' exatamente a mesma ordem de bytes."""
    from PySide6.QtGui import QImage

    info = ICONINFO()
    if not user32.GetIconInfo(icone, ctypes.byref(info)):
        return None
    try:
        bm = BITMAP()
        if not gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None
        largura, altura = bm.bmWidth, bm.bmHeight
        if largura <= 0 or altura <= 0:
            return None

        cabecalho = BITMAPINFO()
        cabecalho.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        cabecalho.bmiHeader.biWidth = largura
        # Altura negativa pede as linhas de cima para baixo. Sem isso o DIB vem
        # invertido, que e' a convencao do GDI e nao a do Qt.
        cabecalho.bmiHeader.biHeight = -altura
        cabecalho.bmiHeader.biPlanes = 1
        cabecalho.bmiHeader.biBitCount = 32
        cabecalho.bmiHeader.biCompression = BI_RGB

        buf = ctypes.create_string_buffer(largura * altura * 4)
        dc = user32.GetDC(None)
        try:
            linhas = gdi32.GetDIBits(dc, info.hbmColor, 0, altura, buf,
                                     ctypes.byref(cabecalho), DIB_RGB_COLORS)
        finally:
            user32.ReleaseDC(None, dc)
        if linhas == 0:
            return None

        dados = bytes(buf)
        # Icone antigo vem com alfa zerado em tudo; nesse caso o recorte vive na
        # mascara, e sem esta correcao a imagem inteira sairia invisivel.
        if not any(dados[3::4]):
            dados = b"".join(dados[i:i + 3] + b"\xff" for i in range(0, len(dados), 4))

        imagem = QImage(dados, largura, altura, largura * 4, QImage.Format.Format_ARGB32)
        return imagem.copy()      # solta a referencia ao buffer temporario
    finally:
        for bmp in (info.hbmColor, info.hbmMask):
            if bmp:
                gdi32.DeleteObject(bmp)


def _cache_dir() -> Path:
    pasta = paths.data_dir() / "capas"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def icon_png(caminho: Path) -> Path | None:
    """Maior icone do executavel, guardado como PNG e reaproveitado depois.

    Extrair custa varias chamadas ao GDI, e a grade repinta a cada movimento do
    foco. Guardar em disco tira isso do caminho do desenho de vez.
    """
    try:
        assinatura = f"{caminho}|{caminho.stat().st_mtime_ns}"
    except OSError:
        return None
    destino = _cache_dir() / f"{hashlib.sha1(assinatura.encode()).hexdigest()[:16]}.png"
    if destino.is_file():
        return destino

    for tamanho in _TAMANHOS:
        icone = _hicon(caminho, tamanho)
        if icone is None:
            continue
        try:
            imagem = _qimage_do_icone(icone)
        finally:
            user32.DestroyIcon(icone)
        if imagem is None or imagem.isNull():
            continue
        if imagem.save(str(destino), "PNG"):
            return destino
    return None


def artwork_path(item: dict) -> Path | None:
    """Melhor capa disponivel para um atalho, ou None se nao houver nenhuma."""
    escolhida = str(item.get("image", "")).strip()
    if escolhida:
        alvo = Path(escolhida)
        if alvo.is_file():
            return alvo

    caminho = Path(str(item.get("path", "")))
    root = _steam_root()
    if root is not None:
        try:
            appid = _appid(caminho, root)
        except OSError:
            appid = ""
        if appid:
            arte = _steam_art(appid, root)
            if arte is not None:
                return arte

    # O .url nao tem icone proprio, mas aponta para um: e' o que o Windows
    # desenha na area de trabalho, entao e' o que o usuario reconhece.
    if caminho.suffix.lower() == ".url":
        try:
            texto = caminho.read_text(encoding="utf-8", errors="replace")
        except OSError:
            texto = ""
        achou = re.search(r"IconFile=(.+)", texto)
        if achou:
            ico = Path(achou.group(1).strip())
            if ico.is_file():
                return icon_png(ico)
        return None

    if caminho.is_file():
        return icon_png(caminho)
    return None


def artwork_by_name(nome: str, itens=None) -> Path | None:
    """Capa a partir do NOME do jogo, procurando o atalho correspondente.

    A partida gravada guarda so' o nome: o caminho do executavel vive no
    atalho. Este e' o unico laco entre os dois, e e' o que permite a lista de
    sessoes ter capa igual a' aba Jogos.

    Jogo que foi removido da lista simplesmente nao tem capa, e isso esta'
    certo: nao ha' mais de onde tirar uma.
    """
    alvo = (nome or "").strip().lower()
    if not alvo:
        return None
    if itens is None:
        try:
            from ..config import Settings

            itens = Settings.load().launch_items
        except Exception:                                    # noqa: BLE001
            return None
    for item in itens or []:
        if str(item.get("name", "")).strip().lower() == alvo:
            return artwork_path(item)
    return None


def is_image(caminho: str) -> bool:
    return Path(caminho).suffix.lower() in _EXTS


def origin(item: dict) -> str:
    """De onde a capa veio, em uma palavra para a interface.

    Sem isto a aba Jogos nao teria como explicar por que um jogo mostra capa
    bonita e o vizinho mostra um icone pequeno, e a diferenca e' justamente o
    que decide se vale a pena escolher uma imagem a mao.
    """
    escolhida = str(item.get("image", "")).strip()
    if escolhida and Path(escolhida).is_file():
        return "escolhida"
    caminho = Path(str(item.get("path", "")))
    root = _steam_root()
    if root is not None:
        try:
            if _appid(caminho, root) and _steam_art(_appid(caminho, root), root):
                return "steam"
        except OSError:
            pass
    return "icone" if artwork_path(item) is not None else "nenhuma"


ORIGIN_LABEL = {
    "escolhida": "capa escolhida por você",
    "steam": "capa da biblioteca do Steam",
    "icone": "ícone do jogo (escolha uma capa para ficar melhor)",
    "nenhuma": "sem capa",
}
