#!/usr/bin/env python3
"""生成 app/ui/app.ico（深紫底 + 紫荆花五瓣）。"""
from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

SIZE = 512


def rounded_bg(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(1, size - 1)
        gd.line([(0, y), (size, y)], fill=(int(38 + 58 * t), int(40 - 8 * t), int(72 + 24 * t), 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(size * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    return img


def flower(img, size):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = size * 0.5, size * 0.5
    R, petals = size * 0.315, 5
    for i in range(petals):
        a = -math.pi / 2 + i * 2 * math.pi / petals
        px, py = cx + R * math.cos(a), cy + R * math.sin(a)
        pr = size * 0.185
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(255, 92, 122, 255))
        d.ellipse([px - pr * 0.72, py - pr * 0.82, px + pr * 0.5, py + pr * 0.4],
                  fill=(255, 150, 170, 255))
    cr = size * 0.085
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(255, 226, 122, 255))
    d.ellipse([cx - cr * 0.5, cy - cr * 0.5, cx + cr * 0.5, cy + cr * 0.5], fill=(255, 248, 214, 255))
    img.alpha_composite(layer)
    return img


def make_png(path, size):
    img = rounded_bg(size)
    flower(img, size)
    img.save(path)


def main():
    out = os.path.join(common.UI, "app.ico")
    os.makedirs(common.UI, exist_ok=True)
    img = rounded_bg(SIZE)
    flower(img, SIZE)
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon ->", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
