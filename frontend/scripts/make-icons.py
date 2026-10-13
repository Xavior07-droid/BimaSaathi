"""Generates the BimaSaathi app icons (F26). Run from frontend/:  python3 scripts/make-icons.py
Needs Pillow (pip install pillow). Output goes to public/icons/ and public/.
Design: trust-teal tile, white shield, teal check mark."""
from PIL import Image, ImageDraw
from pathlib import Path

TEAL = (23, 100, 95, 255)   # brand-700 #17645f
WHITE = (255, 255, 255, 255)
SS = 4                      # supersampling factor for smooth edges
OUT = Path(__file__).resolve().parent.parent / "public"


def cubic(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def shield_points():
    """Shield outline in a 0..1 box (width 1, height 1)."""
    right = cubic((1.0, 0.16), (1.0, 0.62), (0.78, 0.86), (0.5, 1.0))
    left = [(1 - x, y) for x, y in reversed(right)]
    return [(0.0, 0.16), (0.5, 0.0), (1.0, 0.16)] + right[1:] + left[1:]


CHECK = [(0.27, 0.52), (0.43, 0.68), (0.74, 0.33)]


def draw_icon(size, shield_h, rounded):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=TEAL)
    else:
        d.rectangle([0, 0, s, s], fill=TEAL)
    h = s * shield_h
    w = h * 0.86
    x0, y0 = (s - w) / 2, (s - h) / 2 + h * 0.01
    pts = [(x0 + x * w, y0 + y * h) for x, y in shield_points()]
    d.polygon(pts, fill=WHITE)
    lw = w * 0.1
    chk = [(x0 + x * w, y0 + y * h) for x, y in CHECK]
    d.line(chk, fill=TEAL, width=int(lw), joint="curve")
    for cx, cy in (chk[0], chk[-1]):
        d.ellipse([cx - lw / 2, cy - lw / 2, cx + lw / 2, cy + lw / 2], fill=TEAL)
    return img.resize((size, size), Image.LANCZOS)


def svg():
    pts = " ".join(f"{x * 86 + 7:.2f},{y * 100 + 0:.2f}" for x, y in shield_points())
    chk = " ".join(f"{x * 86 + 7:.2f},{y * 100:.2f}" for x, y in CHECK)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-14 -14 128 128">'
        '<rect x="-14" y="-14" width="128" height="128" rx="28" fill="#17645f"/>'
        f'<polygon points="{pts}" fill="#fff" transform="translate(0 0)"/>'
        f'<polyline points="{chk}" fill="none" stroke="#17645f" stroke-width="8.6" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>\n"
    )


(OUT / "icons").mkdir(parents=True, exist_ok=True)
draw_icon(192, 0.64, True).save(OUT / "icons/icon-192.png")
draw_icon(512, 0.64, True).save(OUT / "icons/icon-512.png")
# Maskable: full-bleed tile, artwork kept inside the central 80% "safe zone" so any mask shape works.
draw_icon(512, 0.5, False).save(OUT / "icons/icon-maskable-512.png")
draw_icon(180, 0.58, False).save(OUT / "icons/apple-touch-icon.png")  # iOS rounds the corners itself
draw_icon(32, 0.7, True).save(OUT / "icons/favicon-32.png")
draw_icon(256, 0.7, True).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
(OUT / "icons/icon.svg").write_text(svg(), encoding="utf-8")
print("icons written to", OUT)
