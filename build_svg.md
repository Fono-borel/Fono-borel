# `build_svg.py` — générateur du hero banner `dark.svg`

Reconstruit **à l'identique** le design de `dark.svg` (fenêtre terminal
« profile.sh --live ») à partir d'une photo + d'un bloc de configuration.
Objectif : pouvoir modifier / moduler le SVG sans éditer 1,3 Mo de XML à la main.

```
python build_svg.py                      # régénère ./dark.svg depuis assets/profile.jpg
```

Dépendance : `pip install pillow`

---

## Ce qui est généré

| Zone | Source dans le script |
|------|-----------------------|
| Cadre fenêtre, barre de titre, pastilles, bordure animée | `build_window`, `build_border`, `build_defs` |
| Panneau gauche `VISUAL.MAP` + coins | `build_left_panel`, `build_corner_brackets` |
| Portrait — **calque 1 : dissolve d'intro** | `build_intro` |
| Portrait — **calque 2 : boucle glitch (implosion)** | `build_glitch_loop` |
| Portrait — **calque 3 : nuage de particules qui morphe en glyphes** | `build_particle_morph` |
| Panneau droit `SYSTEM.INFO` (lignes + badge + footer) | `build_right_panel` |

### Pipeline portrait
`photo → gris → recadrage ratio (300×322) → autocontraste → contraste/gamma →
vignette → tramage Floyd–Steinberg 1 bit → pixels « encre »`.
Par défaut **l'encre suit les tons clairs** (fond, peau, chemise) ; cheveux,
costume et cravate deviennent du vide → silhouette en négatif tramé, comme
l'original. `--dark-ink` inverse.

Les pixels sont ensuite :
- **intro** : amas de 3 px mélangés, répartis en 60 paquets, fondu échelonné
  (`begin` 0,20 s → ~2,17 s), puis le calque est masqué à `3.2s` ;
- **boucle** : découpés en tuiles de 30 px ; pendant la phase glitch du
  cycle de 13,9 s chaque tuile disparaît en se décalant vers le centre
  (`implode = 0.45`), puis se recompose ;
- **particules** : `particle_count` (défaut **1300**) `<use>` d'un rectangle
  2,4×1,7, visibles uniquement pendant la phase glitch. Chaque particule
  part d'un point de la silhouette puis se range successivement dans
  **3 glyphes** — par défaut **🔒 cadenas → `</>` → fenêtre `>_`**
  (cybersécurité·crypto / dev / linux·shell) — maintenus une keyframe
  chacun, avant de revenir au visage. C'est le « défilement d'images » de
  l'original, synchronisé avec la dislocation des tuiles.

  Les glyphes sont **détaillés** : mélange de **zones pleines** (échantillon-
  nage surfacique — corps du cadenas, bloc curseur, écusson) et de **traits**
  (échantillonnage linéaire + épaisseur — anse, cadre de fenêtre, `>`, `</>`).
  Helpers : `_disc`, `_rrect`, `_outline`, `_arc`.

  **Densité + épaisseur** : chaque glyphe est **compact et centré**
  (`_glyph_def` → placement `(cx, cy, w, h)`, ~50–80 % de la silhouette),
  calé sur les proportions mesurées de l'original. 900 points dans cette
  petite surface = points serrés, traits épais. `</>` reprend la structure
  de l'original : `<` sur 0–30 %, `/` sur 40–60 %, `>` sur 70–100 %, gaps nets.

  **Netteté + fluidité de l'appariement** :
  1. le glyphe = **n points sur les traits** (`_glyph_points`, un point par
     particule → bijection → chaque trait garde ses particules) ;
  2. init par rang serpentin (nuage cohérent) ;
  3. **2-opt** (`_match_min_travel`, `morph_opt_passes`) : échange de deux
     cibles tant que ça raccourcit les trajets → contraction par le plus
     court chemin, sans croisements ni traînées.

  Mesuré : transitions glyphe→glyphe **~43–49 px** (original 36–45),
  home↔glyphe ~63–67 px (original 51–54), **boucle sans à-coup**
  (`kf0 == kf8`). Réglages : placement dans `_glyph_def`,
  `morph_thickness`, `morph_scale`, `morph_opt_passes`, `morph_rows`.

Glyphes disponibles (`_glyph_def`) :

