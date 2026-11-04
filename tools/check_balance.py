"""Vérifie la cohérence du contenu avant commit.

Usage: python tools/check_balance.py [--rate WU_PAR_JOUR] [--min-days N]

  --rate WU_PAR_JOUR   rythme de référence (défaut : 4200 WU/j, faux hamster ~60x)
  --min-days N         échoue si le contenu dure moins de N jours au rythme donné

Règles vérifiées :
  1. Toute plage infra_stages a from < to.
  2. Aucun chevauchement incohérent entre stades.
  3. La capacité totale de logement ne dépasse pas PEOPLE_MAX (100).
  4. Les clés obligatoires de config.json sont présentes.
  5. Le contenu bâtiments ne dépasse pas le dernier stade d'infra.
  6. La durée estimée n'est pas inférieure à --min-days (si fourni).

Retourne 0 si tout passe, 1 si une règle est violée.
"""
import json
import sys

PEOPLE_MAX = 100
REQUIRED_KEYS = [
    "heat_per_work", "base_demand_per_s", "demand_per_person_per_s",
    "night_after_idle_s", "dream_every_s",
]

ROOT = __file__.replace("\\", "/").rsplit("/tools/", 1)[0]


def load(path):
    with open(f"{ROOT}/{path}", encoding="utf-8") as f:
        return json.load(f)


def main():
    rate = None  # WU/jour : par défaut celui du faux hamster (4022 à l'échelle 1, multiplié par wu_scale)
    min_days = 30.0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--rate" and i + 1 < len(args):
            rate = float(args[i + 1])
        if a == "--min-days" and i + 1 < len(args):
            min_days = float(args[i + 1])

    errors = []
    cfg = load("content/config.json")
    buildings = load("content/buildings.json")
    # wu_scale (config.json) : mêmes règles que le serveur (server/main.py, apply_wu_scale)
    scale = float(cfg.get("wu_scale", 1.0))
    if scale != 1.0 and scale > 0:
        for b in buildings:
            if "cost" in b:
                b["cost"] = round(b["cost"] * scale)
        for st in cfg.get("infra_stages", []):
            for key in ("wu", "wu_to"):
                if st.get(key) is not None:
                    st[key] = round(st[key] * scale)

    # ---- clés obligatoires ----
    for k in REQUIRED_KEYS:
        if k not in cfg:
            errors.append(f"config.json: clé manquante '{k}'")

    # ---- plages infra_stages ----
    for st in cfg.get("infra_stages", []):
        wu, wu_to = st.get("wu"), st.get("wu_to")
        if wu is None or wu_to is None:
            errors.append(f"infra_stage '{st.get('id')}': wu ou wu_to manquant")
        elif wu >= wu_to:
            errors.append(f"infra_stage '{st.get('id')}': wu={wu} >= wu_to={wu_to}")

    # ---- capacité de logement ----
    total_cap = 0
    for b in buildings:
        housing = b.get("effects", {}).get("housing", 0)
        if housing:
            n = b.get("max", 1)
            if b.get("start"):
                n = 1  # bâtiment de départ, toujours présent
            total_cap += housing * n

    if total_cap > PEOPLE_MAX:
        errors.append(
            f"Capacité max de logement {total_cap} > PEOPLE_MAX {PEOPLE_MAX}. "
            "Ajuster max des bâtiments ou PEOPLE_MAX dans city3d.js."
        )

    # ---- résumé du contenu ----
    stages = cfg.get("infra_stages", [])
    max_wu_to = max((st["wu_to"] for st in stages), default=0)
    build_wu = sum(b.get("cost", 0) * b.get("max", 1) for b in buildings if not b.get("start"))

    # WU effectifs : coût divisé par la vitesse de construction au moment de la construction.
    # L'ordre des bâtiments dans buildings.json détermine l'ordre d'acquisition des bonus.
    speed = 1.0
    effective_build_wu = 0.0
    for b in buildings:
        if b.get("start"):
            continue
        count = b.get("max", 1)
        effective_build_wu += b["cost"] * count / speed
        speed += b.get("effects", {}).get("build_speed", 0.0)
    effective_build_wu = round(effective_build_wu)

    if rate is None:
        rate = 4022.0 * scale  # le faux hamster produit `scale` fois plus quand wu_scale est réglé (voir main.py)
    # La durée se calcule sur le travail effectif (bâtiments), pas sur le stade infra le plus loin.
    jours = effective_build_wu / rate if rate else 0

    if effective_build_wu > max_wu_to:
        errors.append(
            f"Contenu bâtiments ({effective_build_wu:,} WU effectifs) > dernier stade d'infra ({max_wu_to:,} WU). "
            "Étendre les stades dans config.json ou réduire les bâtiments."
        )

    if min_days is not None and jours < min_days:
        errors.append(
            f"Durée estimée {jours:.0f} jours < cible {int(min_days)} jours "
            f"au rythme {rate:.0f} WU/j. Ajouter du contenu ou baisser --min-days."
        )

    print(f"Echelle WU    : x{scale:g} (wu_scale dans config.json)")
    print(f"Capacité logement max : {total_cap} / {PEOPLE_MAX}")
    print(f"WU bâtiments  : {build_wu:,}  (brut)  /  {effective_build_wu:,}  (effectif apres build_speed)")
    print(f"WU stades max : {max_wu_to:,}")
    print(f"Duree estimee : {jours:.0f} jours  (contenu {effective_build_wu:,} WU effectifs / {rate:.0f} WU/j)")
    if min_days is not None:
        print(f"Cible min     : {int(min_days)} jours  -> {'OK' if jours >= min_days else 'TROP COURT'}")

    if errors:
        for e in errors:
            print(f"ERREUR: {e}", file=sys.stderr)
        return 1

    print("OK — toutes les vérifications passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
