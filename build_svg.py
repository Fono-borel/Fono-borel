#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_svg.py — Générateur modulaire du hero banner "profile.sh --live".

Reproduit fidèlement le design de dark.svg :

  ┌──────────────────────────── fenêtre terminal ────────────────────────────┐
  │  ● ● ●        <email> - % ./profile.sh --live                            │
  │ ┌── VISUAL.MAP ──┐   SYSTEM.INFO ───────────────────────────  ● LIVE     │
  │ │  portrait      │   ┌ badge email ┐                                     │
  │ │  pixel-art     │   Subject ....... Nom                                 │
  │ │  (dissolve +   │   Role .......... ...                                 │
  │ │   glitch loop  │   ...                                                 │
  │ │   + morph  <>) │   - Contact ------------------------------            │
  │ └────────────────┘   Grid.Mail ..... <email>                            │
  │              ▸ Full profile below in README ↓ █                          │
  └─────────────────────────────────────────────────────────────────────────┘

Pipeline portrait :
  image -> niveaux de gris -> recadrage ratio -> autocontraste -> gamma/contraste
        -> tramage Floyd–Steinberg (1 bit) -> pixels "encre" (zones sombres)
        -> 3 calques SVG :
             1. intro    : dissolve — N paquets de pixels dispersés, fondu échelonné
             2. boucle   : glitch  — tuiles spatiales qui se décalent vers le centre
             3. particules : nuage <use> qui morphe la silhouette en 3 glyphes
                             successifs (< , </> , ▲) puis revient — le
                             « défilement d'images » de l'original

Tout le contenu (identité, lignes du panneau, couleurs, géométrie, timings) est
dans les dataclasses de configuration plus bas. Le CLI permet des retouches
rapides sans éditer le fichier.

Dépendance : Pillow  (pip install pillow)

Exemples
--------
    python build_svg.py                         # régénère dark.svg
    python build_svg.py --out dark.svg --seed 7
    python build_svg.py --gamma 1.3 --contrast 1.15   # portrait plus clair
    python build_svg.py --name "Jane Doe" --email jane@doe.dev
