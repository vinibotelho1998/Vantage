"""Procura os jogos instalados, para nao ter que cacar o .exe na mao.

Achar um jogo pelo explorador de arquivos e' pior do que parece: o executavel
raramente esta' na raiz da pasta (`Crimson Desert\\bin64\\CrimsonDesert.exe`), e
a pasta ainda vem cheia de executavel que nao e' o jogo: instalador de
redistribuivel, desinstalador, relator de travamento. Por isso so' atalho da area
de trabalho era facil de adicionar: e' o unico que ja' aponta para o lugar certo.

Aqui a busca e' feita de tras para frente: primeiro se descobre QUAIS jogos
existem (manifesto do Steam, pastas conhecidas de biblioteca) e so' depois se
procura o executavel dentro de cada um, escolhendo entre os candidatos.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .. import log

_log = log.get("gamescan")

_LIXO = (
    "unins", "uninstall", "setup", "installer", "install", "vcredist", "vc_redist",
    "dxsetup", "directx", "dxwebsetup", "dotnet", "redist", "oalinst", "openal",
    "crashhandler", "crashreport", "crashpad", "bugreport", "errorreport",
    "updater", "update", "patcher", "touchup", "activation", "cleanup",
    "diagnostic", "benchmark_tool", "config", "settings", "unitycrashhandler",
    "ueprereqsetup", "epicwebhelper", "easteamproxy", "eaanticheat", "anticheat",
    "battleye", "easyanticheat", "helper", "service", "daemon", "notification",
)
"""Nomes que nunca sao o jogo.

Sem esta lista o palpite mais obvio (o maior executavel da pasta) cai no
instalador do redistribuivel da Microsoft com uma frequencia incomoda.
"""

_BIN = ("bin64", "bin", "binaries", "win64", "x64", "game", "retail")
"""Pastas onde o executavel de verdade costuma morar."""

_PROFUNDIDADE = 4
"""Ate' onde descer dentro da pasta do jogo.

`Jogo\\Binaries\\Win64\\Jogo.exe` sao tres; quatro cobre com folga. Sem limite,
uma pasta com mods ou com um motor inteiro dentro faria a busca varrer dezenas de
milhares de arquivos.
"""

_MAX_ARQUIVOS = 4000
"""Teto de executaveis olhados por jogo, para uma pasta doente nao travar a tela."""


@dataclass(frozen=True)
class Achado:
    """Um jogo encontrado, pronto para virar atalho."""

    name: str
    path: str
    source: str
    """"Steam", "pasta" ou "atalho": a tela mostra de onde veio."""


def _normal(texto: str) -> str:
    """Reduz a comparavel: sem pontuacao, sem espaco, sem caixa.

    "Crimson Desert" e "CrimsonDesert.exe" tem de casar, e e' esse casamento que
    escolhe o executavel certo na maioria dos jogos.
    """
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def _e_lixo(stem: str) -> bool:
    baixo = stem.lower()
    return any(marca in baixo for marca in _LIXO)


def _executaveis(raiz: Path) -> list[Path]:
    """Executaveis plausiveis dentro da pasta do jogo, ja' sem o lixo."""
    achados: list[Path] = []
    raiz_str = str(raiz)
    for pasta, subpastas, arquivos in os.walk(raiz_str):
        profundidade = pasta[len(raiz_str):].count(os.sep)
        if profundidade >= _PROFUNDIDADE:
            subpastas[:] = []
            continue
        # Nao adianta descer em pasta de recurso, e sao elas que tem os milhares
        # de arquivos.
        subpastas[:] = [s for s in subpastas
                        if s.lower() not in ("content", "data", "assets", "paks",
                                             "movies", "sound", "audio", "textures",
                                             "_commonredist", "redist", "support")]
        for nome in arquivos:
            if not nome.lower().endswith(".exe"):
                continue
            if _e_lixo(Path(nome).stem):
                continue
            achados.append(Path(pasta) / nome)
            if len(achados) >= _MAX_ARQUIVOS:
                return achados
    return achados


