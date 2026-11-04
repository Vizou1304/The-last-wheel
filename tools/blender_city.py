"""The Last Wheel — la ville low-poly dans son cratère gelé, source de la page web 3D.

Blender 4.x / 5.x. Onglet Scripting > Open > ce fichier > Run Script.
Relançable: il efface et reconstruit tout ce qu'il a créé (collection "TheLastWheel").

Il crée:
  - les 12 bâtiments du jeu + la centrale, chacun sous un Empty "TLW_<id>", plus les exemplaires
    supplémentaires des bâtiments construits plusieurs fois ("TLW_bunkhouse_2"... voir REPEATS)
  - la Roue de la centrale sous l'Empty "TLW_wheel" (la page la fait tourner à la vitesse du hamster)
  - des points "TLW_smoke_*" au sommet des cheminées (la page y fait monter la fumée)
  - STYLE "frost": cratère de roche et de neige, ville en cercles, chemins en étoile, arbres gelés
  - STYLE "pastel": l'île flottante aux aplats pastel (première version)

Fichiers produits dans le dossier tlw_export/ (à côté du .blend):
  city.glb           la scène 3D de la page web            (si EXPORT_GLB)
  city_overview.png  vue du jeu, city_hero.png vue héros    (si RENDER, Cycles, GPU si dispo)
  -> copie-les dans the-last-wheel/web/assets/

Retouches à la main: garde les noms TLW_<id>, TLW_wheel et TLW_smoke_*, puis mets BUILD = False
et relance: le script réexporte sans rien reconstruire.
"""
import math
import os

import random

import json

import bpy  # noqa: I001  (bpy avant bmesh: requis hors de l'interface Blender)
import bmesh
from mathutils import Matrix, Vector, noise

BUILD = True            # False = ne reconstruit pas, n'exporte que (après tes retouches)
EXPORT_GLB = True       # exporte city.glb, la scène 3D affichée par la page web
RENDER = True           # rend les images fixes (vue d'ensemble, vue héros pour les posts)
SPRITES = False         # rend aussi un sprite isolé par bâtiment
SAMPLES = 64            # qualité Cycles (débruitage activé)
SPRITE_PX = 512         # taille des sprites (carrés, fond transparent)
OVERVIEW = (1920, 1080)
OUT_DIR = os.path.join(bpy.path.abspath("//") or os.path.expanduser("~"), "tlw_export")
COLL_NAME = "TheLastWheel"
STYLE = "frost"         # "frost" (cratère de roche et de neige) ou "pastel" (île flottante)
SEED = 7                # change la forme du cratère et la place des arbres

# Palettes (sRGB). Une seule famille chaude: les lumières.
PALETTES = {
    "pastel": {
        "snow": (0.90, 0.91, 0.98), "rock": (0.47, 0.47, 0.66), "stone": (0.66, 0.66, 0.82),
        "stone_dark": (0.47, 0.47, 0.66), "wood": (0.76, 0.60, 0.62), "wall": (0.68, 0.64, 0.80),
        "wall_light": (0.86, 0.80, 0.88), "canvas": (0.92, 0.84, 0.78), "metal": (0.52, 0.58, 0.72),
        "door": (0.42, 0.36, 0.52), "path": (0.78, 0.78, 0.90), "plaza": (0.70, 0.70, 0.86),
        "pine": (0.40, 0.44, 0.60), "smoke": (0.85, 0.85, 0.95),
    },
    "frost": {
        "snow": (0.88, 0.92, 1.00), "rock": (0.20, 0.25, 0.34), "stone": (0.42, 0.45, 0.54),
        "stone_dark": (0.26, 0.28, 0.36), "wood": (0.46, 0.29, 0.22), "wall": (0.36, 0.34, 0.40),
        "wall_light": (0.55, 0.52, 0.56), "canvas": (0.62, 0.55, 0.48), "metal": (0.30, 0.32, 0.40),
        "door": (0.18, 0.15, 0.18), "path": (0.55, 0.57, 0.66), "plaza": (0.38, 0.36, 0.40),
        "pine": (0.14, 0.17, 0.22), "smoke": (0.78, 0.80, 0.86),
    },
}
GLOWS = {  # (couleur sRGB, intensité d'émission)
    "pastel": {"fire": ((1.00, 0.42, 0.12), 2.2), "window": ((1.00, 0.70, 0.35), 1.4),
               "greenhouse": ((0.70, 0.95, 0.82), 0.35)},
    "frost": {"fire": ((1.00, 0.38, 0.08), 9.0), "window": ((1.00, 0.62, 0.28), 5.0),
              "greenhouse": ((0.70, 0.95, 0.80), 1.2)},
}
WORLDS = {"pastel": ((0.90, 0.88, 1.00), 0.55), "frost": ((0.16, 0.22, 0.36), 1.0)}
PALETTE, GLOW = PALETTES[STYLE], GLOWS[STYLE]
WORLD_COLOR, WORLD_STRENGTH = WORLDS[STYLE]

# Emplacements
PATH_END, LATE_ANGLE, REPEAT_ANGLE = {}, {}, []   # remplis pour le style "frost" (voir plus bas)
LATE_INNER_R = 16.6   # rayon du bord intérieur des bâtiments tardifs : au-delà de l'anneau extérieur (r=15, large de 1)
if STYLE == "frost":
    # ville radiale: 7 bâtiments autour du générateur, 4 au bout des chemins
    RING1 = ["tents", "cellar", "workshop", "bunkhouse", "greenhouse", "infirmary", "story_hall"]
    RING2 = {"big_cellar": 1, "beacon": 3, "heat_pipes": 5, "insulation": 6}  # n° de chemin
    STEP = 2 * math.pi / len(RING1)
    START = -math.pi / 2 - STEP / 2
    PATH_ANGLES = [START + STEP * (i + 0.5) for i in range(len(RING1))]
    LAYOUT = {"generator": (0, 0)}
    for i, bid in enumerate(RING1):
        a = START + STEP * i
        LAYOUT[bid] = (6.8 * math.cos(a), 6.8 * math.sin(a))
    for bid, k in RING2.items():
        a = PATH_ANGLES[k]
        LAYOUT[bid] = (12.3 * math.cos(a), 12.3 * math.sin(a))
    # exemplaires supplémentaires des bâtiments que le jeu construit plusieurs fois
    # (à garder égal au "max" de content/buildings.json): anneau extérieur, entre les chemins
    REPEATS = {"tents": [0], "bunkhouse": [3, 2, 4, 1, 5]}  # n° de secteur pour le 2e, 3e... exemplaire
    for bid, sectors in REPEATS.items():
        for k, i in enumerate(sectors, start=2):
            a = START + STEP * i
            LAYOUT[f"{bid}_{k}"] = (12.6 * math.cos(a), 12.6 * math.sin(a))
            REPEAT_ANGLE.append(a)
    # Bâtiments tardifs : au-delà de l'anneau extérieur, centre = bord intérieur + demi-profondeur
    # (demi-profondeurs mesurées par tools/audit_scene.py, pour que rien ne touche l'anneau ni les routes)
    for bid, (ang_idx, frac, half_depth) in {
        "forge":           (1, 0.5, 1.0),
        "deep_forge":      (1, 0.0, 1.2),
        "observatory":     (4, 0.0, 1.2),
        "hall_of_records": (5, 0.5, 1.3),
        "outer_wall":      (2, 0.5, 0.6),
        "watchtower":      (0, 0.0, 1.1),
        "clinic":          (6, 0.5, 1.15),
        "grand_hall":      (3, 0.0, 1.5),
        "mechanists":      (3, 0.5, 1.1),
        "thermal_heart":   (2, 0.0, 2.7),
    }.items():
        a = PATH_ANGLES[ang_idx] + frac * STEP
        r = LATE_INNER_R + half_depth
        LAYOUT[bid] = (math.cos(a) * r, math.sin(a) * r)
        if frac == 0.0:  # sur l'axe d'une route : la route elle-même s'arrête devant le bâtiment
            PATH_END.setdefault(ang_idx, LATE_INNER_R - 0.4)
        else:            # entre deux routes : une allée de porte part de l'anneau extérieur (stade s4)
            LATE_ANGLE[bid] = a
    # Bord intérieur (rayon) des bâtiments de l'anneau 2, posés sur l'axe d'une route : la route s'y arrête
    RING2_INNER = {"big_cellar": 10.1, "beacon": 11.7, "heat_pipes": 11.5, "insulation": 10.8}
    for bid, k in RING2.items():
        PATH_END[k] = RING2_INNER[bid] - 0.4
