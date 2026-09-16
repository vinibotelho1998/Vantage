"""Desenha as imagens do assistente de instalacao a partir do tema do app.

O Inno Setup so' aceita BMP, e pede varios tamanhos para dar conta de tela com
escala alta. Gerar aqui, com as mesmas cores e o mesmo tracado do painel, e' o
que faz o instalador parecer parte do produto em vez de um wizard generico.

    python scripts/make_installer_art.py

Os .bmp ficam versionados: assim compilar o instalador (inclusive no CI, que nao
tem sessao grafica) nao depende de renderizar nada na hora.
"""
from __future__ import annotations

import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "windows"   # offscreen nao tem fonte real: texto vira caixinha
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage import theme  # noqa: E402

MARCA = "Vantage"
"""Nome exibido no instalador."""

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONE = os.path.join(RAIZ, "assets", "icon.png")

# Tamanhos que o Inno Setup procura (100%, 125%, 150%, 175%+ de escala).
GRANDES = ((164, 314), (192, 386), (246, 459), (273, 556))
PEQUENAS = ((55, 55), (64, 68), (83, 80), (92, 97))


def _fundo(p: QPainter, w: int, h: int) -> None:
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor("#0B1220"))
    grad.setColorAt(0.55, QColor(theme.BG))
    grad.setColorAt(1.0, QColor("#0A1A22"))
    p.fillRect(0, 0, w, h, grad)


def _brilho(p: QPainter, centro: QPointF, raio: float, cor: str, forca: int) -> None:
    """Halo suave. E' o que tira o ar de fundo chapado sem poluir o desenho."""
    grad = QRadialGradient(centro, raio)
    c0, c1 = QColor(cor), QColor(cor)
    c0.setAlpha(forca)
    c1.setAlpha(0)
    grad.setColorAt(0.0, c0)
    grad.setColorAt(1.0, c1)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawEllipse(centro, raio, raio)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _icone(p: QPainter, rect: QRectF) -> bool:
    """Desenha o icone do proprio app; sem ele o instalador vira generico."""
    if not os.path.exists(ICONE):
        return False
    pix = QPixmap(ICONE)
    if pix.isNull():
        return False
    lado = int(min(rect.width(), rect.height()))
    pix = pix.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    p.drawPixmap(int(rect.center().x() - pix.width() / 2),
                 int(rect.center().y() - pix.height() / 2), pix)
    return True


def _grade(p: QPainter, w: int, h: int, passo: int) -> None:
    p.setPen(QPen(QColor(theme.LINE), 1))
    for x in range(0, w, passo):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, passo):
        p.drawLine(0, y, w, y)


def _curva(p: QPainter, rect: QRectF, cor: str, fase: float, amplitude: float,
           largura: float) -> None:
    """Uma linha de desempenho, igual as do painel: suave, com brilho e area."""
    caminho = QPainterPath()
    pontos = 90
    for i in range(pontos + 1):
        t = i / pontos
        x = rect.left() + t * rect.width()
        onda = (math.sin(t * 6.0 + fase) * 0.55
                + math.sin(t * 13.0 + fase * 1.7) * 0.28
                + math.sin(t * 23.0 + fase * 2.3) * 0.17)
        y = rect.center().y() - onda * amplitude
        if i == 0:
            caminho.moveTo(x, y)
        else:
            caminho.lineTo(x, y)

    area = QPainterPath(caminho)
    area.lineTo(rect.right(), rect.bottom())
    area.lineTo(rect.left(), rect.bottom())
    area.closeSubpath()
    grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
    c0, c1 = QColor(cor), QColor(cor)
    c0.setAlpha(70)
    c1.setAlpha(0)
    grad.setColorAt(0.0, c0)
    grad.setColorAt(1.0, c1)
    p.fillPath(area, grad)

    brilho = QColor(cor)
    brilho.setAlpha(60)
    p.setPen(QPen(brilho, largura * 3.0, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(caminho)
    p.setPen(QPen(QColor(cor), largura, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(caminho)


def imagem_grande(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing
                     | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)
    escala = w / 164.0
    _fundo(p, w, h)
    _grade(p, w, h, int(16 * escala))
    _brilho(p, QPointF(w * 0.5, h * 0.20), w * 0.85, theme.FPS, 46)

    icone = QRectF(w * 0.5 - w * 0.21, h * 0.09, w * 0.42, w * 0.42)
    if not _icone(p, icone):
        p.setFont(QFont("Segoe UI", int(20 * escala), QFont.Weight.Bold))
        p.setPen(QColor(theme.TXT))
        p.drawText(icone, int(Qt.AlignmentFlag.AlignCenter), "V")

    topo = icone.bottom() + h * 0.035
    p.setFont(QFont("Segoe UI", int(13 * escala), QFont.Weight.Bold))
    p.setPen(QColor(theme.TXT))
    p.drawText(QRectF(0, topo, w, h * 0.075),
               int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter), MARCA)

    p.setPen(QPen(QColor(theme.FPS), max(1.0, 1.6 * escala)))
    meio = w * 0.5
    p.drawLine(QPointF(meio - w * 0.13, topo + h * 0.082),
               QPointF(meio + w * 0.13, topo + h * 0.082))

    faixa = QRectF(-w * 0.1, h * 0.52, w * 1.2, h * 0.20)
    _curva(p, faixa, theme.GPU, 2.1, h * 0.050, 1.6 * escala)
    faixa.moveTop(h * 0.63)
    _curva(p, faixa, theme.CPU, 0.7, h * 0.062, 1.8 * escala)
    faixa.moveTop(h * 0.74)
    _curva(p, faixa, theme.FPS, 0.0, h * 0.075, 2.3 * escala)

    p.setFont(QFont("Segoe UI", int(7 * escala), QFont.Weight.Normal))
    p.setPen(QColor(theme.MUTE))
    p.drawText(QRectF(0, h * 0.915, w, h * 0.06),
               int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
               "FPS  ·  1% low  ·  sensores  ·  telas")
    p.end()
    return img


def imagem_pequena(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing
                     | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)
    _fundo(p, w, h)
    _brilho(p, QPointF(w * 0.5, h * 0.45), w * 0.7, theme.FPS, 40)
    if not _icone(p, QRectF(w * 0.13, h * 0.13, w * 0.74, h * 0.74)):
        p.setFont(QFont("Segoe UI", int(13 * (w / 55.0)), QFont.Weight.Bold))
        p.setPen(QColor(theme.TXT))
        p.drawText(QRectF(0, 0, w, h), int(Qt.AlignmentFlag.AlignCenter), "V")
    p.end()
    return img


def main() -> int:
    QApplication(sys.argv)
    destino = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "packaging", "assets")
    os.makedirs(destino, exist_ok=True)

    for i, (w, h) in enumerate(GRANDES):
        nome = "wizard.bmp" if i == 0 else f"wizard-{i}.bmp"
        imagem_grande(w, h).save(os.path.join(destino, nome), "BMP")
        print(f"  {nome:20} {w}x{h}")
    for i, (w, h) in enumerate(PEQUENAS):
        nome = "wizard-small.bmp" if i == 0 else f"wizard-small-{i}.bmp"
        imagem_pequena(w, h).save(os.path.join(destino, nome), "BMP")
        print(f"  {nome:20} {w}x{h}")
    print(f"arte do instalador em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