def _melhor_exe(raiz: Path, titulo: str) -> Path | None:
    """Qual dos executaveis e' o jogo.

    O nome manda, e o tamanho so' desempata. E' de proposito: o maior arquivo da
    pasta as vezes e' um motor ou uma ferramenta, mas o executavel que se chama
    como o jogo quase sempre e' o jogo.
    """
    candidatos = _executaveis(raiz)
    if not candidatos:
        return None

    alvo = _normal(titulo)

    def peso(caminho: Path) -> tuple:
        stem = _normal(caminho.stem)
        if stem == alvo:
            casamento = 3
        elif alvo and (stem.startswith(alvo) or alvo.startswith(stem)):
            casamento = 2
        elif alvo and (alvo in stem or stem in alvo):
            casamento = 1
        else:
            casamento = 0
        # Estar numa pasta de binario e' pista fraca, mas separa o jogo de um
        # utilitario largado na raiz.
        em_bin = any(p.lower() in _BIN for p in caminho.parts)
        try:
            tamanho = caminho.stat().st_size
        except OSError:
            tamanho = 0
        return (casamento, em_bin, tamanho)

    return max(candidatos, key=peso)


def _do_steam() -> list[Achado]:
    from . import art

    root = art._steam_root()
    if root is None:
        return []
    achados: list[Achado] = []
    for lib in art._steam_libraries(root):
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
            nome = re.search(r'"name"\s+"([^"]+)"', texto)
            instalado = re.search(r'"installdir"\s+"([^"]+)"', texto)
            if not nome or not instalado:
                continue
            titulo = nome.group(1).strip()
            # Redistribuivel e ferramenta entram como "jogo" no manifesto; nao
            # sao jogo e nem tem executavel proprio para abrir.
            if _e_lixo(titulo) or "redistributable" in titulo.lower():
                continue
            destino = pasta / "common" / instalado.group(1)
            if not destino.is_dir():
                continue
            exe = _melhor_exe(destino, titulo)
            if exe is not None:
                achados.append(Achado(titulo[:40], str(exe), "Steam"))
    return achados


def _raizes() -> list[Path]:
    """Onde procurar pasta de jogo, em todos os discos que existirem."""
    nomes = ("Games", "Jogos", "SteamLibrary", "Epic Games", "GOG Games",
             "XboxGames", "Program Files (x86)/Steam/steamapps/common")
    raizes: list[Path] = []
    for letra in "CDEFGH":
        disco = Path(f"{letra}:/")
        if not disco.exists():
            continue
        for nome in nomes:
            alvo = disco / nome
            if alvo.is_dir():
                raizes.append(alvo)
    for fixo in (r"C:\Program Files\Epic Games",
                 r"C:\Program Files (x86)\Epic Games",
                 r"C:\Program Files\EA Games",
                 r"C:\Program Files (x86)\EA Games",
                 r"C:\Program Files\Electronic Arts",
                 r"C:\Program Files (x86)\GOG Galaxy\Games",
                 r"C:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games"):
        alvo = Path(fixo)
        if alvo.is_dir():
            raizes.append(alvo)
    return raizes


def _das_pastas() -> list[Achado]:
    achados: list[Achado] = []
    for raiz in _raizes():
        try:
            subpastas = [p for p in raiz.iterdir() if p.is_dir()]
        except OSError:
            continue
        for pasta in subpastas:
            if _e_lixo(pasta.name):
                continue
            exe = _melhor_exe(pasta, pasta.name)
            if exe is not None:
                achados.append(Achado(pasta.name[:40], str(exe), "pasta"))
    return achados