else:
    S = 5.5
    PATH_ANGLES = []
    LAYOUT = {
        "generator": (0, 0),
        "tents": (-S, -S), "cellar": (0, -S), "workshop": (S, -S),
        "bunkhouse": (S, 0), "greenhouse": (S, S), "insulation": (0, S),
        "infirmary": (-S, S), "story_hall": (-S, 0),
        "big_cellar": (0, -2 * S), "beacon": (2 * S, 0), "heat_pipes": (-2 * S, 0),
    }

CAM_ROT = (math.radians(60 if STYLE == "pastel" else 45), 0.0, math.radians(45))  # faces -Y et +X visibles


# --------------------------------------------------------------- outils ---
def lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def set_input(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return


MATS = {}


def mat(key):
    if key in MATS:
        return MATS[key]
    m = bpy.data.materials.new(f"TLW_{key}")
    if m.node_tree is None:
        m.use_nodes = True
    p = m.node_tree.nodes.get("Principled BSDF")
    set_input(p, ["Roughness"], 1.0)
    set_input(p, ["Specular IOR Level", "Specular"], 0.0)
    if key in GLOW:
        color, strength = GLOW[key]
        set_input(p, ["Base Color"], (*lin(color), 1))
        set_input(p, ["Emission Color", "Emission"], (*lin(color), 1))
        set_input(p, ["Emission Strength"], strength)
    else:
        set_input(p, ["Base Color"], (*lin(PALETTE[key]), 1))
    MATS[key] = m
    return m


_n = [0]


def _finish(bm, parent, material, loc):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    _n[0] += 1
    name = f"{parent.name}_{_n[0]:03d}"
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat(material))
    o = bpy.data.objects.new(name, me)
    COLL.objects.link(o)
    o.parent = parent
    o.location = loc
    return o


def box(parent, material, w, d, h, x=0, y=0, z=0, rz=0.0):
    """Pavé w x d x h posé sur z (base en bas)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, h / 2), verts=bm.verts)
    if rz:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rz, 3, "Z"), verts=bm.verts)
    return _finish(bm, parent, material, (x, y, z))


def cyl(parent, material, r, h, x=0, y=0, z=0, seg=16, r2=None, axis="Z", rz=0.0):
    """Cylindre/cône. axe Z: base posée sur z. Axes X/Y: centré sur (x, y, z)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r, radius2=r if r2 is None else r2, depth=h)
    if axis == "Z":
        bmesh.ops.translate(bm, vec=(0, 0, h / 2), verts=bm.verts)
    elif axis == "X":
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y"), verts=bm.verts)
    else:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "X"), verts=bm.verts)
    if rz:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rz, 3, "Z"), verts=bm.verts)
    return _finish(bm, parent, material, (x, y, z))


def limb_into(bm, base, tip, r0, r1, seg=5):
    """Ajoute à `bm` une branche conique de `base` à `tip` (Vector), rayon r0 -> r1. Une seule maille par arbre."""
    d = tip - base
    length = d.length
    new = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r0, radius2=r1, depth=length)["verts"]
    bmesh.ops.translate(bm, vec=(0, 0, length / 2), verts=new)  # base en z = 0, pointe en z = longueur
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=d.to_track_quat("Z", "Y").to_matrix(), verts=new)
    bmesh.ops.translate(bm, vec=base, verts=new)


def dead_tree(parent, p, rng, hd):
    """Arbre mort : tronc effilé et un peu penché, 5 à 8 branches réparties tout autour (angle d'or : jamais dans
    un même plan, donc plus de silhouette en croix), brindilles, sommet parfois fourchu, parfois un peu de neige."""
    bm = bmesh.new()
    lean = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)).normalized() * rng.uniform(0.04, 0.12) * hd
    base, tip = Vector((0, 0, 0)), Vector((lean.x, lean.y, hd))
    limb_into(bm, base, tip, 0.16, 0.045)
    n = rng.randint(5, 8)
    a0 = rng.uniform(0, math.tau)
    for k in range(n):
        t = min(0.92, max(0.3, 0.38 + 0.52 * (k + rng.uniform(-0.2, 0.2)) / max(1, n - 1)))  # hauteur sur le tronc
        a = a0 + k * 2.399963                                  # angle d'or
        pos = base.lerp(tip, t)
        length = (1 - t) * hd * 0.4 + rng.uniform(0.2, 0.35)   # plus courtes vers le haut
        d = Vector((math.cos(a), math.sin(a), rng.uniform(0.35, 0.8))).normalized()
        end = pos + d * length
        limb_into(bm, pos, end, 0.05, 0.015, seg=4)
        if length > 0.5 and rng.random() < 0.6:                # brindille
            sub = pos.lerp(end, rng.uniform(0.5, 0.75))
            a2 = a + rng.choice((-1, 1)) * rng.uniform(0.5, 0.9)
            d2 = Vector((math.cos(a2), math.sin(a2), rng.uniform(0.4, 0.9))).normalized()
            limb_into(bm, sub, sub + d2 * length * 0.45, 0.025, 0.008, seg=4)
    if rng.random() < 0.5:                                     # sommet fourchu
        for sign in (-1, 1):
            limb_into(bm, tip, tip + Vector((sign * 0.22, rng.uniform(-0.12, 0.12), 0.42)), 0.035, 0.01, seg=4)
    _finish(bm, parent, "pine", (p.x, p.y, 0.0))
    if rng.random() < 0.5:                                     # un peu de neige sur le haut du tronc
        cyl(parent, "snow", 0.1, 0.12, x=p.x + tip.x, y=p.y + tip.y, z=hd - 0.06, seg=5, r2=0.0)


def roof(parent, material, w, d, h, x=0, y=0, z=0, over=0.15):
    """Toit à deux pans, faîtage le long de X."""
    x0, x1, y0, y1 = -w / 2 - over, w / 2 + over, -d / 2 - over, d / 2 + over
    bm = bmesh.new()
    v = [bm.verts.new(p) for p in [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0),
                                    (x0, 0, h), (x1, 0, h)]]
    for f in [(0, 1, 5, 4), (2, 3, 4, 5), (3, 0, 4), (1, 2, 5), (0, 3, 2, 1)]:
        bm.faces.new([v[i] for i in f])
    return _finish(bm, parent, material, (x, y, z))


def windows(parent, w, d, xs, z, size=(0.38, 0.45), side="-Y"):
    for x in xs:
        if side == "-Y":
            box(parent, "window", size[0], 0.06, size[1], x=x, y=-d / 2 - 0.02, z=z)
        else:
            box(parent, "window", 0.06, size[0], size[1], x=w / 2 + 0.02, y=x, z=z)


# ------------------------------------------------------------ bâtiments ---
def marker(name, parent, loc):
    """Point invisible exporté dans city.glb (fumée, axe de la Roue...)."""
    m = bpy.data.objects.new(name, None)
    m.empty_display_size = 0.3
    COLL.objects.link(m)
    m.parent = parent
    m.location = loc
    return m


