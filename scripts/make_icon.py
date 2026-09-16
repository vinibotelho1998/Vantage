"""Gera assets/icon.ico e assets/icon.png com o tema do Vantage (barras de performance)."""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS = 4
S = 256 * SS

BARS = [(88, 166, 255), (188, 140, 255), (63, 185, 80), (210, 153, 34)]
TOP = (28, 34, 46)
BOT = (10, 13, 19)


def _bg() -> Image.Image:
    grad = Image.new("RGB", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)],
                fill=tuple(int(TOP[i] + (BOT[i] - TOP[i]) * t) for i in range(3)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [S * 0.05, S * 0.05, S * 0.95, S * 0.95], radius=int(S * 0.23), fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def _bars() -> Image.Image:
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    n = len(BARS)
    mx = S * 0.20
    gap = S * 0.05
    bw = (S - 2 * mx - gap * (n - 1)) / n
    base = S * 0.76
    top_lim = S * 0.24
    frac = [0.5, 0.78, 1.0, 0.62]
    for i, c in enumerate(BARS):
        x0 = mx + i * (bw + gap)
        x1 = x0 + bw
        y0 = base - frac[i] * (base - top_lim)
        d.rounded_rectangle([x0, y0, x1, base], radius=bw * 0.42, fill=c + (255,))
        d.rounded_rectangle([x0, y0, x1, y0 + bw * 0.7], radius=bw * 0.42, fill=(255, 255, 255, 60))
    return layer


def main() -> None:
    img = _bg()
    bars = _bars()
    glow = bars.filter(ImageFilter.GaussianBlur(S * 0.018))
    img = Image.alpha_composite(img, glow)
    img = Image.alpha_composite(img, bars)
    ImageDraw.Draw(img).rounded_rectangle(
        [S * 0.05, S * 0.05, S * 0.95, S * 0.95], radius=int(S * 0.23),
        outline=(64, 72, 84, 180), width=max(1, int(S * 0.006)))

    icon = img.resize((256, 256), Image.LANCZOS)
    out_dir = os.path.join(ROOT, "assets")
    os.makedirs(out_dir, exist_ok=True)
    icon.save(os.path.join(out_dir, "icon.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(os.path.join(out_dir, "icon.png"))
    print("icone gerado em", out_dir)


if __name__ == "__main__":
    main()