def _da_area_de_trabalho() -> list[Achado]:
    """O que estiver na area de trabalho: atalho do Steam, .lnk ou o exe solto.

    O exe solto entra porque e' o caso que mais irrita: baixar o jogo, largar o
    executavel na area de trabalho e o app nao oferecer ele. Pior, arrastar dali
    para a janela nao funciona: o DBX Stats roda elevado, e o Windows bloqueia
    arrastar de um Explorer comum para uma janela elevada (UIPI), sem aviso
    nenhum. Encontrar sozinho e' o que fecha esse buraco.

    A area de trabalho publica entra junto: instalador costuma criar o atalho
    la', e ela nao aparece como pasta separada para quem olha a tela.
    """
    achados: list[Achado] = []
    locais = [Path(os.path.expandvars(r"%USERPROFILE%\Desktop")),
              Path(os.path.expandvars(r"%PUBLIC%\Desktop"))]
    for local in locais:
        if not local.is_dir():
            continue
        try:
            arquivos = list(local.iterdir())
        except OSError:
            continue
        for arquivo in arquivos:
            sufixo = arquivo.suffix.lower()
            if sufixo == ".url":
                try:
                    texto = arquivo.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "steam://rungameid/" not in texto:
                    continue
                achados.append(Achado(arquivo.stem[:40], str(arquivo), "atalho"))
            elif sufixo == ".exe" and not _e_lixo(arquivo.stem):
                achados.append(Achado(arquivo.stem[:40], str(arquivo), "atalho"))
            elif sufixo == ".lnk" and not _e_lixo(arquivo.stem):
                from ..core.session import resolve_shortcut

                alvo = resolve_shortcut(str(arquivo))
                # Atalho que aponta para exe vira o exe: o alvo e' o que o app
                # precisa acompanhar para saber quando o jogo fechou.
                if not alvo.lower().endswith(".exe") or not Path(alvo).is_file():
                    continue
                # So' entra se o alvo mora numa pasta de jogo. A area de trabalho
                # e' cheia de atalho de programa (navegador, monitor de sensor,
                # cliente de conversa) e sem este filtro a lista de "jogos
                # encontrados" vinha com Chrome e CPU-Z dentro.
                if not _em_pasta_de_jogo(alvo):
                    continue
                achados.append(Achado(arquivo.stem[:40], alvo, "atalho"))
    return achados


def _em_pasta_de_jogo(caminho: str) -> bool:
    baixo = caminho.lower()
    if "steamapps" in baixo:
        return True
    return any(baixo.startswith(str(raiz).lower()) for raiz in _raizes())


def scan(ja_tenho: list[str] | None = None) -> list[Achado]:
    """Todos os jogos encontrados, sem os que ja' estao na lista do usuario.

    A ordem das fontes importa: o Steam sabe o nome de verdade do jogo
    ("Battlefield™ 6"), a pasta so' sabe como a pasta se chama. Quem chega
    primeiro fica com a vaga.
    """
    conhecidos = {str(p).lower() for p in (ja_tenho or [])}
    # O mesmo jogo chega por mais de um caminho: o Steam acha o executavel, e a
    # area de trabalho acha o atalho .url que abre o mesmo jogo. Sao caminhos
    # diferentes, entao so' comparar caminho deixava a lista com tudo em dobro.
    nomes_conhecidos = {_normal(Path(p).stem) for p in (ja_tenho or [])}
    vistos: set[str] = set()
    nomes_vistos: set[str] = set()
    saida: list[Achado] = []

    for fonte in (_do_steam, _da_area_de_trabalho, _das_pastas):
        try:
            achados = fonte()
        except OSError as e:
            _log.warning("varredura %s falhou: %s", fonte.__name__, e)
            continue
        for achado in achados:
            chave = achado.path.lower()
            nome = _normal(achado.name)
            if chave in conhecidos or chave in vistos:
                continue
            if nome and (nome in nomes_vistos or nome in nomes_conhecidos):
                continue
            vistos.add(chave)
            if nome:
                nomes_vistos.add(nome)
            saida.append(achado)

    saida.sort(key=lambda a: a.name.lower())
    return saida