def ring(parent, material, r, thick, depth, n, y=0.0, z=0.0):
    """Anneau vertical low-poly (plan XZ), fait de n segments."""
    seg_len = 2 * r * math.sin(math.pi / n) * 1.04
    for i in range(n):
        a = 2 * math.pi * (i + 0.5) / n
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(seg_len, depth, thick), verts=bm.verts)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(-a + math.pi / 2, 3, "Y"), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(r * math.cos(a), y, r * math.sin(a) + z), verts=bm.verts)
        _finish(bm, parent, material, (0, 0, 0))


def b_generator(e):
    # socle massif à gradins, grilles de foyer incandescentes tout autour
    cyl(e, "stone_dark", 3.0, 0.45, seg=12)
    cyl(e, "stone", 2.55, 0.35, z=0.45, seg=12)
    for i in range(12):
        a = 2 * math.pi * (i + 0.5) / 12
        box(e, "fire", 0.5, 0.08, 0.22, x=2.56 * math.cos(a), y=2.56 * math.sin(a), z=0.5,
            rz=a + math.pi / 2)
    # plateforme de maintenance: anneau de marche + garde-corps + escalier
    cyl(e, "stone_dark", 2.55, 0.1, z=0.8, seg=12)
    for i in range(6):
        a = 2 * math.pi * (i + 0.5) / 6
        box(e, "metal", 0.06, 0.06, 0.55, x=2.38 * math.cos(a), y=2.38 * math.sin(a), z=0.85)
    for s in range(3):
        box(e, "stone", 0.75 - s * 0.12, 0.28, 0.12 * (s + 1), x=2.85 - s * 0.22, y=0)
    # chaudière: gros fût, bande de feu, chapeau
    cyl(e, "metal", 1.75, 2.4, z=0.8, seg=12)
    cyl(e, "fire", 1.82, 0.38, z=1.45, seg=12)
    for i in range(6):  # nervures
        a = 2 * math.pi * i / 6
        box(e, "stone_dark", 0.22, 0.22, 2.4, x=1.8 * math.cos(a), y=1.8 * math.sin(a), z=0.8, rz=a)
    cyl(e, "stone_dark", 2.05, 0.3, z=3.2, seg=12)
    cyl(e, "metal", 1.75, 0.8, z=3.5, seg=12, r2=1.0)
    # trois cheminées, la fumée part de leur sommet
    for k, deg in enumerate((90, 210, 330)):
        a = math.radians(deg)
        x, y = 1.05 * math.cos(a), 1.05 * math.sin(a)
        cyl(e, "metal", 0.34, 3.9, x=x, y=y, z=3.5, seg=8)
        cyl(e, "stone_dark", 0.44, 0.18, x=x, y=y, z=7.4, seg=8)
        cyl(e, "fire", 0.28, 0.05, x=x, y=y, z=7.58, seg=8)
        marker(f"TLW_smoke_gen{k + 1}", e, (x, y, 7.75))
    # câbles entre les 3 cheminées (au 3/4 de leur hauteur)
    chim_pos = [(1.05 * math.cos(math.radians(d)), 1.05 * math.sin(math.radians(d))) for d in (90, 210, 330)]
    for k in range(3):
        cx0, cy0 = chim_pos[k]
        cx1, cy1 = chim_pos[(k + 1) % 3]
        mx, my = (cx0 + cx1) / 2, (cy0 + cy1) / 2
        dist = math.sqrt((cx1 - cx0) ** 2 + (cy1 - cy0) ** 2)
        angle = math.atan2(cy1 - cy0, cx1 - cx0)
        box(e, "metal", dist, 0.05, 0.05, x=mx, y=my, z=6.4, rz=angle)
    # tuyaux vers les quartiers
    for a in PATH_ANGLES:
        if abs(math.sin(a) + 1) < 0.05:  # chemin devant la Roue
            continue
        cyl(e, "metal", 0.16, 1.6, x=3.6 * math.cos(a), y=3.6 * math.sin(a), z=0.3, axis="X", seg=8,
            rz=a)
        cyl(e, "fire", 0.2, 0.12, x=3.0 * math.cos(a), y=3.0 * math.sin(a), z=0.3, axis="X", seg=8, rz=a)
    # LA ROUE: grande roue de hamster debout devant la chaudière, reliée par un axe
    wy, wz, wr = -3.5, 2.4, 2.2
    for sx in (-1, 1):  # chevalets à ±2.45 m (hors rayon wr=2.2)
        box(e, "stone_dark", 0.3, 0.3, wz, x=sx * 2.45, y=wy, z=0.0, rz=0)
        box(e, "stone_dark", 0.3, 0.9, 0.3, x=sx * 2.45, y=wy, z=wz - 0.15)
    cyl(e, "metal", 0.16, 1.8, y=-2.7, z=wz, axis="Y", seg=8)  # axe vers la chaudière
    wheel = marker("TLW_wheel", e, (0, wy, wz))  # la page fait tourner ce groupe
    ring(wheel, "wood", wr, 0.2, 0.18, 24, y=-0.50)
    ring(wheel, "wood", wr, 0.2, 0.18, 24, y=0.50)
    for i in range(24):  # barreaux sur lesquels court le hamster
        a = 2 * math.pi * i / 24
        cyl(wheel, "metal", 0.045, 1.0, x=(wr - 0.06) * math.cos(a), z=(wr - 0.06) * math.sin(a), axis="Y", seg=5)
    for i in range(6):  # rayons
        a = 2 * math.pi * i / 6
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(wr, 0.1, 0.1), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(wr / 2, 0, 0), verts=bm.verts)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(-a, 3, "Y"), verts=bm.verts)
        _finish(bm, wheel, "metal", (0, 0, 0))
    cyl(wheel, "fire", 0.36, 1.1, axis="Y", seg=10)  # moyeu incandescent


def b_tents(e):
    for x, y, r in [(-0.9, -0.7, 1.0), (0.9, -0.8, 0.9), (0.1, 0.9, 1.1)]:
        cyl(e, "canvas", r, 1.15 * r + 0.2, x=x, y=y, seg=4, r2=0.0, rz=math.pi / 4)
    cyl(e, "stone_dark", 0.32, 0.08, x=0.0, y=-0.1, seg=8)
    cyl(e, "fire", 0.18, 0.2, x=0.0, y=-0.1, z=0.08, seg=8, r2=0.02)


def b_cellar(e):
    cyl(e, "snow", 1.6, 0.7, seg=20, r2=1.15)
    box(e, "stone", 1.0, 0.5, 0.85, y=-1.35)
    box(e, "window", 0.55, 0.06, 0.55, y=-1.62)
    cyl(e, "metal", 0.13, 0.55, x=0.6, y=0.35, z=0.6, seg=8)


def b_workshop(e):
    w, d = 2.4, 1.8
    box(e, "wood", w, d, 1.3)
    roof(e, "snow", w, d, 0.9, z=1.3)
    box(e, "stone", 0.38, 0.38, 1.3, x=0.7, y=0.35, z=1.3)
    marker("TLW_smoke_workshop", e, (0.7, 0.35, 2.7))
    windows(e, w, d, [-0.6, 0.6], z=0.55)
    box(e, "door", 0.06, 0.6, 0.9, x=w / 2 + 0.02)


def b_bunkhouse(e):
    w, d = 3.2, 1.5
    box(e, "wall", w, d, 1.1)
    roof(e, "snow", w, d, 0.7, z=1.1)
    windows(e, w, d, [-1.0, 0.0, 1.0], z=0.45, size=(0.32, 0.38))
    box(e, "door", 0.06, 0.55, 0.85, x=w / 2 + 0.02)


