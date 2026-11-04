"""Audit de la scène 3D : détecte les chevauchements au sol (bâtiments, routes, anneaux, décor).

Usage (Blender 4.x / 5.x) :
  - depuis Blender : onglet Scripting > Open > ce fichier > Run Script (reconstruit la ville puis l'audite)
  - ou sans interface :  blender --background --python tools/audit_scene.py
  - ou avec le module bpy :  python tools/audit_scene.py

Chaque élément est projeté sur le sol (grille de 0,25 u). Une paire qui se recouvre de plus de SEUIL u²
alors qu'elle ne devrait pas est signalée. Le script s'arrête en erreur (code 1) s'il trouve un problème.
Il ne touche à aucun fichier : la ville est reconstruite sans export ni rendu.
"""
import collections
import math
import os
import re
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
CELL = 0.25          # taille d'une case de la grille (u)
SEUIL = 0.3          # recouvrement toléré (u²) : un simple effleurement
SOL_PLAT_MAX = 22.5  # rayon du fond plat du cratère (r_floor dans blender_city.py)


def build_city():
    """Reconstruit la ville dans la session, sans export ni rendu."""
    src = open(os.path.join(HERE, "blender_city.py"), encoding="utf-8").read()
    src = re.sub(r"^RENDER = True", "RENDER = False", src, flags=re.M)
    src = re.sub(r"^EXPORT_GLB = True", "EXPORT_GLB = False", src, flags=re.M)
    exec(compile(src, "blender_city.py", "exec"), {"__name__": "__tlw_audit__", "__file__": os.path.join(HERE, "blender_city.py")})


def descendants(o):
    out = [o]
    for c in o.children:
        out += descendants(c)
    return out


def _hull(pts):
    """Enveloppe convexe (chaîne monotone) d'une liste de points (x, y), sens antihoraire."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    low, up = [], []
    for p in pts:
        while len(low) >= 2 and cross(low[-2], low[-1], p) <= 0:
            low.pop()
        low.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return low[:-1] + up[:-1]


def footprint(root):
    """Cases (ix, iy) couvertes par un groupe vu de dessus : union des enveloppes convexes de ses objets.
    Les bâtiments, routes et décors sont faits de boîtes, cylindres et cônes, donc convexes un par un."""
    cells = set()
    for o in descendants(root):
        if o.type != "MESH" or not o.data.vertices:
            continue
        m = o.matrix_world
        pts = [(round((m @ v.co).x, 3), round((m @ v.co).y, 3)) for v in o.data.vertices]
        h = _hull(pts)
        if len(h) < 3:
            continue
        xs, ys = [p[0] for p in h], [p[1] for p in h]
        x0, x1 = int(math.floor(min(xs) / CELL)), int(math.floor(max(xs) / CELL))
        y0, y1 = int(math.floor(min(ys) / CELL)), int(math.floor(max(ys) / CELL))
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1), indexing="ij")
        px, py = (gx + .5) * CELL, (gy + .5) * CELL
        ok = np.ones(px.shape, dtype=bool)
        for i in range(len(h)):
            (ax, ay), (bx, by) = h[i], h[(i + 1) % len(h)]
            ok &= ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) >= -0.02
        for ix, iy in zip(gx[ok].tolist(), gy[ok].tolist()):
            cells.add((ix, iy))
    return cells


def genre(nom):
    if re.match(r"TLW_infra_path_\d$", nom) or nom in ("TLW_infra_paths_s4", "TLW_infra_paths_s5"):
        return "route"
    if nom.startswith("TLW_infra_ring"):
        return "anneau"
    if nom.startswith("TLW_infra_lamp"):
        return "lampadaire"
    if nom.startswith("TLW_infra_tracks") or nom.startswith("TLW_infra_village") or nom.startswith("TLW_supply"):
        return "detail"  # traces de pas, ponts, panneaux, caisses : faits pour toucher les routes
    return "bâtiment"


# paires de genres qui ne doivent PAS se chevaucher
INTERDIT = {("bâtiment", "bâtiment"), ("bâtiment", "route"), ("bâtiment", "anneau"), ("bâtiment", "lampadaire"),
            ("route", "lampadaire"), ("anneau", "lampadaire"), ("route", "route")}


def main():
    if bpy.data.objects.get("TLW_generator") is None:
        build_city()
    racines = [o for o in bpy.data.objects if o.parent is None and o.type == "EMPTY" and o.name.startswith("TLW_")]
    ignore = re.compile(r"TLW_(land|cam|cam_hero|sun|heat|stillfx|wheel|fx|smoke_.*)$")
    groupes = {o.name: footprint(o) for o in racines if not ignore.match(o.name)}
    groupes = {k: v for k, v in groupes.items() if v}
    pb = []
    noms = sorted(groupes)
    for i, x in enumerate(noms):
        for y in noms[i + 1:]:
            gx, gy = genre(x), genre(y)
            if tuple(sorted((gx, gy))) not in INTERDIT:
                continue
            # deux routes se croisent naturellement près du centre (place) : on ne vérifie que hors de la place
            ov = len(groupes[x] & groupes[y]) * CELL * CELL
            if ov > SEUIL:
                pb.append(f"{gx} × {gy} : {x[4:]} / {y[4:]}  ({ov:.1f} u²)")

    # décor (arbres, rochers) : un par un, contre bâtiments / routes / anneaux
    fx = bpy.data.objects.get("TLW_fx")
    decor = 0
    if fx:
        durs = {n: s for n, s in groupes.items() if genre(n) in ("bâtiment", "route", "anneau")}
        for c in fx.children:
            mats = {m.name for m in getattr(c.data, "materials", []) if m} if c.type == "MESH" else set()
            if not mats & {"TLW_pine", "TLW_rock", "TLW_snow"}:
                continue
            cells = footprint(c)
            for n, s in durs.items():
                ov = len(cells & s) * CELL * CELL
                if ov > 0.15:
                    pb.append(f"décor × {genre(n)} : {c.name} / {n[4:]}  ({ov:.2f} u²)")
            decor += 1

    # bâtiments et décor sur le sol plat du cratère
    hors = []
    for n, s in groupes.items():
        if genre(n) == "bâtiment" and n != "TLW_generator":
            rmax = max(math.hypot((i + .5) * CELL, (j + .5) * CELL) for i, j in s)
            if rmax > SOL_PLAT_MAX:
                hors.append(f"{n[4:]} dépasse le sol plat (r={rmax:.1f} > {SOL_PLAT_MAX})")
    pb += hors

    print(f"\n[audit] {len(groupes)} groupes, {decor} éléments de décor contrôlés")
    if pb:
        print(f"[audit] {len(pb)} problème(s) :")
        for ligne in pb:
            print("  -", ligne)
        sys.exit(1)
    print("[audit] OK — aucun chevauchement, tout est sur le sol plat.")


main()