"""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image, ImageEnhance, ImageOps
except ImportError:  # pragma: no cover
    raise SystemExit("Pillow requis :  pip install pillow")


# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Theme:
    """Palette. Tous les éléments graphiques passent par ici."""
    bg_outer:     str = "#070B16"
    panel_top:    str = "#0A101F"
    panel_bot:    str = "#0C1426"
    titlebar:     str = "#0B1222"
    hairline:     str = "rgba(255,255,255,0.10)"
    dot_red:      str = "#ff5f56"
    dot_amber:    str = "#ffbd2e"
    dot_green:    str = "#27c93f"
    muted:        str = "#94A3B8"
    faint:        str = "#475569"
    cyan:         str = "#22D3EE"
    ink:          str = "#A78BFA"   # couleur du portrait pixel-art
    panel_inner:  str = "#0A101F"
    value:        str = "#F8FAFC"
    leader:       str = "rgba(148,163,184,0.35)"
    badge_bg:     str = "#4C1D95"
    badge_fg:     str = "#E9D5FF"
    live:         str = "#F87171"
    # dégradé d'accent (bordure animée)
    accent_stops: tuple[str, str, str] = ("#7C3AED", "#22D3EE", "#10B981")
    ascii_stops:  tuple[str, str, str] = ("#60A5FA", "#A78BFA", "#22D3EE")


@dataclass
class Layout:
    """Géométrie. Les valeurs par défaut reproduisent dark.svg au pixel près."""
    width:  int = 1180
    height: int = 610
    win_x: int = 2
    win_y: int = 2
    win_w: int = 1176
    win_h: int = 606
    win_rx: int = 18
    titlebar_h: int = 46

    # panneau gauche (VISUAL.MAP)
    lp_x: int = 36
    lp_y: int = 84
    lp_w: int = 400
    lp_h: int = 492
    lp_rx: int = 10
    lp_pad_x: int = 14           # marge interne horizontale
    lp_pad_y: int = 2            # marge interne verticale

    # grille du portrait (unités locales, avant scale)
    grid_w: int = 300
    grid_h: int = 340
    top_margin: int = 18         # bandeau vide au-dessus de la tête

    # panneau droit (SYSTEM.INFO)
    rp_x: int = 470
    rp_row_len: int = 655        # largeur forcée de chaque ligne (textLength)
    rp_y0: int = 162             # y de la 1re ligne d'info
    rp_step: int = 23            # interligne
    rp_divider_gap: int = 16     # espace supplémentaire avant "- Contact -"
    rp_total_chars: int = 76     # gabarit pour calculer les points de conduite

    @property
    def scale_x(self) -> float:
        return (self.lp_w - 2 * self.lp_pad_x) / self.grid_w

    @property
    def scale_y(self) -> float:
        return (self.lp_h - 2 * self.lp_pad_y) / self.grid_h

    @property
    def portrait_tx(self) -> int:
        return self.lp_x + self.lp_pad_x

    @property
    def portrait_ty(self) -> int:
        return self.lp_y + self.lp_pad_y


@dataclass
class Anim:
    """Minutage des animations SMIL."""
    # dissolve d'intro
    intro_bands: int = 60
    intro_cell: int = 3          # taille des amas mélangés dans le dissolve
    intro_start: float = 0.20
    intro_stagger: float = 0.0334
    intro_dur: float = 0.9
    # boucle glitch (portrait + particules)
    cycle_dur: float = 13.9
    cycle_begin: float = 3.2
    key_times: str = "0.000;0.194;0.288;0.432;0.525;0.669;0.763;0.906;1.000"
    tile: int = 30               # taille d'une tuile glitch (unités locales)
    implode: float = 0.45        # fraction du vecteur tuile→centre
    implode_jitter: int = 6
    # nuage de particules : la silhouette se disloque puis se recompose en
    # 3 glyphes successifs avant de revenir au visage.
    particle_count: int = 1300
    particle_w: float = 2.4
    particle_h: float = 1.7
    morph_glyphs: tuple[str, ...] = ("padlock", "code_tags", "terminal")
    # Chaque glyphe est COMPACT et centré (placement dans _glyph_def, calé sur
    # les proportions de l'original) : 900 points dans une petite surface =
    # points denses, traits épais. Les 3 formes se superposent au centre ->
    # transitions courtes -> morph très fluide. Bijection + 2-opt (trajet mini).
    morph_scale: float = 1.0        # multiplicateur global de la taille des glyphes
    morph_rows: int = 36            # bandes du balayage serpentin (init appariement)
    morph_opt_passes: int = 150     # passes de 2-opt pour raccourcir les trajets
    morph_jitter: float = 0.006     # bruit sur les cibles (fraction de la largeur)
    morph_thickness: float = 0.085  # épaisseur des traits de glyphe (fraction bbox glyphe)
    # panneau droit
    rp_begin0: float = 0.90
    rp_begin_step: float = 0.12
    rp_row_dur: float = 0.4
    footer_begin: float = 3.34


@dataclass
class Row:
    """Une ligne du panneau droit."""
    label: str
    value: str = ""
    kind: str = "kv"             # "kv" | "divider"


@dataclass
class Profile:
    """Contenu éditable de la carte."""
    name: str = "Borel Fono"
    email: str = "fonoborel@gmail.com"
    title_cmd: str = "% ./profile.sh --live"
    left_label: str = "VISUAL.MAP"
    right_label: str = "SYSTEM.INFO"
    footer: str = "Full profile, tooling & write-ups below in README"
    info_rows: list[Row] = field(default_factory=lambda: [
        Row("Subject",       "Borel Fono"),
        Row("Role",          "Security Engineer — Full-Spectrum"),
        Row("Origin",        "Remote — Worldwide"),
        Row("Clearance",     "Offensive + Defensive Ops"),
        Row("Status",        "Break · Harden · Automate"),
        Row("Core.Offense",  "Burp, Cobalt Strike, BloodHound, Sliver"),
        Row("Core.Defense",  "Splunk, Wazuh, Sigma, YARA, Velociraptor"),
        Row("Core.Cloud",    "AWS, GCP"),
        Row("Core.Lang",     "Python, Bash, C"),
        Row("Core.AppSec",   "Threat modeling, SAST/DAST, secure SDLC"),
    ])
    contact_rows: list[Row] = field(default_factory=lambda: [
        Row("- Contact", kind="divider"),
        Row("Grid.Mail",     "fonoborel@gmail.com"),
        Row("Grid.Site",     "coming soon"),
        Row("Grid.LinkedIn", "borel-fono"),
        Row("Grid.GitHub",   "@borelfono"),
        Row("Grid.X",        "@borelfono"),
    ])

    @property
    def rows(self) -> list[Row]:
        return self.info_rows + self.contact_rows


_HERE = Path(__file__).resolve().parent
DEFAULT_IMAGE = str(_HERE / "assets" / "profile.jpg")   # photo vendue dans le repo


# ──────────────────────────────────────────────────────────────────────────────
#  PORTRAIT :  image  ->  pixels "encre"
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class PortraitOpts:
    # L'encre suit les tons CLAIRS (fond, peau, chemise) ; les tons très
    # sombres (cheveux, costume, cravate) deviennent du vide -> silhouette
    # en négatif tramé, comme l'original.
    contrast: float = 1.20
    gamma: float = 1.90
    brightness: float = 1.0
    threshold_bias: int = -30     # <0 => moins d'encre
    dither: bool = True
    autocontrast_cutoff: int = 1
    invert: bool = True           # True => encre = clair ; False => encre = sombre
    vignette: float = 0.40        # 0..1, assombrit les bords (allège le fond)


def build_ink_pixels(image_path: str, layout: Layout, opts: PortraitOpts) -> set[tuple[int, int]]:
    """Renvoie l'ensemble des (x, y) sombres, en unités de grille locales."""
    content_h = layout.grid_h - layout.top_margin
    target_ar = layout.grid_w / content_h

    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("L")
    w, h = img.size
    ar = w / h
    if ar > target_ar:                                   # trop large -> rogner les côtés
        nw = int(round(h * target_ar))
        x0 = (w - nw) // 2
        img = img.crop((x0, 0, x0 + nw, h))
    else:                                                # trop haut -> garder le haut (tête)
        nh = int(round(w / target_ar))
        img = img.crop((0, 0, w, nh))

    img = img.resize((layout.grid_w, content_h), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=opts.autocontrast_cutoff)
    if opts.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(opts.contrast)
    if opts.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(opts.brightness)
    if opts.gamma != 1.0:
        lut = [min(255, int(round((i / 255) ** opts.gamma * 255))) for i in range(256)]
        img = img.point(lut)
    if opts.vignette > 0:
        img = _apply_vignette(img, opts.vignette)
    if opts.threshold_bias:
        b = opts.threshold_bias
        img = img.point(lambda v: max(0, min(255, v + b)))

    bw = img.convert("1") if opts.dither else img.point(lambda v: 255 if v > 128 else 0, mode="1")
    px = bw.load()

    # invert=True  -> encre = pixels clairs (255) ; sinon encre = pixels sombres (0)
    ink_val = 255 if opts.invert else 0
    off = layout.top_margin
    ink: set[tuple[int, int]] = set()
    for y in range(content_h):
        for x in range(layout.grid_w):
            if px[x, y] == ink_val:
                ink.add((x, y + off))
    return ink


def _apply_vignette(img: "Image.Image", strength: float) -> "Image.Image":
    w, h = img.size
    cx, cy = w / 2, h / 2
    maxd = (cx ** 2 + cy ** 2) ** 0.5
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            f = 1.0 - strength * (d ** 2)
            px[x, y] = max(0, min(255, int(px[x, y] * f)))
    return img