def b_greenhouse(e):
    w, d = 2.6, 1.8
    box(e, "stone", w, d, 0.3)
    box(e, "greenhouse", w - 0.2, d - 0.2, 1.0, z=0.3)
    roof(e, "greenhouse", w - 0.2, d - 0.2, 0.75, z=1.3, over=0.05)
    for x in (-0.65, 0.0, 0.65):  # montants
        box(e, "wall_light", 0.08, d - 0.15, 1.0, x=x, z=0.3)


def b_insulation(e):
    box(e, "stone", 3.4, 0.4, 0.95, y=1.4)
    box(e, "snow", 3.5, 0.5, 0.1, y=1.4, z=0.95)
    box(e, "stone", 0.4, 2.8, 0.95, x=-1.5, y=-0.3)
    box(e, "snow", 0.5, 2.6, 0.1, x=-1.5, y=-0.4, z=0.95)
    box(e, "metal", 0.5, 0.5, 0.5, x=0.6, y=0.4)


def b_infirmary(e):
    w, d = 2.2, 2.0
    box(e, "wall_light", w, d, 1.4)
    box(e, "snow", w + 0.2, d + 0.2, 0.15, z=1.4)
    cyl(e, "window", 0.3, 0.06, y=-d / 2 - 0.02, z=0.85, axis="Y", seg=16)
    box(e, "door", 0.06, 0.6, 0.9, x=w / 2 + 0.02)
    box(e, "metal", 0.08, 0.08, 1.2, x=1.4, y=-1.3)
    box(e, "window", 0.2, 0.2, 0.22, x=1.4, y=-1.3, z=1.2)


def b_story_hall(e):
    cyl(e, "wall", 1.3, 1.3, seg=16)
    cyl(e, "snow", 1.6, 1.1, z=1.3, seg=16, r2=0.0)
    for deg in (-120, -75, -30, 15):
        a = math.radians(deg)
        box(e, "window", 0.32, 0.06, 0.45, x=1.32 * math.cos(a), y=1.32 * math.sin(a), z=0.45,
            rz=a + math.pi / 2)


def b_big_cellar(e):
    cyl(e, "snow", 2.1, 0.85, seg=24, r2=1.5)
    for x in (-0.7, 0.7):
        box(e, "stone", 0.9, 0.5, 0.85, x=x, y=-1.85)
        box(e, "window", 0.5, 0.06, 0.55, x=x, y=-2.12)
    for x, y in ((0.9, 0.5), (-0.6, 0.8)):
        cyl(e, "metal", 0.13, 0.6, x=x, y=y, z=0.75, seg=8)


def b_beacon(e):
    cyl(e, "stone", 0.8, 3.2, seg=4, r2=0.5, rz=math.pi / 4)
    cyl(e, "stone_dark", 0.75, 0.15, z=3.2, seg=4, rz=math.pi / 4)
    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        box(e, "metal", 0.08, 0.08, 0.6, x=0.35 * sx, y=0.35 * sy, z=3.35)
    cyl(e, "fire", 0.3, 0.45, z=3.35, seg=8, r2=0.1)
    cyl(e, "snow", 0.7, 0.55, z=3.95, seg=4, r2=0.0, rz=math.pi / 4)


def b_heat_pipes(e):
    for y in (-0.6, 0.6):
        cyl(e, "metal", 0.18, 3.4, y=y, z=0.35, axis="X", seg=12)
        for x in (-1.1, 0.0, 1.1):
            cyl(e, "fire", 0.22, 0.12, x=x, y=y, z=0.35, axis="X", seg=12)
            box(e, "stone_dark", 0.2, 0.3, 0.2, x=x + 0.4, y=y)
    cyl(e, "metal", 0.18, 1.6, x=1.5, z=0.35, axis="Y", seg=12)


def b_forge(e):
    w, d = 2.8, 2.0
    box(e, "stone_dark", w, d, 0.25)
    box(e, "metal", w - 0.3, d - 0.3, 1.6, z=0.25)
    box(e, "fire", 0.9, 0.7, 0.6, z=0.25)
    box(e, "stone", 0.45, 0.45, 2.2, x=0.7, y=0.6, z=1.6)
    marker("TLW_smoke_forge", e, (0.7, 0.6, 3.9))
    windows(e, w, d, [-0.7], z=0.85)


def b_deep_forge(e):
    w, d = 3.2, 2.4
    box(e, "stone_dark", w, d, 0.3)
    box(e, "metal", w - 0.2, d - 0.2, 1.8, z=0.3)
    for x in (-0.7, 0.7):
        box(e, "fire", 0.7, 0.6, 0.7, x=x, z=0.3)
    box(e, "stone", 0.5, 0.5, 2.8, x=-0.7, y=0.8, z=1.8)
    box(e, "stone", 0.5, 0.5, 2.8, x=0.7, y=0.8, z=1.8)
    marker("TLW_smoke_deep_forge1", e, (-0.7, 0.8, 4.7))
    marker("TLW_smoke_deep_forge2", e, (0.7, 0.8, 4.7))


def b_observatory(e):
    cyl(e, "stone", 1.1, 4.2, seg=8)
    cyl(e, "stone_dark", 1.3, 0.18, z=4.2, seg=8)
    cyl(e, "wall_light", 1.1, 1.2, z=4.38, seg=8, r2=0.0)
    for deg in (0, 90, 180, 270):
        a = math.radians(deg)
        box(e, "window", 0.32, 0.06, 0.4, x=1.13 * math.cos(a), y=1.13 * math.sin(a), z=4.6,
            rz=a + math.pi / 2)
    cyl(e, "metal", 0.055, 0.9, z=5.58, seg=6)


def b_hall_of_records(e):
    w, d = 3.2, 2.4
    box(e, "stone_dark", w + 0.1, d + 0.1, 0.25)
    box(e, "stone", w, d, 1.9, z=0.25)
    box(e, "snow", w + 0.2, d + 0.2, 0.12, z=2.15)
    for x in (-0.9, 0.0, 0.9):
        box(e, "window", 0.36, 0.06, 0.52, x=x, y=-d / 2 - 0.02, z=0.9)
    box(e, "door", 0.06, 0.7, 1.0, x=w / 2 + 0.02)


def b_outer_wall(e):
    box(e, "stone_dark", 5.2, 1.2, 0.22)
    box(e, "stone", 5.0, 1.0, 1.5, z=0.22)
    for x in (-1.75, -0.75, 0.25, 1.25):
        box(e, "stone", 0.62, 1.1, 0.55, x=x, z=1.72)
    for x in (-1.25, -0.25, 0.75, 1.75):
        box(e, "snow", 0.45, 1.1, 0.15, x=x, z=1.72)


def b_watchtower(e):
    cyl(e, "stone", 0.7, 5.5, seg=6)
    cyl(e, "stone_dark", 0.9, 0.18, z=5.5, seg=6)
    box(e, "stone", 2.4, 2.4, 0.2, z=5.68)
    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        box(e, "metal", 0.06, 0.06, 1.0, x=0.9 * sx, y=0.9 * sy, z=5.88)
    cyl(e, "fire", 0.12, 0.22, z=6.88, seg=8, r2=0.02)


def b_clinic(e):
    w, d = 2.4, 2.0
    box(e, "wall_light", w, d, 1.5)
    box(e, "snow", w + 0.15, d + 0.15, 0.12, z=1.5)
    box(e, "window", 0.15, 0.06, 0.6, y=-d / 2 - 0.02, z=0.65)
    box(e, "window", 0.4, 0.06, 0.18, y=-d / 2 - 0.02, z=0.95)
    box(e, "door", 0.06, 0.6, 0.9, x=w / 2 + 0.02)


