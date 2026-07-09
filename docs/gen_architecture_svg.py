"""Génère le schéma d'architecture Niveau 1 (Docker Compose) en SVG + PNG.

Source unique de vérité pour la figure de la partie 7 du rendu écrit.
Les deux fichiers sont produits à partir des mêmes coordonnées afin de rester
parfaitement cohérents (SVG vectoriel pour Word, PNG en repli).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 700

# Palette sobre, cohérente avec un rendu académique.
COL = {
    "svc": ("#E8F0FE", "#3B6FB0"),      # services applicatifs (bleu)
    "data": ("#E6F4EA", "#2E7D46"),     # stockage / données (vert)
    "mon": ("#FEF3E0", "#C9760E"),      # supervision (orange)
    "ext": ("#EEEEEE", "#666666"),      # externe / artefacts (gris)
}
TXT = "#1A1A1A"
SUB = "#555555"
ARROW = "#444444"

# id: (x, y, w, h, kind, title, subtitle)
NODES = {
    "etl":      (70, 105, 165, 58, "svc", "etl", "Bronze → Silver/Gold"),
    "parquet":  (360, 105, 205, 58, "data", "Silver / Gold", "(Parquet)"),
    "trainer":  (690, 105, 165, 58, "svc", "trainer", "entraînement ML"),
    "models":   (690, 212, 165, 52, "ext", "models-store", "(joblib)"),
    "postgres": (70, 312, 165, 78, "data", "postgres", "capteurs + prédictions"),
    "api":      (360, 312, 205, 78, "svc", "api (FastAPI)", "3 modèles ML"),
    "prom":     (690, 320, 165, 60, "mon", "prometheus", "métriques"),
    "grafana":  (360, 468, 205, 60, "mon", "grafana", "tableaux de bord"),
    "user":     (360, 600, 205, 56, "ext", "Utilisateur métier", ""),
}

# (src, dst, label, dashed, src_side, dst_side)
EDGES = [
    ("etl", "parquet", "", False, "R", "L"),
    ("parquet", "trainer", "", False, "R", "L"),
    ("trainer", "models", "", False, "B", "T"),
    ("models", "api", "charge", False, "B", "T"),
    ("etl", "postgres", "INSERT capteurs", False, "B", "T"),
    ("api", "postgres", "INSERT prédictions", False, "L", "R"),
    ("prom", "api", "scrape /metrics", True, "L", "R"),
    ("grafana", "prom", "PromQL", False, "R", "B"),
    ("grafana", "postgres", "SQL", False, "L", "B"),
    ("grafana", "user", "port 3000 (seul exposé)", False, "B", "T"),
]

CONTAINER = (30, 60, 895, 555)  # x0,y0,x1,y1  réseau mecha-net


def side_point(n, side):
    x, y, w, h, *_ = NODES[n]
    if side == "L":
        return (x, y + h / 2)
    if side == "R":
        return (x + w, y + h / 2)
    if side == "T":
        return (x + w / 2, y)
    return (x + w / 2, y + h)  # B


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
def build_svg() -> str:
    s = []
    s.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Arial, Helvetica, sans-serif">'
    )
    s.append(
        '<defs><marker id="ah" markerWidth="9" markerHeight="9" refX="7" refY="3" '
        'orient="auto" markerUnits="userSpaceOnUse">'
        f'<path d="M0,0 L7,3 L0,6 Z" fill="{ARROW}"/></marker></defs>'
    )
    s.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>')

    cx0, cy0, cx1, cy1 = CONTAINER
    s.append(
        f'<rect x="{cx0}" y="{cy0}" width="{cx1 - cx0}" height="{cy1 - cy0}" rx="12" '
        f'fill="#FAFBFC" stroke="#9AA7B4" stroke-width="1.5" stroke-dasharray="7 5"/>'
    )
    s.append(
        f'<text x="{cx0 + 14}" y="{cy0 + 22}" font-size="14" font-weight="bold" '
        f'fill="{SUB}">Réseau Docker interne · mecha-net</text>'
    )

    # edges first (under boxes)
    for src, dst, label, dashed, ss, ds in EDGES:
        x1, y1 = side_point(src, ss)
        x2, y2 = side_point(dst, ds)
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        s.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            f'stroke="{ARROW}" stroke-width="1.6"{dash} marker-end="url(#ah)"/>'
        )
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            tw = len(label) * 6.2 + 8
            s.append(
                f'<rect x="{mx - tw / 2:.0f}" y="{my - 9:.0f}" width="{tw:.0f}" height="16" '
                f'rx="3" fill="#FFFFFF" opacity="0.92"/>'
            )
            s.append(
                f'<text x="{mx:.0f}" y="{my + 3:.0f}" font-size="11" fill="{SUB}" '
                f'text-anchor="middle">{label}</text>'
            )

    # nodes
    for n, (x, y, w, h, kind, title, sub) in NODES.items():
        fill, stroke = COL[kind]
        s.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>'
        )
        if sub:
            s.append(
                f'<text x="{x + w / 2:.0f}" y="{y + h / 2 - 3:.0f}" font-size="14" '
                f'font-weight="bold" fill="{TXT}" text-anchor="middle">{title}</text>'
            )
            s.append(
                f'<text x="{x + w / 2:.0f}" y="{y + h / 2 + 14:.0f}" font-size="11" '
                f'fill="{SUB}" text-anchor="middle">{sub}</text>'
            )
        else:
            s.append(
                f'<text x="{x + w / 2:.0f}" y="{y + h / 2 + 5:.0f}" font-size="14" '
                f'font-weight="bold" fill="{TXT}" text-anchor="middle">{title}</text>'
            )
    s.append("</svg>")
    return "\n".join(s)


# --------------------------------------------------------------------------- #
# PNG (repli) via PIL — mêmes coordonnées, échelle x2
# --------------------------------------------------------------------------- #
def build_png(path: Path, scale: int = 2):
    img = Image.new("RGB", (W * scale, H * scale), "white")
    d = ImageDraw.Draw(img)

    def font(sz, bold=False):
        name = "arialbd.ttf" if bold else "arial.ttf"
        try:
            return ImageFont.truetype(name, sz * scale)
        except OSError:
            return ImageFont.load_default()

    def hx(c):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

    def sc(v):
        return v * scale

    def rrect(x, y, w, h, fill, stroke, sw=2, dash=False):
        d.rounded_rectangle(
            [sc(x), sc(y), sc(x + w), sc(y + h)], radius=9 * scale,
            fill=hx(fill) if fill else None, outline=hx(stroke), width=sw * scale,
        )

    def ctext(x, y, t, sz, color, bold=False, anchor="mm"):
        d.text((sc(x), sc(y)), t, font=font(sz, bold), fill=hx(color), anchor=anchor)

    def arrow(x1, y1, x2, y2, dashed=False):
        col = hx(ARROW)
        if dashed:
            seg, gap = 6, 4
            tot = math.hypot(x2 - x1, y2 - y1)
            n = max(1, int(tot / (seg + gap)))
            for i in range(n):
                t0 = i * (seg + gap) / tot
                t1 = min(1, (i * (seg + gap) + seg) / tot)
                d.line(
                    [sc(x1 + (x2 - x1) * t0), sc(y1 + (y2 - y1) * t0),
                     sc(x1 + (x2 - x1) * t1), sc(y1 + (y2 - y1) * t1)],
                    fill=col, width=2 * scale,
                )
        else:
            d.line([sc(x1), sc(y1), sc(x2), sc(y2)], fill=col, width=2 * scale)
        ang = math.atan2(y2 - y1, x2 - x1)
        L = 9
        p1 = (x2, y2)
        p2 = (x2 - L * math.cos(ang - 0.4), y2 - L * math.sin(ang - 0.4))
        p3 = (x2 - L * math.cos(ang + 0.4), y2 - L * math.sin(ang + 0.4))
        d.polygon([sc(p1[0]), sc(p1[1]), sc(p2[0]), sc(p2[1]), sc(p3[0]), sc(p3[1])], fill=col)

    cx0, cy0, cx1, cy1 = CONTAINER
    # dashed container (approx with rectangle outline)
    d.rounded_rectangle(
        [sc(cx0), sc(cy0), sc(cx1), sc(cy1)], radius=12 * scale,
        fill=hx("#FAFBFC"), outline=hx("#9AA7B4"), width=2 * scale,
    )
    ctext(cx0 + 14, cy0 + 14, "Réseau Docker interne · mecha-net", 13, SUB, True, "lm")

    for src, dst, label, dashed, ss, ds in EDGES:
        x1, y1 = side_point(src, ss)
        x2, y2 = side_point(dst, ds)
        arrow(x1, y1, x2, y2, dashed)
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            tw = len(label) * 6.4 + 8
            d.rectangle([sc(mx - tw / 2), sc(my - 9), sc(mx + tw / 2), sc(my + 8)], fill="white")
            ctext(mx, my, label, 10, SUB, False, "mm")

    for n, (x, y, w, h, kind, title, sub) in NODES.items():
        fill, stroke = COL[kind]
        rrect(x, y, w, h, fill, stroke)
        if sub:
            ctext(x + w / 2, y + h / 2 - 9, title, 13, TXT, True, "mm")
            ctext(x + w / 2, y + h / 2 + 11, sub, 10, SUB, False, "mm")
        else:
            ctext(x + w / 2, y + h / 2, title, 13, TXT, True, "mm")

    img.save(path, "PNG")


if __name__ == "__main__":
    out = Path(__file__).parent
    (out / "architecture_niveau1.svg").write_text(build_svg(), encoding="utf-8")
    build_png(out / "architecture_niveau1.png")
    print("OK: architecture_niveau1.svg + .png générés")