# ──────────────────────────────────────────────────────────────────────────────
#  Fusion de pixels en "d" de <path>  (rectangles 1x1 fusionnés par ligne)
# ──────────────────────────────────────────────────────────────────────────────
def pixels_to_path_d(pixels: Iterable[tuple[int, int]]) -> str:
    rows: dict[int, list[int]] = {}
    for x, y in pixels:
        rows.setdefault(y, []).append(x)
    out: list[str] = []
    for y in sorted(rows):
        xs = sorted(rows[y])
        start = prev = xs[0]
        for x in xs[1:]:
            if x == prev + 1:
                prev = x
            else:
                n = prev - start + 1
                out.append(f"M{start} {y}h{n}v1h-{n}z")
                start = prev = x
        n = prev - start + 1
        out.append(f"M{start} {y}h{n}v1h-{n}z")
    return "".join(out)


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers XML
# ──────────────────────────────────────────────────────────────────────────────
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def portrait_group_open(layout: Layout, theme: Theme, extra: str = "") -> str:
    return (f'<g transform="translate({layout.portrait_tx},{layout.portrait_ty}) '
            f'scale({layout.scale_x:.4f},{layout.scale_y:.4f})" '
            f'fill="{theme.ink}" shape-rendering="crispEdges"{extra}>')