def b_grand_hall(e):
    w, d = 4.5, 2.8
    box(e, "stone", w, d, 0.3)
    box(e, "wall", w - 0.2, d - 0.2, 1.8, z=0.3)
    roof(e, "snow", w - 0.2, d - 0.2, 1.0, z=2.1)
    for x in (-1.6, -0.8, 0.0, 0.8, 1.6):
        box(e, "window", 0.35, 0.06, 0.5, x=x, y=-d / 2 + 0.08, z=0.85)
    box(e, "door", 0.06, 0.8, 1.1, x=w / 2 + 0.02)


def b_mechanists(e):
    w, d = 3.0, 2.2
    box(e, "stone_dark", w, d, 0.22)
    box(e, "metal", w - 0.1, d - 0.1, 1.7, z=0.22)
    box(e, "snow", w + 0.1, d + 0.1, 0.1, z=1.92)
    for x in (-0.8, 0.8):
        cyl(e, "metal", 0.28, 0.12, x=x, y=-d / 2 - 0.01, z=0.9, axis="Y", seg=8)
        cyl(e, "fire", 0.15, 0.08, x=x, y=-d / 2 - 0.01, z=0.9, axis="Y", seg=8)
    cyl(e, "metal", 0.15, 3.0, x=-1.1, y=0.5, z=1.7, seg=8)
    marker("TLW_smoke_mechanists", e, (-1.1, 0.5, 4.8))
    windows(e, w, d, [0.2], z=1.0)


def b_thermal_heart(e):
    cyl(e, "stone_dark", 2.4, 0.4, seg=12)
    cyl(e, "metal", 1.8, 2.6, z=0.4, seg=12)
    cyl(e, "fire", 1.88, 0.5, z=1.2, seg=12)
    cyl(e, "stone_dark", 2.1, 0.28, z=3.0, seg=12)
    cyl(e, "metal", 1.8, 0.6, z=3.28, seg=12, r2=1.0)
    for i in range(4):
        a = math.pi / 2 * i
        cyl(e, "metal", 0.18, 1.8, x=1.8 * math.cos(a), y=1.8 * math.sin(a), z=0.5, axis="X", seg=8, rz=a)
        box(e, "fire", 0.3, 0.25, 0.25, x=1.8 * math.cos(a), y=1.8 * math.sin(a), z=0.5)


BUILDERS = {
    "generator": b_generator, "tents": b_tents, "cellar": b_cellar, "workshop": b_workshop,
    "bunkhouse": b_bunkhouse, "greenhouse": b_greenhouse, "insulation": b_insulation,
    "infirmary": b_infirmary, "story_hall": b_story_hall, "big_cellar": b_big_cellar,
    "beacon": b_beacon, "heat_pipes": b_heat_pipes,
    "forge": b_forge, "deep_forge": b_deep_forge, "observatory": b_observatory,
    "hall_of_records": b_hall_of_records, "outer_wall": b_outer_wall, "watchtower": b_watchtower,
    "clinic": b_clinic, "grand_hall": b_grand_hall, "mechanists": b_mechanists,
    "thermal_heart": b_thermal_heart,
}


# --------------------------------------------------------------- scène ---
def reset():
    old = bpy.data.collections.get(COLL_NAME)
    if old:
        for o in list(old.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(old)
    for m in [m for m in bpy.data.materials if m.name.startswith("TLW_")]:
        bpy.data.materials.remove(m)
    for me in [me for me in bpy.data.meshes if me.name.startswith("TLW_") and me.users == 0]:
        bpy.data.meshes.remove(me)
    c = bpy.data.collections.new(COLL_NAME)
    bpy.context.scene.collection.children.link(c)
    return c


def empty(name, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.5
    COLL.objects.link(e)
    e.location = (*loc, 0) if len(loc) == 2 else loc
    return e


def crater(parent, rng):
    """Cratère low-poly en grille polaire: fond plat et rond, falaises de roche, bord enneigé."""
    r_floor, r_wall, height = 22.5, 28.0, 9.0
    radii = [0, 6, 11, 14.5, 16] + [16 + 0.9 * i for i in range(1, 25)]  # serré sur les falaises
    sectors = 120
    off = Vector((rng.uniform(0, 100), rng.uniform(0, 100), 0))
    bm = bmesh.new()
    rows = []
    for i, r in enumerate(radii):
        row = []
        for j in range(sectors if r > 0 else 1):
            a = 2 * math.pi * (j + 0.5 * (i % 2)) / sectors
            x, y = r * math.cos(a), r * math.sin(a)
            t = min(max((r - r_floor) / (r_wall - r_floor), 0.0), 1.0)
            t = t * t * (3 - 2 * t)
            n = noise.noise(Vector((x * 0.11, y * 0.11, 0)) + off)
            n2 = noise.noise(Vector((x * 0.4, y * 0.4, 3)) + off)
            z = 0.0 if r <= r_floor else height * t + (3.0 * n + 0.9 * n2) * t
            row.append(bm.verts.new((x, y, z)))
        rows.append(row)
    for j in range(sectors):  # centre
        bm.faces.new((rows[0][0], rows[1][j], rows[1][(j + 1) % sectors]))
    for i in range(1, len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        for j in range(sectors):
            bm.faces.new((a[j], b[j], b[(j + 1) % sectors]))
            bm.faces.new((a[j], b[(j + 1) % sectors], a[(j + 1) % sectors]))
    bm.normal_update()
    for f in bm.faces:  # neige sur le plat et les pentes douces, roche sur les falaises
        f.material_index = 0 if f.normal.z > 0.8 else 1
    _n[0] += 1
    me = bpy.data.meshes.new(f"TLW_crater_{_n[0]}")
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = False
    me.materials.append(mat("snow"))    # slot 0 : neige
    me.materials.append(mat("rock"))    # slot 1 : roche
    o = bpy.data.objects.new(me.name, me)
    COLL.objects.link(o)
    o.parent = parent
    return o


def outer_plateau(parent):
    """Plateau enneigé bas-poly autour du cratère, jusqu'à l'horizon.
    L'anneau interne (r=28) raccorde au niveau moyen du rebord (z≈9). Au-delà, le terrain
    s'étend très loin et descend doucement : le brouillard de la page le fond dans le ciel,
    donc plus de vide visible autour de la carte, même en vue dézoomée sur écran large.
    """
    sectors = 96
    rings = [
        # (rayon, hauteur, relief) — le relief grandit avec la distance puis s'éteint à l'horizon
        (28, 9.0, 0.0),    # rebord intérieur : au niveau moyen des falaises du cratère
        (36, 9.5, 0.0),    # légère crête de neige au sommet du bord
        (54, 9.4, 0.7),    # plateau
        (72, 9.2, 1.5),
        (100, 8.9, 2.6),   # collines basses
        (140, 8.6, 3.6),
        (200, 8.2, 4.0),
        (280, 7.6, 2.8),
        (380, 7.0, 0.0),   # bord extérieur, noyé dans le brouillard bien avant d'être visible
    ]
    rng = random.Random(2026)
    bm = bmesh.new()
    rows = []
    for r, z, relief in rings:
        row = []
        for j in range(sectors):
            a = 2 * math.pi * j / sectors
            # ondulation douce (grandes collines) + un peu de grain pour les facettes low-poly
            wave = 0.6 * math.sin(3 * a + r / 17.0) + 0.4 * math.sin(5 * a - r / 9.0 + 1.3)
            h = z + relief * (0.75 * wave + 0.5 * rng.uniform(-1, 1))
            row.append(bm.verts.new((r * math.cos(a), r * math.sin(a), h)))
        rows.append(row)
    for i in range(len(rows) - 1):
        ra, rb = rows[i], rows[i + 1]
        for j in range(sectors):
            nj = (j + 1) % sectors
            # sens antihoraire vu d'en haut : la face regarde vers le ciel
            bm.faces.new((ra[j], rb[j], rb[nj], ra[nj]))
    bm.normal_update()
    me = bpy.data.meshes.new("TLW_plateau")
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = False
    me.materials.append(mat("snow"))
    o = bpy.data.objects.new(me.name, me)
    COLL.objects.link(o)
    o.parent = parent


PLAZA_R, PATH_START, PATH_LEN, RING_R, RING_R2 = 4.6, 4.2, 13.5, 9.85, 15.0


def puff_column(parent, x, y, z, rng, n=6, size=0.35):
    """Colonne de fumée low-poly, pour les images fixes seulement (la page anime sa propre fumée)."""
    for i in range(n):
        bm = bmesh.new()
        r = size * (1 + 0.28 * i)
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r)
        _finish(bm, parent, "smoke",
                (x + 0.3 * i + rng.uniform(-0.15, 0.15), y + 0.2 * i, z + 0.42 * i * (1 + 0.06 * i)))


def flat_arc_segments(parent, material, r, width, height, a_from, a_to, seg):
    """Arc de route horizontal (plan XY) approximé par des pavés, de a_from à a_to."""
    for i in range(seg):
        a = a_from + (a_to - a_from) * (i + 0.5) / seg
        arc_len = r * abs(a_to - a_from) / seg * 1.03
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(arc_len, width, height), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, height / 2), verts=bm.verts)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(a + math.pi / 2, 3, "Z"), verts=bm.verts)  # grand côté = tangente à l'arc
        bmesh.ops.translate(bm, vec=(r * math.cos(a), r * math.sin(a), 0), verts=bm.verts)
        _finish(bm, parent, material, (0, 0, 0))