| glyphe | rendu |
|--------|-------|
| `padlock` | 🔒 corps plein + anse double + serrure — cyber / chiffrement |
| `terminal` | fenêtre : cadre + barre de titre + 3 pastilles + `>` + curseur █ — Linux |
| `keyhole` | trou de serrure plein + halo — cyber / accès |
| `key` | clé : anneau double + tige + 3 pannetons — crypto |
| `shield` | écusson plein — défense |
| `code_tags` | `</>` — développement |
| `hash` | `#` — root, hashing |
| `chevron_left` / `chevron_right` / `triangle` | formes neutres |

Changer la séquence (toujours 3) :

```
python build_svg.py --glyphs keyhole,code_tags,key      # cyber / dev / crypto
python build_svg.py --glyphs shield,terminal,hash       # défense / shell / root
```

ou éditer `Anim.morph_glyphs`. Nouveau glyphe = une entrée dans `_glyph_def` :
liste de segments `((ax,ay),(bx,by),poids)` en 0..1 + `filled` + placement
`(cx,cy,w,h)` en fraction de la silhouette (`_arc()` pour les cercles/arcs).

Les `keyTimes` / `values` SMIL (cycle 13,9 s, 9 keyframes
`0;0.194;0.288;0.432;0.525;0.669;0.763;0.906;1`) sont repris **mot pour mot**
de l'original.

---

## Modifier le contenu

Tout est dans les `@dataclass` en haut du fichier.

### Identité et lignes du panneau → `class Profile`
```python
info_rows = [
    Row("Subject",      "Borel Fono"),
    Row("Role",         "Security Engineer — Full-Spectrum"),
    Row("Core.Offense", "Burp, Cobalt Strike, BloodHound, Sliver"),
    ...
]
contact_rows = [
    Row("- Contact", kind="divider"),
    Row("Grid.Mail", "fonoborel@gmail.com"),
    ...
]
```
- `Row(label, value)` = une ligne clé/valeur avec points de conduite.
- `Row(label, kind="divider")` = un séparateur `- Label -------`.
- Ajouter / retirer des lignes est libre ; garder ~11 lignes d'info pour que
  tout tienne dans la hauteur du panneau.

Raccourcis CLI sans toucher au code :
```
python build_svg.py --name "Borel Fono" --email fonoborel@gmail.com \
                    --footer "Write-ups & tooling below"
```

### Couleurs → `class Theme`
`ink` = couleur du portrait, `accent_stops` = dégradé de la bordure animée, etc.

### Géométrie → `class Layout`  ·  Minutage → `class Anim`
Les valeurs par défaut reproduisent `dark.svg` au pixel / à la frame près.

---

## Régler le portrait

| Besoin | Option |
|--------|--------|
| Portrait trop dense / trop sombre | `--gamma 2.2` ou `--threshold-bias -45` |
| Portrait trop clair / troué | `--gamma 1.6` ou `--threshold-bias -10` |
| Fond trop chargé sur les bords | `--vignette 0.55` |
| Rendu net sans grain | `--no-dither` |
| Encre = zones sombres (cheveux/costume pleins) | `--dark-ink` |
| Autre cadrage | `--grid-w`, `--grid-h` |
| Autre photo | `--image chemin/vers/photo.jpg` |
| Reproductibilité / variation du bruit | `--seed 7` |
| Autres glyphes dans le morph glitch | `--glyphs shield,hash,triangle` |
| Plus / moins de particules | `--particles 1200` |

Aperçu rapide d'un réglage sans générer tout le SVG :
```python
from build_svg import Layout, PortraitOpts, build_ink_pixels
from PIL import Image
L = Layout(); o = PortraitOpts(gamma=2.0, vignette=0.5)
ink = build_ink_pixels("assets/profile.jpg", L, o)
im = Image.new("L", (L.grid_w, L.grid_h)); [im.putpixel((x, y), 255) for x, y in ink]
im.save("/tmp/preview.png")
```

---

## Vérifier le résultat

```
python -c "import xml.dom.minidom as m; m.parse('dark.svg')"      # XML valide
```
Les animations sont du SMIL : elles tournent dans un navigateur / sur GitHub,
pas dans les rasteriseurs statiques (`resvg`, `rsvg-convert`). Pour un aperçu
statique, forcer les `opacity="0"` à `1` avant de rasteriser.

`dark.svg.backup-arifhasan` = version précédente (profil « Arif Hasan »).