# ──────────────────────────────────────────────────────────────────────────────
#  CALQUES DU PORTRAIT
# ──────────────────────────────────────────────────────────────────────────────
def build_intro(ink: set[tuple[int, int]], layout: Layout, anim: Anim,
                theme: Theme, rng: random.Random) -> list[str]:
    """Dissolve : N paquets de petits amas dispersés, fondu échelonné, puis masqué."""
    # On mélange des cellules (pas des pixels isolés) : le rendu reste un
    # "dissolve" aléatoire mais les runs horizontaux fusionnent -> SVG plus léger.
    cs = anim.intro_cell
    cells: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in ink:
        cells.setdefault((x // cs, y // cs), []).append((x, y))
    buckets = list(cells.values())
    rng.shuffle(buckets)

    bands = anim.intro_bands
    parts = [portrait_group_open(layout, theme)]
    parts.append(f'<set attributeName="opacity" to="0" begin="{anim.cycle_begin}s"/>')
    for i in range(bands):
        chunk = [p for bucket in buckets[i::bands] for p in bucket]
        if not chunk:
            continue
        begin = anim.intro_start + i * anim.intro_stagger
        d = pixels_to_path_d(chunk)
        parts.append(
            f'<g opacity="0"><animate attributeName="opacity" values="0;1" '
            f'dur="{anim.intro_dur}s" begin="{begin:.2f}s" fill="freeze" '
            f'calcMode="spline" keyTimes="0;1" keySplines=".4 0 .2 1"/>'
            f'<path d="{d}"/></g>'
        )
    parts.append("</g>")
    return parts


def build_glitch_loop(ink: set[tuple[int, int]], layout: Layout, anim: Anim,
                      theme: Theme, rng: random.Random) -> list[str]:
    """Boucle : tuiles spatiales qui disparaissent en implosant vers le centre."""
    tile = anim.tile
    tiles: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in ink:
        tiles.setdefault((x // tile, y // tile), []).append((x, y))

    cx = layout.grid_w / 2
    cy = layout.grid_h / 2
    kt = anim.key_times
    dur = anim.cycle_dur
    beg = anim.cycle_begin

    parts = [portrait_group_open(layout, theme, extra=' opacity="0"')]
    parts.append(f'<set attributeName="opacity" to="1" begin="{beg}s"/>')
    for _, pts in sorted(tiles.items()):
        tx = sum(p[0] for p in pts) / len(pts)
        ty = sum(p[1] for p in pts) / len(pts)
        dx = round((cx - tx) * anim.implode + rng.uniform(-anim.implode_jitter, anim.implode_jitter))
        dy = round((cy - ty) * anim.implode + rng.uniform(-anim.implode_jitter, anim.implode_jitter))
        v = f"{dx} {dy}"
        translate = f"0 0;0 0;{v};{v};{v};{v};{v};{v};0 0"
        d = pixels_to_path_d(pts)
        parts.append(
            f'<g opacity="1">'
            f'<animate attributeName="opacity" values="1;1;0;0;0;0;0;0;1" '
            f'keyTimes="{kt}" dur="{dur}s" begin="{beg}s" repeatCount="indefinite"/>'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="{translate}" keyTimes="{kt}" dur="{dur}s" begin="{beg}s" '
            f'repeatCount="indefinite"/>'
            f'<path d="{d}"/></g>'
        )
    parts.append("</g>")
    return parts


def _arc(cx: float, cy: float, r: float, a0: float, a1: float, n: int,
         w: float = 1.0) -> list[tuple]:
    """Segments approximant un arc de cercle (coords normalisées, y vers le bas)."""
    import math
    out = []
    for i in range(n):
        t0 = a0 + (a1 - a0) * i / n
        t1 = a0 + (a1 - a0) * (i + 1) / n
        out.append(((cx + r * math.cos(t0), cy + r * math.sin(t0)),
                    (cx + r * math.cos(t1), cy + r * math.sin(t1)), w))
    return out


def _disc(cx: float, cy: float, r: float, n: int = 16) -> list[tuple[float, float]]:
    """Polygone (n sommets) approximant un cercle plein."""
    import math
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def _rrect(x0: float, y0: float, x1: float, y1: float, c: float) -> list[tuple[float, float]]:
    """Polygone d'un rectangle à coins coupés (pseudo-arrondi)."""
    return [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1),
            (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)]


def _outline(poly: list[tuple[float, float]], w: float) -> list[tuple]:
    """Segments fermés reliant les sommets d'un polygone."""
    return [(poly[i], poly[(i + 1) % len(poly)], w) for i in range(len(poly))]


def _glyph_def(name: str):
    """(traits, remplissages, placement).

    - trait       : ((ax, ay), (bx, by), poids)                — poids = part de particules
    - remplissage : (polygone [(x, y), …], poids)              — zone échantillonnée en plein
    - placement   : (cx, cy, w, h) en fraction de la silhouette — compact & centré

    Défaut cyber / crypto / dev / linux :
      padlock (🔒) · code_tags (</>) · terminal (fenêtre >_).
    Autres : keyhole, key, shield, hash, chevron_left/right, triangle.
    """
    import math
    if name == "padlock":                                # 🔒  cadenas détaillé
        body = _rrect(0.14, 0.46, 0.86, 0.99, 0.10)
        strokes = _outline(body, 1.1)
        strokes += _arc(0.50, 0.46, 0.27, math.pi * 1.02, math.pi * 1.98, 20, 1.3)   # anse ext.
        strokes += _arc(0.50, 0.46, 0.17, math.pi * 1.04, math.pi * 1.96, 16, 1.1)   # anse int.
        strokes += _arc(0.50, 0.66, 0.075, 0.0, 2 * math.pi, 12, 1.0)                 # anneau serrure
        strokes += [((0.50, 0.70), (0.50, 0.88), 0.9)]                               # fente serrure
        return (strokes, [(body, 0.85)], (0.50, 0.47, 0.54, 0.74))
    if name == "terminal":                               # fenêtre de terminal  >_
        frame = _rrect(0.03, 0.12, 0.97, 0.90, 0.06)
        strokes = _outline(frame, 1.7)
        strokes += [((0.03, 0.27), (0.97, 0.27), 1.1)]                               # barre de titre
        strokes += _arc(0.09, 0.195, 0.020, 0, 2 * math.pi, 8, 0.5)                  # 3 pastilles
        strokes += _arc(0.15, 0.195, 0.020, 0, 2 * math.pi, 8, 0.5)
        strokes += _arc(0.21, 0.195, 0.020, 0, 2 * math.pi, 8, 0.5)
        strokes += [((0.12, 0.42), (0.34, 0.58), 1.3), ((0.34, 0.58), (0.12, 0.74), 1.3)]  # prompt >
        cursor = [(0.40, 0.49), (0.54, 0.49), (0.54, 0.71), (0.40, 0.71)]            # bloc curseur █
        strokes += _outline(cursor, 0.8)
        return (strokes, [(cursor, 1.0)], (0.50, 0.47, 0.84, 0.66))
    if name == "keyhole":                                # trou de serrure plein
        circ = _disc(0.50, 0.31, 0.18, 16)
        flare = [(0.42, 0.42), (0.32, 0.93), (0.68, 0.93), (0.58, 0.42)]
        strokes = _arc(0.50, 0.31, 0.23, 0.0, 2 * math.pi, 20, 0.9)                  # halo
        strokes += [((0.40, 0.42), (0.29, 0.95), 1.0), ((0.60, 0.42), (0.71, 0.95), 1.0),
                    ((0.29, 0.95), (0.71, 0.95), 1.0)]
        return (strokes, [(circ, 1.0), (flare, 1.0)], (0.50, 0.46, 0.54, 0.76))
    if name == "key":                                    # clé  (crypto)
        strokes = _arc(0.17, 0.50, 0.17, 0, 2 * math.pi, 20, 1.2)                    # anneau ext.
        strokes += _arc(0.17, 0.50, 0.075, 0, 2 * math.pi, 12, 1.0)                  # anneau int.
        strokes += [((0.31, 0.50), (0.95, 0.50), 1.6), ((0.31, 0.55), (0.88, 0.55), 1.0)]  # tige
        strokes += [((0.68, 0.50), (0.68, 0.76), 1.1), ((0.79, 0.50), (0.79, 0.68), 1.0),
                    ((0.92, 0.50), (0.92, 0.80), 1.1)]                               # pannetons
        ring = _disc(0.17, 0.50, 0.17, 16)
        return (strokes, [(ring, 0.35)], (0.50, 0.50, 0.92, 0.46))
    if name == "shield":                                 # écusson plein
        poly = [(0.5, 0.02), (0.95, 0.20), (0.90, 0.60), (0.5, 0.98),
                (0.10, 0.60), (0.05, 0.20)]
        return (_outline(poly, 0.7), [(poly, 1.0)], (0.50, 0.48, 0.54, 0.64))
    if name == "code_tags":                              # «  </>  »  (proportions de l'original)
        return ([((0.30, 0.05), (0.02, 0.5), 1.0), ((0.02, 0.5), (0.30, 0.95), 1.0),   # <
                 ((0.60, 0.98), (0.40, 0.02), 0.9),                                     # /
                 ((0.70, 0.05), (0.98, 0.5), 1.0), ((0.98, 0.5), (0.70, 0.95), 1.0)],   # >
                [], (0.50, 0.45, 0.82, 0.53))
    if name == "hash":                                   # «  #  »
        return ([((0.36, 0.04), (0.26, 0.96), 1.0), ((0.74, 0.04), (0.64, 0.96), 1.0),
                 ((0.04, 0.34), (0.96, 0.29), 1.0), ((0.04, 0.71), (0.96, 0.66), 1.0)],
                [], (0.50, 0.44, 0.58, 0.62))
    if name == "chevron_left":                           # «  <  »
        return ([((0.90, 0.05), (0.10, 0.5), 1.0), ((0.10, 0.5), (0.90, 0.95), 1.0)],
                [], (0.50, 0.44, 0.55, 0.68))
    if name == "chevron_right":                          # «  >  »
        return ([((0.10, 0.05), (0.90, 0.5), 1.0), ((0.90, 0.5), (0.10, 0.95), 1.0)],
                [], (0.50, 0.44, 0.55, 0.68))
    if name == "triangle":                               # ▲ plein
        poly = [(0.5, 0.04), (0.04, 0.96), (0.96, 0.96)]
        return (_outline(poly, 0.6), [(poly, 1.0)], (0.50, 0.50, 0.60, 0.42))
    raise ValueError(f"glyphe inconnu : {name}")


def _point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _poly_area(poly: list[tuple[float, float]]) -> float:
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return abs(a) * 0.5


def _glyph_points(name: str, n: int, bbox: tuple[float, float, float, float],
                  thickness: float, rng: random.Random) -> list[tuple[float, float]]:
    """EXACTEMENT n points décrivant le glyphe (traits + zones pleines), dans bbox.

    Un point par particule -> bijection nette. Les particules se répartissent
    entre les zones pleines (échantillonnage surfacique) et les traits
    (échantillonnage linéaire + épaisseur), au prorata de leur « masse ».
    """
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    strokes, fills, _ = _glyph_def(name)
    half = thickness * 0.5

    def seglen(s: tuple) -> float:
        return ((s[1][0] - s[0][0]) ** 2 + (s[1][1] - s[0][1]) ** 2) ** 0.5

    fill_mass = sum(_poly_area(p) * wt for p, wt in fills)
    band = max(thickness, 0.06)
    stroke_mass = sum(seglen(s) * s[2] for s in strokes) * band
    total = (fill_mass + stroke_mass) or 1.0
    n_fill = min(n, round(n * fill_mass / total)) if fills else 0

    norm: list[tuple[float, float]] = []
    if n_fill:
        fm = fill_mass or 1.0
        acc = 0
        for idx, (p, wt) in enumerate(fills):
            k = (n_fill - acc) if idx == len(fills) - 1 else max(1, round(n_fill * _poly_area(p) * wt / fm))
            k = max(0, k)
            bx0 = min(q[0] for q in p); bx1 = max(q[0] for q in p)
            by0 = min(q[1] for q in p); by1 = max(q[1] for q in p)
            got = tries = 0
            while got < k and tries < k * 120 + 400:
                tries += 1
                u, v = rng.uniform(bx0, bx1), rng.uniform(by0, by1)
                if _point_in_poly(u, v, p):
                    norm.append((u, v)); got += 1
            acc += k

    if strokes:
        sm = sum(seglen(s) * s[2] for s in strokes) or 1.0
        rem = n - len(norm)
        for si, s in enumerate(strokes):
            k = max(0, n - len(norm)) if si == len(strokes) - 1 \
                else max(1, round(rem * seglen(s) * s[2] / sm))
            (ax, ay), (bx, by) = s[0], s[1]
            L = seglen(s) or 1.0
            nx, ny = -(by - ay) / L, (bx - ax) / L
            for i in range(k):
                t = (i + 0.5) / k
                o = (rng.random() - rng.random()) * half   # triangulaire : cœur net, bord doux
                norm.append((ax + (bx - ax) * t + nx * o, ay + (by - ay) * t + ny * o))

    del norm[n:]
    while len(norm) < n:
        norm.append(rng.choice(norm) if norm else (0.5, 0.5))
    return [(x0 + u * w, y0 + v * h) for u, v in norm]


def _serpentine_rank(points: list[tuple[float, float]],
                     bbox: tuple[float, float, float, float], rows: int) -> list[int]:
    """Rang en balayage serpentin (bandes en y, sens alterné) normalisé sur bbox."""
    x0, y0, x1, y1 = bbox
    w = (x1 - x0) or 1.0
    bh = ((y1 - y0) or 1.0) / rows

    def key(i: int):
        x, y = points[i]
        b = min(rows - 1, max(0, int((y - y0) / bh)))
        u = (x - x0) / w
        return (b, u if b % 2 == 0 else 1.0 - u)

    return sorted(range(len(points)), key=key)


def _match_min_travel(homes: list[tuple[float, float]], targets: list[tuple[float, float]],
                      init_assign: list[int], rng: random.Random, passes: int) -> list[int]:
    """Bijection home_i -> targets[assign[i]] à trajet total ~minimal.

    Part d'une affectation cohérente (rang serpentin) puis applique du 2-opt :
    on échange deux cibles si ça raccourcit la somme des deux trajets. Le nuage
    se contracte alors dans la forme par le plus court chemin, sans croisements
    ni longues traînées, tout en restant une bijection (chaque point du glyphe
    garde sa particule -> traits denses et nets). Chaque glyphe est optimisé
    contre les mêmes homes : deux glyphes consécutifs restent proches car les
    deux cibles d'une particule sont chacune près de son home.
    """
    n = len(homes)
    assign = list(init_assign)

    def d2(hi: int, ti: int) -> float:
        hx, hy = homes[hi]
        tx, ty = targets[ti]
        return (hx - tx) ** 2 + (hy - ty) ** 2

    for _ in range(passes * n):
        a = rng.randrange(n)
        b = rng.randrange(n)
        if a == b:
            continue
        ta, tb = assign[a], assign[b]
        if d2(a, ta) + d2(b, tb) > d2(a, tb) + d2(b, ta):
            assign[a], assign[b] = tb, ta
    return assign


def build_particle_morph(ink: set[tuple[int, int]], layout: Layout, anim: Anim,
                         theme: Theme, rng: random.Random) -> list[str]:
    """Nuage de particules : silhouette → glyphe 1 → glyphe 2 → glyphe 3 → silhouette.

    Reproduit le "défilement d'images" de l'original. Bijection particule↔point
    du glyphe par rang serpentin (dans le repère de chaque forme) : le nuage se
    contracte d'un bloc dans le glyphe, sans croisements -> morph fluide, et
    chaque trait (y compris le « / ») reçoit assez de particules -> glyphe net.
    Particules visibles uniquement pendant la phase glitch (0;0;1;1;1;1;1;1;0).
    """
    kt = anim.key_times
    dur = anim.cycle_dur
    beg = anim.cycle_begin

    pool = sorted(ink)
    n = min(anim.particle_count, len(pool))
    homes = rng.sample(pool, n)

    xs = [p[0] for p in homes]
    ys = [p[1] for p in homes]
    pbox = (min(xs), min(ys), max(xs), max(ys))
    hw, hh = pbox[2] - pbox[0], pbox[3] - pbox[1]
    pcx, pcy = (pbox[0] + pbox[2]) / 2, (pbox[1] + pbox[3]) / 2
    jit = anim.morph_jitter * hw
    fhomes = [(float(x), float(y)) for x, y in homes]
    rows = anim.morph_rows
    sc = anim.morph_scale

    rank_home = _serpentine_rank(fhomes, pbox, rows)

    glyph_seqs: list[list[tuple[float, float]]] = []
    for gname in anim.morph_glyphs:
        _, _, (cxf, cyf, wf, hf) = _glyph_def(gname)
        gcx = pbox[0] + cxf * hw
        gcy = pbox[1] + cyf * hh
        gw = hw * wf * sc
        gh = hh * hf * sc
        gbox = (gcx - gw / 2, gcy - gh / 2, gcx + gw / 2, gcy + gh / 2)

        pts = _glyph_points(gname, n, gbox, anim.morph_thickness, rng)
        rank_g = _serpentine_rank(pts, gbox, rows)
        init = [0] * n                                    # rang serpentin <-> rang serpentin
        for r, hi in enumerate(rank_home):
            init[hi] = rank_g[r]
        assign = _match_min_travel(fhomes, pts, init, rng, anim.morph_opt_passes)
        glyph_seqs.append([(pts[assign[i]][0] + rng.uniform(-jit, jit),
                            pts[assign[i]][1] + rng.uniform(-jit, jit)) for i in range(n)])

    parts = [
        f'<defs><rect id="tvdark" width="{anim.particle_w}" height="{anim.particle_h}" '
        f'fill="{theme.ink}"/></defs>',
        f'<g transform="translate({layout.portrait_tx},{layout.portrait_ty}) '
        f'scale({layout.scale_x:.4f},{layout.scale_y:.4f})">',
    ]
    g1, g2, g3 = (glyph_seqs + glyph_seqs + glyph_seqs)[:3]
    for i in range(n):
        hx, hy = homes[i]
        a = f"{round(g1[i][0])} {round(g1[i][1])}"
        b = f"{round(g2[i][0])} {round(g2[i][1])}"
        c = f"{round(g3[i][0])} {round(g3[i][1])}"
        home = f"{hx} {hy}"
        vals = f"{home};{home};{a};{a};{b};{b};{c};{c};{home}"
        parts.append(
            f'<use href="#tvdark" opacity="0">'
            f'<animate attributeName="opacity" values="0;0;1;1;1;1;1;1;0" '
            f'keyTimes="{kt}" dur="{dur}s" begin="{beg}s" repeatCount="indefinite"/>'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="{vals}" keyTimes="{kt}" dur="{dur}s" begin="{beg}s" '
            f'repeatCount="indefinite"/></use>'
        )
    parts.append("</g>")
    return parts


# ──────────────────────────────────────────────────────────────────────────────
#  CHROME  (fenêtre, panneaux, bordures)
# ──────────────────────────────────────────────────────────────────────────────
def build_defs(theme: Theme, layout: Layout) -> str:
    a0, a1, a2 = theme.accent_stops
    s0, s1, s2 = theme.ascii_stops
    return (
        "<defs>"
        '<linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{a0}"><animate attributeName="stop-color" '
        f'values="{a0};{a1};{a2};{a0}" dur="10s" repeatCount="indefinite"/></stop>'
        f'<stop offset="0.5" stop-color="{a1}"><animate attributeName="stop-color" '
        f'values="{a1};{a2};{a0};{a1}" dur="10s" repeatCount="indefinite"/></stop>'
        f'<stop offset="1" stop-color="{a2}"><animate attributeName="stop-color" '
        f'values="{a2};{a0};{a1};{a2}" dur="10s" repeatCount="indefinite"/></stop>'
        "</linearGradient>"
        '<linearGradient id="asciiGrad" x1="0" y1="0" x2="0" y2="520" '
        'gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{s0}"/>'
        f'<stop offset="0.45" stop-color="{s1}"/>'
        f'<stop offset="1" stop-color="{s2}"/>'
        '<animateTransform attributeName="gradientTransform" type="translate" '
        'values="0 -120; 0 120; 0 -120" dur="9s" repeatCount="indefinite"/>'
        "</linearGradient>"
        '<linearGradient id="panelGrad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{theme.panel_top}"/>'
        f'<stop offset="1" stop-color="{theme.panel_bot}"/></linearGradient>'
        '<filter id="glow8" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="8"/></filter>'
        '<filter id="glow3" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="3"/></filter>'
        '<filter id="txtGlow" x="-30%" y="-30%" width="160%" height="160%">'
        '<feGaussianBlur stdDeviation="0.9" result="b"/><feMerge>'
        '<feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        f'<clipPath id="winClip"><rect x="{layout.win_x}" y="{layout.win_y}" '
        f'width="{layout.win_w}" height="{layout.win_h}" rx="{layout.win_rx}"/></clipPath>'
        "</defs>"
    )


def build_window(theme: Theme, layout: Layout, profile: Profile) -> list[str]:
    cx = layout.width / 2
    tb = layout.titlebar_h
    title = esc(f"{profile.email} - {profile.title_cmd}")
    return [
        f'<rect x="{layout.win_x}" y="{layout.win_y}" width="{layout.win_w}" '
        f'height="{layout.win_h}" rx="{layout.win_rx}" fill="{theme.bg_outer}"/>',
        '<g clip-path="url(#winClip)">',
        f'<rect x="{layout.win_x}" y="{layout.win_y}" width="{layout.win_w}" '
        f'height="{layout.win_h}" fill="url(#panelGrad)"/>',
        f'<rect x="{layout.win_x}" y="{layout.win_y}" width="{layout.win_w}" '
        f'height="{tb}" fill="{theme.titlebar}"/>',
        f'<line x1="{layout.win_x}" y1="{layout.win_y + tb}" x2="{layout.win_w + layout.win_x}" '
        f'y2="{layout.win_y + tb}" stroke="{theme.hairline}"/>',
        f'<circle cx="30" cy="25.0" r="5.5" fill="{theme.dot_red}"/>',
        f'<circle cx="50" cy="25.0" r="5.5" fill="{theme.dot_amber}"/>',
        f'<circle cx="70" cy="25.0" r="5.5" fill="{theme.dot_green}"/>',
        f'<text x="{cx:.1f}" y="29.0" text-anchor="middle" font-size="12" '
        f'fill="{theme.muted}">{title}</text>',
    ]


def build_left_panel(theme: Theme, layout: Layout, profile: Profile) -> list[str]:
    x, y, w, h, rx = layout.lp_x, layout.lp_y, layout.lp_w, layout.lp_h, layout.lp_rx
    return [
        f'<text x="38" y="74" font-size="10" letter-spacing="3" '
        f'fill="{theme.faint}">{esc(profile.left_label)}</text>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="none" '
        f'stroke="{theme.cyan}" stroke-width="2" opacity="0.45" filter="url(#glow3)"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{theme.panel_inner}" stroke="rgba(34,211,238,0.35)"/>',
    ]


def build_corner_brackets(theme: Theme, layout: Layout) -> list[str]:
    x, y, w, h = layout.lp_x, layout.lp_y, layout.lp_w, layout.lp_h
    tx = layout.portrait_tx
    x2 = x + w
    y2 = y + h
    c = theme.cyan
    return [
        f'<path d="M {tx} {y} L {x} {y} L {x} {y + 14}" fill="none" stroke="{c}" stroke-width="2" opacity="0.8"/>',
        f'<path d="M {x2 - 14} {y} L {x2} {y} L {x2} {y + 14}" fill="none" stroke="{c}" stroke-width="2" opacity="0.8"/>',
        f'<path d="M {tx} {y2} L {x} {y2} L {x} {y2 - 14}" fill="none" stroke="{c}" stroke-width="2" opacity="0.8"/>',
        f'<path d="M {x2 - 14} {y2} L {x2} {y2} L {x2} {y2 - 14}" fill="none" stroke="{c}" stroke-width="2" opacity="0.8"/>',
    ]


def build_border(theme: Theme, layout: Layout) -> list[str]:
    x = layout.win_x + 1
    y = layout.win_y + 1
    w = layout.win_w - 2
    h = layout.win_h - 2
    rx = layout.win_rx - 1
    return [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="none" '
        f'stroke="url(#accent)" stroke-width="3" opacity="0.55" filter="url(#glow8)"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="none" '
        f'stroke="url(#accent)" stroke-width="1.6"/>',
    ]


# ──────────────────────────────────────────────────────────────────────────────
#  PANNEAU DROIT
# ──────────────────────────────────────────────────────────────────────────────
def _leader_dots(label: str, value: str, total: int) -> str:
    return "." * max(3, total - len(label) - len(value) - 2)


def build_right_panel(profile: Profile, theme: Theme, layout: Layout, anim: Anim) -> list[str]:
    x = layout.rp_x
    row_len = layout.rp_row_len
    x_end = x + row_len
    parts: list[str] = [
        f'<text x="{x}" y="106" font-size="13" letter-spacing="2" fill="{theme.cyan}" '
        f'filter="url(#txtGlow)">{esc(profile.right_label)}</text>',
        f'<line x1="566" y1="102" x2="1061" y2="102" stroke="{theme.hairline}"/>',
        f'<text x="{x_end}" y="106" text-anchor="end" font-size="12" fill="{theme.live}" '
        f'font-weight="700"><tspan>&#9679;</tspan> LIVE<animate attributeName="opacity" '
        f'values="1;0.25;1" dur="1.6s" repeatCount="indefinite"/></text>',
        # badge email
        f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" dur="0.5s" '
        f'begin="0.6s" fill="freeze"/>'
        f'<rect x="{x}" y="122" width="245" height="20" rx="4" fill="{theme.badge_bg}"/>'
        f'<text x="{x + 9}" y="136" font-size="14" font-weight="700" '
        f'fill="{theme.badge_fg}">{esc(profile.email)}</text>'
        f'<line x1="{x + 255}" y1="130" x2="{x_end}" y2="130" stroke="{theme.hairline}"/></g>',
    ]

    y = layout.rp_y0
    begin = anim.rp_begin0
    n_info = len(profile.info_rows)
    for idx, row in enumerate(profile.rows):
        if row.kind == "divider":
            y += layout.rp_divider_gap
            begin += anim.rp_begin_step
        dur = anim.rp_row_dur
        b = f"{begin:.2f}s"
        if row.kind == "divider":
            dashes = "-" * max(3, layout.rp_total_chars - len(row.label) - 1)
            inner = (f'<tspan fill="{theme.muted}">{esc(row.label)} </tspan>'
                     f'<tspan fill="{theme.leader}">{dashes}</tspan>')
            parts.append(
                f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" '
                f'dur="{dur}s" begin="{b}" fill="freeze"/>'
                f'<text x="{x}" y="{y}" font-size="14" textLength="{row_len}" '
                f'lengthAdjust="spacingAndGlyphs" xml:space="preserve">{inner}</text></g>'
            )
        else:
            dots = _leader_dots(row.label, row.value, layout.rp_total_chars)
            inner = (f'<tspan fill="{theme.cyan}">{esc(row.label)} </tspan>'
                     f'<tspan fill="{theme.leader}">{dots}</tspan>'
                     f'<tspan fill="{theme.value}" font-weight="600"> {esc(row.value)}</tspan>')
            parts.append(
                f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" '
                f'dur="{dur}s" begin="{b}" fill="freeze"/>'
                f'<animateTransform attributeName="transform" type="translate" '
                f'values="-8 0;0 0" dur="{dur}s" begin="{b}" fill="freeze"/>'
                f'<text x="{x}" y="{y}" font-size="14" textLength="{row_len}" '
                f'lengthAdjust="spacingAndGlyphs" xml:space="preserve">{inner}</text></g>'
            )
        y += layout.rp_step
        begin += anim.rp_begin_step

    # footer
    footer_y = layout.lp_y + layout.lp_h + 1
    parts.append(
        f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" dur="0.5s" '
        f'begin="{anim.footer_begin}s" fill="freeze"/>'
        f'<text x="{x}" y="{footer_y}" font-size="14" fill="{theme.muted}">'
        f'&#9656; {esc(profile.footer)} &#8595; '
        f'<tspan fill="{theme.cyan}">&#9608;<animate attributeName="fill-opacity" '
        f'values="1;0;1" dur="1s" repeatCount="indefinite"/></tspan></text></g>'
    )
    return parts


# ──────────────────────────────────────────────────────────────────────────────
#  ASSEMBLAGE
# ──────────────────────────────────────────────────────────────────────────────
def build_svg(image_path: str, profile: Profile, theme: Theme, layout: Layout,
              anim: Anim, portrait: PortraitOpts, seed: int) -> str:
    rng = random.Random(seed)
    ink = build_ink_pixels(image_path, layout, portrait)
    if not ink:
        raise SystemExit("Portrait vide : ajuste --threshold-bias / --gamma / --contrast.")

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" '
        f'height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'
        f"'Liberation Mono',monospace\" "
        f'role="img" aria-label="{esc(profile.name)} — profile.sh --live">',
        build_defs(theme, layout),
    ]
    parts += build_window(theme, layout, profile)
    parts += build_left_panel(theme, layout, profile)
    parts += build_intro(ink, layout, anim, theme, rng)
    parts += build_glitch_loop(ink, layout, anim, theme, rng)
    parts += build_particle_morph(ink, layout, anim, theme, rng)
    parts += build_corner_brackets(theme, layout)
    parts += build_right_panel(profile, theme, layout, anim)
    parts.append("</g>")                                 # ferme winClip
    parts += build_border(theme, layout)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ──────────────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Génère le hero banner profile.sh --live.")
    p.add_argument("--image", default=DEFAULT_IMAGE, help="photo source du portrait")
    p.add_argument("--out", default="dark.svg", help="fichier SVG de sortie")
    p.add_argument("--seed", type=int, default=7, help="graine aléatoire (reproductible)")
    # identité (raccourcis ; sinon éditer la dataclass Profile)
    p.add_argument("--name")
    p.add_argument("--email")
    p.add_argument("--footer")
    # portrait
    p.add_argument("--contrast", type=float, default=PortraitOpts.contrast)
    p.add_argument("--gamma", type=float, default=PortraitOpts.gamma)
    p.add_argument("--brightness", type=float, default=PortraitOpts.brightness)
    p.add_argument("--threshold-bias", type=int, default=PortraitOpts.threshold_bias,
                   help=">0 = portrait plus clair (moins d'encre)")
    p.add_argument("--no-dither", action="store_true", help="seuil dur au lieu de Floyd–Steinberg")
    p.add_argument("--vignette", type=float, default=PortraitOpts.vignette,
                   help="0..1, assombrit les bords du portrait")
    p.add_argument("--dark-ink", action="store_true",
                   help="encre = tons sombres (défaut : encre = tons clairs)")
    # géométrie / anim
    p.add_argument("--grid-w", type=int, default=Layout.grid_w)
    p.add_argument("--grid-h", type=int, default=Layout.grid_h)
    p.add_argument("--bands", type=int, default=Anim.intro_bands)
    p.add_argument("--tile", type=int, default=Anim.tile)
    p.add_argument("--implode", type=float, default=Anim.implode)
    p.add_argument("--particles", type=int, default=Anim.particle_count,
                   help="nombre de particules du morph glitch")
    p.add_argument("--glyphs", default=",".join(Anim.morph_glyphs),
                   help="glyphes du morph, séparés par des virgules "
                        "(padlock, terminal, keyhole, key, shield, code_tags, hash, "
                        "chevron_left, chevron_right, triangle)")
    return p.parse_args()


def main() -> None:
    a = parse_args()

    theme = Theme()
    layout = Layout(grid_w=a.grid_w, grid_h=a.grid_h)
    anim = Anim(
        intro_bands=a.bands, tile=a.tile, implode=a.implode,
        particle_count=a.particles,
        morph_glyphs=tuple(g.strip() for g in a.glyphs.split(",") if g.strip()),
    )
    portrait = PortraitOpts(
        contrast=a.contrast, gamma=a.gamma, brightness=a.brightness,
        threshold_bias=a.threshold_bias, dither=not a.no_dither,
        vignette=a.vignette, invert=not a.dark_ink,
    )
    profile = Profile()
    over = {}
    if a.name:
        over["name"] = a.name
        if profile.info_rows and profile.info_rows[0].label == "Subject":
            profile.info_rows[0] = Row("Subject", a.name)
    if a.email:
        over["email"] = a.email
        for r in profile.contact_rows:
            if r.label == "Grid.Mail":
                r.value = a.email
    if a.footer:
        over["footer"] = a.footer
    if over:
        profile = replace(profile, **over)

    svg = build_svg(a.image, profile, theme, layout, anim, portrait, a.seed)
    out = Path(a.out)
    out.write_text(svg, encoding="utf-8")

    n_ink = svg.count("v1h-")
    print(f"✓ {out}  ({len(svg):,} o, ~{n_ink:,} pixels encre, seed={a.seed})")


if __name__ == "__main__":
    main()