def ground_details(rng):
    """Place + métadonnées chemins + arbres + rochers ; infrastructure progressive granulaire."""
    # TLW_fx: métadonnées pour la page, place centrale, décor statique (arbres, rochers)
    fx = empty("TLW_fx")
    # chaque route s'arrête devant le premier bâtiment de son axe (PATH_END) ; les marcheurs de la page font pareil
    ends = [PATH_END.get(k, PATH_START + PATH_LEN) for k in range(len(PATH_ANGLES))]
    fx["tlw"] = json.dumps({
        "paths": [round(a, 5) for a in PATH_ANGLES], "path_ends": [round(e, 2) for e in ends],
        "path_start": PATH_START, "path_end": round(max(ends, default=PATH_START + PATH_LEN), 2),
        "ring": RING_R, "ring2": RING_R2, "plaza": PLAZA_R,
    })
    cyl(fx, "plaza", PLAZA_R, 0.07, seg=32)

    # Traces de pas: 3 stades radiaux (s1=intérieur, s2=milieu, s3=extérieur), chacun sur le tiers de SA route
    for s_idx in range(1, 4):
        tracks_s = empty(f"TLW_infra_tracks_s{s_idx}")
        for k, a in enumerate(PATH_ANGLES):
            seg_r = (ends[k] - PATH_START) / 3
            mid_r = PATH_START + seg_r * (s_idx - 1) + seg_r / 2
            box(tracks_s, "stone_dark", 0.38, seg_r, 0.03,
                x=math.cos(a) * mid_r, y=math.sin(a) * mid_r, rz=a - math.pi / 2)

    # Chemin radial : 1 objet par direction pour la révélation route par route
    # TLW_infra_path_0 … TLW_infra_path_6 ; chacun contient 1 boîte, du centre jusqu'à PATH_END de sa route
    for idx, a in enumerate(PATH_ANGLES):
        path_e = empty(f"TLW_infra_path_{idx}")
        length = ends[idx] - PATH_START
        mid_r = PATH_START + length / 2
        box(path_e, "path", 1.1, length, 0.05,
            x=math.cos(a) * mid_r, y=math.sin(a) * mid_r, rz=a - math.pi / 2)

    # Anneau: 4 arcs N/E/S/O (chacun 90°, sens trigonométrique depuis N-E)
    arc_starts = [math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4]
    for n_idx, a_start in enumerate(arc_starts, 1):
        a_end = a_start + math.pi / 2
        ring_n = empty(f"TLW_infra_ring_n{n_idx}")
        flat_arc_segments(ring_n, "path", RING_R, 1.1, 0.04, a_start, a_end, seg=16)

    # Lampadaires intérieurs: 8 objets séparés, pivot à la base du mât
    for i in range(1, 9):
        la = 2 * math.pi * (i - 1) / 8 + math.pi / 8
        lx, ly = (RING_R + 1.1) * math.cos(la), (RING_R + 1.1) * math.sin(la)
        lamp_e = empty(f"TLW_infra_lamp_{i}", (lx, ly))
        cyl(lamp_e, "metal", 0.065, 3.1, seg=6)
        cyl(lamp_e, "fire", 0.14, 0.2, z=3.18, seg=8, r2=0.04)

    # Allées de porte (stade s4) : de l'anneau extérieur aux bâtiments tardifs posés entre deux routes
    paths_s4 = empty("TLW_infra_paths_s4")
    r_from, r_to = RING_R2 + 0.5, LATE_INNER_R - 0.1
    for a in LATE_ANGLE.values():
        box(paths_s4, "path", 0.9, r_to - r_from, 0.05,
            x=math.cos(a) * (r_from + r_to) / 2, y=math.sin(a) * (r_from + r_to) / 2, rz=a - math.pi / 2)

    # Allées de porte (stade s5) : de l'anneau intérieur aux bâtiments de l'anneau 2 posés entre les routes
    paths_s5 = empty("TLW_infra_paths_s5")
    r_from, r_to = RING_R + 0.6, 11.2
    for a in REPEAT_ANGLE:
        box(paths_s5, "path", 0.9, r_to - r_from, 0.05,
            x=math.cos(a) * (r_from + r_to) / 2, y=math.sin(a) * (r_from + r_to) / 2, rz=a - math.pi / 2)

    # Anneau extérieur (ring_n5: demi-anneau N-E, ring_n6: demi-anneau S-O)
    ring_n5 = empty("TLW_infra_ring_n5")
    for a_start in arc_starts[:2]:
        flat_arc_segments(ring_n5, "path", RING_R2, 1.0, 0.04, a_start, a_start + math.pi / 2, seg=16)

    ring_n6 = empty("TLW_infra_ring_n6")
    for a_start in arc_starts[2:]:
        flat_arc_segments(ring_n6, "path", RING_R2, 1.0, 0.04, a_start, a_start + math.pi / 2, seg=16)

    # Lampadaires extérieurs (lamp_9 à lamp_12) : juste dehors de l'anneau extérieur, dans les trouées
    # entre bâtiments tardifs (angles relevés avec tools/audit_scene.py)
    for i, deg in zip(range(9, 13), (358.0, 154.0, 218.6, 296.0)):
        la = math.radians(deg)
        lx, ly = (RING_R2 + 1.1) * math.cos(la), (RING_R2 + 1.1) * math.sin(la)
        lamp_e = empty(f"TLW_infra_lamp_{i}", (lx, ly))
        cyl(lamp_e, "metal", 0.065, 3.6, seg=6)
        cyl(lamp_e, "fire", 0.14, 0.2, z=3.68, seg=8, r2=0.04)

    # Arbres gelés — 3 silhouettes, 60 instances, clearance 3,2 m autour des bâtiments
    clear = {"thermal_heart": 4.6, "big_cellar": 4.0}  # rayon de dégagement autour du centre du bâtiment
    occupied = [(Vector((x, y)), clear.get(base_id(slot), 3.5 if math.hypot(x, y) > 11 else 3.0))
                for slot, (x, y) in LAYOUT.items()]

    def free_ground(p, margin=0.0):
        """Hors des bâtiments, hors de la bande de l'anneau extérieur."""
        if abs(p.length - RING_R2) < 1.4 + margin:
            return False
        return not any((p - o).length < c + margin for o, c in occupied)

    trees, essais = 0, 0
    while trees < 60 and essais < 6000:  # borne d'essais : la place libre est limitée par les bâtiments
        essais += 1
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(11.5, 21.5)
        p = Vector((r * math.cos(a), r * math.sin(a)))
        if not free_ground(p):
            continue
        if any(abs(math.atan2(math.sin(a - pa), math.cos(a - pa))) < 0.09 for pa in PATH_ANGLES):
            continue
        h = rng.uniform(1.2, 2.6)
        kind = trees % 3
        if kind == 0:
            # Type A : conifère élancé (silhouette actuelle)
            cyl(fx, "pine", 0.07, h * 0.35, x=p.x, y=p.y, seg=5)
            cyl(fx, "pine", 0.45 * h / 2, h, x=p.x, y=p.y, z=h * 0.25, seg=5, r2=0.0, rz=rng.uniform(0, 6))
            cyl(fx, "snow", 0.22 * h / 2, h * 0.35, x=p.x, y=p.y, z=h * 0.9, seg=5, r2=0.0)
        elif kind == 1:
            # Type B : pin enneigé bas (court, large calotte de neige)
            hs = h * 0.55
            cyl(fx, "pine", 0.09, hs * 0.28, x=p.x, y=p.y, seg=5)
            cyl(fx, "pine", 0.60 * hs / 2, hs, x=p.x, y=p.y, z=hs * 0.18, seg=5, r2=0.0, rz=rng.uniform(0, 6))
            cyl(fx, "snow", 0.38 * hs / 2, hs * 0.55, x=p.x, y=p.y, z=hs * 0.5, seg=5, r2=0.0)
        else:
            # Type C : arbre mort (voir dead_tree). Ses branches dépassent un peu : marge de dégagement en plus.
            if not free_ground(p, margin=0.8):
                continue
            dead_tree(fx, p, rng, rng.uniform(1.5, 2.8))
        trees += 1
    print(f"[TLW] décor : {trees} arbres posés")

    # Rochers — 3 formes, 40 instances en quinconce dans la couronne extérieure
    k, essais = 0, 0
    while k < 40 and essais < 6000:
        essais += 1
        a = rng.uniform(0, 2 * math.pi)
        if any(abs(math.atan2(math.sin(a - pa), math.cos(a - pa))) < 0.15 for pa in PATH_ANGLES):
            continue
        r = rng.uniform(11.5, 21.5)            # sur le sol plat, là où il reste de la place
        if not free_ground(Vector((r * math.cos(a), r * math.sin(a))), margin=0.6):
            continue
        form = k % 3
        bm = bmesh.new()
        if form == 0:
            # Forme A : icosphère aplatie (gros rocher)
            bmesh.ops.create_icosphere(bm, subdivisions=1, radius=rng.uniform(0.4, 1.0))
            bmesh.ops.scale(bm, vec=(rng.uniform(0.9, 1.3), rng.uniform(0.8, 1.2),
                                     rng.uniform(0.35, 0.65)), verts=bm.verts)
        elif form == 1:
            # Forme B : dalle angulaire (pavé plat)
            bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(rng.uniform(0.6, 1.4), rng.uniform(0.5, 1.0),
                                     rng.uniform(0.18, 0.38)), verts=bm.verts)
            bmesh.ops.rotate(bm, cent=(0, 0, 0),
                             matrix=Matrix.Rotation(rng.uniform(-0.5, 0.5), 3, "Z"), verts=bm.verts)
        else:
            # Forme C : pierre dressée (standing stone)
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=5,
                                  radius1=rng.uniform(0.25, 0.5), radius2=rng.uniform(0.08, 0.22),
                                  depth=rng.uniform(0.7, 1.5))
            bmesh.ops.translate(bm, vec=(0, 0, rng.uniform(0.6, 1.2)), verts=bm.verts)
        _finish(bm, fx, "rock", (r * math.cos(a), r * math.sin(a), -0.1))
        k += 1
    print(f"[TLW] décor : {k} rochers posés")

    # Détails de village (TLW_infra_village) — apparaissent à partir de 2 000 WU
    village = empty("TLW_infra_village")
    # 3 petits ponts aux croisements radiale × anneau intérieur
    for ki in (0, 2, 4):
        a = PATH_ANGLES[ki]
        bx = RING_R * math.cos(a)
        by_ = RING_R * math.sin(a)
        rz_b = a - math.pi / 2
        box(village, "stone", 1.2, 1.55, 0.1, x=bx, y=by_, z=0.04, rz=rz_b)   # dalle
        for sx in (-0.52, 0.52):
            box(village, "stone_dark", 0.28, 0.28, 0.38,
                x=bx + sx * math.cos(a + math.pi / 2),
                y=by_ + sx * math.sin(a + math.pi / 2), rz=rz_b)
    # 4 panneaux indicateurs aux fourches de chemin (r ≈ PLAZA_R + 1,8)
    for ki in (1, 2, 4, 5):
        a = PATH_ANGLES[ki]
        sr = PLAZA_R + 1.8
        sx = sr * math.cos(a) + 0.95 * math.cos(a + math.pi / 2)   # décalé sur le bord de la route
        sy_ = sr * math.sin(a) + 0.95 * math.sin(a + math.pi / 2)
        box(village, "wood", 0.08, 0.08, 1.05, x=sx, y=sy_)
        box(village, "wood", 0.50, 0.06, 0.18, x=sx, y=sy_, z=0.95, rz=a + math.pi / 2)


def still_smoke(rng):
    """Fumée figée au-dessus de chaque point TLW_smoke_*, pour les images fixes."""
    stills = empty("TLW_stillfx")
    bpy.context.view_layer.update()
    for o in list(COLL.objects):
        if o.name.startswith("TLW_smoke_"):
            p = o.matrix_world.translation
            big = o.name.startswith("TLW_smoke_gen")
            puff_column(stills, p.x, p.y, p.z, rng, n=10 if big else 6, size=0.3 if big else 0.18)
    return stills


def base_id(slot):
    """'bunkhouse_3' -> 'bunkhouse' ; 'story_hall' -> 'story_hall'."""
    head, _, tail = slot.rpartition("_")
    return head if head and tail.isdigit() else slot


def build_scene():
    rng = random.Random(SEED)
    for slot, (x, y) in LAYOUT.items():
        bid = base_id(slot)
        e = empty(f"TLW_{slot}", (x, y))
        if STYLE == "frost" and bid != "generator":
            e.rotation_euler.z = math.atan2(y, x) - math.pi / 2  # façade (-Y) tournée vers le générateur
        BUILDERS[bid](e)
    if STYLE == "frost":
        # 5 caisses séparées (TLW_supply_1..5) pour suppression individuelle par stade WU
        sup_base = (1.65, 2.86)  # entre les routes 30° et 90°, dans la place
        for k, (dx, dy, dz, rz) in enumerate([
            (-0.7, 0.0, 0.0, 0.30), (0.1, -0.1, 0.0, -0.20), (0.9, 0.05, 0.0, 0.15),
            (-0.3, 0.1, 0.55, 0.10), (0.55, -0.05, 0.55, -0.25),
        ], 1):
            se = empty(f"TLW_supply_{k}", (sup_base[0] + dx, sup_base[1] + dy, dz))
            box(se, "wood", 0.62, 0.62, 0.52, rz=rz)
            box(se, "stone_dark", 0.66, 0.66, 0.04, z=0.52)
    land = empty("TLW_land")
    if STYLE == "frost":
        crater(land, rng)
        outer_plateau(land)
        ground_details(rng)
        still_smoke(rng)
    else:
        box(land, "stone_dark", 27, 27, 2.4, z=-2.5)
        box(land, "snow", 27, 27, 0.12, z=-0.12)

    sun_data = bpy.data.lights.new("TLW_sun", "SUN")
    if hasattr(sun_data, "angle"):
        sun_data.angle = math.radians(3)
    sun = bpy.data.objects.new("TLW_sun", sun_data)
    COLL.objects.link(sun)
    if STYLE == "frost":
        sun_data.energy = 3.6
        sun_data.color = (0.72, 0.82, 1.0)
        sun.rotation_euler = (math.radians(68), 0, math.radians(-150))  # rasant: longues ombres
        heat = bpy.data.lights.new("TLW_heat", "POINT")
        heat.energy = 2500
        heat.color = (1.0, 0.5, 0.2)
        if hasattr(heat, "shadow_soft_size"):
            heat.shadow_soft_size = 0.6
        h = bpy.data.objects.new("TLW_heat", heat)
        COLL.objects.link(h)
        h.location = (*LAYOUT["generator"], 4.2)
    else:
        sun_data.energy = 2.4
        sun_data.color = (1.0, 0.97, 0.95)
        sun.rotation_euler = (math.radians(42), 0, math.radians(-22))

    cam_data = bpy.data.cameras.new("TLW_cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("TLW_cam", cam_data)
    COLL.objects.link(cam)
    cam.rotation_euler = CAM_ROT
    bpy.context.scene.camera = cam

    hero_data = bpy.data.cameras.new("TLW_cam_hero")
    hero_data.lens = 30
    hero_data.clip_end = 400
    hero = bpy.data.objects.new("TLW_cam_hero", hero_data)
    COLL.objects.link(hero)
    hero.location = (16, -30, 34)
    hero.rotation_euler = (Vector((0, 0, 0)) - hero.location).to_track_quat("-Z", "Y").to_euler()


def setup_render():
    sc = bpy.context.scene
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    # pastel: aplats fidèles à la palette. frost: rendu plus cinéma, les lumières ne brûlent pas
    for vt in (("Standard",) if STYLE == "pastel" else ("AgX", "Filmic", "Standard")):
        try:
            sc.view_settings.view_transform = vt
            break
        except TypeError:
            continue
    ee = sc.eevee
    for attr, val in (("use_bloom", True), ("bloom_intensity", 0.04), ("bloom_threshold", 1.0),
                      ("use_soft_shadows", True), ("use_gtao", True)):
        if hasattr(ee, attr):
            setattr(ee, attr, val)
    if not hasattr(ee, "use_bloom"):
        print("[TLW] Bloom EEVEE absent dans cette version: ajoute un nœud Glare (Bloom) dans le compositor.")
    w = sc.world or bpy.data.worlds.new("TLW_world")
    sc.world = w
    if w.node_tree is None:
        w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (*lin(WORLD_COLOR), 1)
        bg.inputs[1].default_value = WORLD_STRENGTH


def frame_camera(objs, margin=1.12):
    """Cadre la caméra iso sur un groupe d'objets."""
    bpy.context.view_layer.update()
    cam = bpy.context.scene.camera
    rot = cam.rotation_euler.to_matrix()
    right, up, fwd = rot @ Vector((1, 0, 0)), rot @ Vector((0, 1, 0)), rot @ Vector((0, 0, -1))
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    center = sum(pts, Vector()) / len(pts)
    xs = [(p - center).dot(right) for p in pts]
    ys = [(p - center).dot(up) for p in pts]
    sc = bpy.context.scene
    aspect = sc.render.resolution_x / sc.render.resolution_y
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    off = right * (max(xs) + min(xs)) / 2 + up * (max(ys) + min(ys)) / 2
    cam.data.ortho_scale = max(w, h * aspect) * margin
    cam.location = center + off - fwd * 60
    cam.data.clip_end = 200


def use_cycles(sc):
    sc.render.engine = "CYCLES"
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    try:  # carte graphique si possible
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
            except (TypeError, AttributeError):
                continue
            devs = [d for d in prefs.devices if d.type == kind]
            if devs:
                for d in devs:
                    d.use = True
                sc.cycles.device = "GPU"
                print(f"[TLW] Cycles sur GPU ({kind})")
                return
    except Exception:
        pass
    sc.cycles.device = "CPU"
    print("[TLW] Cycles sur CPU")


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print(f"[TLW] {path}")


def subtree(name):
    root = bpy.data.objects.get(name)
    return {root, *root.children_recursive} if root else set()


def export_glb(path):
    """Exporte la ville en un seul fichier 3D pour la page web.
    Sans lumières ni caméras (la page a les siennes) ni fumée figée (la page anime la sienne)."""
    skip = subtree("TLW_stillfx")
    keep = [o for o in COLL.objects if o.type in {"MESH", "EMPTY"} and o not in skip]
    if bpy.context.view_layer.objects.active is None and keep:
        bpy.context.view_layer.objects.active = keep[0]
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in keep:
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True, export_extras=True,
        export_lights=False, export_cameras=False, export_apply=False, export_yup=True,
    )
    for o in keep:
        o.select_set(False)
    print(f"[TLW] {path}")


def render_stills():
    sc = bpy.context.scene
    use_cycles(sc)
    groups = {o.name[4:]: [c for c in o.children_recursive] for o in COLL.objects
              if o.type == "EMPTY" and o.name.startswith("TLW_")}
    everything = [o for o in COLL.objects if o.type == "MESH"]
    # tout ce qui n'est pas la ville (cube et lampe par défaut, autres scènes...) est masqué au rendu
    ours = set(COLL.objects)
    foreign = {o: o.hide_render for o in sc.objects if o not in ours and o.type != "CAMERA"}
    for o in foreign:
        o.hide_render = True
    cam = bpy.data.objects["TLW_cam"]
    sc.camera = cam

    if SPRITES:  # un sprite par bâtiment, fond transparent, bâtiment remis droit (rotation 0)
        sc.render.film_transparent = True
        sc.render.resolution_x = sc.render.resolution_y = SPRITE_PX
        for bid in BUILDERS:
            e = bpy.data.objects[f"TLW_{bid}"]
            rz = e.rotation_euler.z
            e.rotation_euler.z = 0
            for o in everything:
                o.hide_render = o not in groups[bid]
            frame_camera(groups[bid])
            render(os.path.join(OUT_DIR, f"{bid}.png"))
            e.rotation_euler.z = rz

    sc.render.film_transparent = False
    sc.render.resolution_x, sc.render.resolution_y = OVERVIEW
    for o in everything:
        o.hide_render = False
    city = [o for slot in LAYOUT if slot in groups for o in groups[slot]]
    frame_camera(city, margin=1.6 if STYLE == "frost" else 1.05)
    render(os.path.join(OUT_DIR, "city_overview.png"))
    if "TLW_cam_hero" in bpy.data.objects:
        sc.camera = bpy.data.objects["TLW_cam_hero"]
        render(os.path.join(OUT_DIR, "city_hero.png"))
        sc.camera = cam
    for o, hidden in foreign.items():
        o.hide_render = hidden


if BUILD:
    COLL = reset()
    build_scene()
else:
    COLL = bpy.data.collections[COLL_NAME]
setup_render()
os.makedirs(OUT_DIR, exist_ok=True)
if EXPORT_GLB:
    export_glb(os.path.join(OUT_DIR, "city.glb"))
if RENDER:
    render_stills()
print(f"[TLW] Terminé. Fichiers dans {OUT_DIR} -> copie-les dans the-last-wheel/web/assets/")
