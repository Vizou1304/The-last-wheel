"""Lit l'historique réel du hamster sur l'API Squeekchain et dit combien de temps durera le contenu du jeu.

Usage (sur ton PC, dans le dossier the-last-wheel) :
    python tools/fetch_pace.py                  # 7 et 30 derniers jours
    python tools/fetch_pace.py --target 30      # durée visée en jours (défaut 30)

Lecture seule : un appel par période sur /v1/measurement/stats, rien n'est écrit ni modifié.
Le script propose une valeur pour `wu_scale` dans content/config.json (1.0 = contenu actuel). Rien n'est changé tout seul.

Champs lus (docs.squeekchain.com/developers/api, schéma measurement-stats.json) :
    activity.summary.{observedWorkUnits, activeDayCount, inactiveDayCount, medianWorkPerActiveDay}
    activity.coverage.complete, records.peakObservedRpmMilli
Les grands nombres sont des chaînes décimales. « unavailable » ou null = inconnu, jamais zéro.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.environ.get("SQUEEK_API_BASE", "https://api.squeekchain.com")


def get(range_):
    req = urllib.request.Request(f"{API}/v1/measurement/stats?range={range_}",
                                 headers={"accept": "application/json", "user-agent": "the-last-wheel/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def current_scale():
    """Valeur actuelle de wu_scale dans content/config.json."""
    try:
        with open(os.path.join(ROOT, "content", "config.json"), encoding="utf-8") as f:
            return float(json.load(f).get("wu_scale", 1.0))
    except Exception:
        return 1.0


def content_wu():
    """Travail effectif du contenu actuel (bâtiments), selon check_balance.py, wu_scale déjà appliqué."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_balance.py"), "--min-days", "0"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("WU bâtiments"):
            return as_int(line.split("/")[1].split("(")[0].replace(",", "").replace(" ", "").replace(" ", ""))
    return None


def report(label, data, base_wu, target):
    act = (data.get("activity") or {})
    s = act.get("summary") or {}
    observed = as_int(s.get("observedWorkUnits"))
    active, inactive = s.get("activeDayCount"), s.get("inactiveDayCount")
    median = as_int(s.get("medianWorkPerActiveDay"))
    print(f"\n=== {label} ===")
    if observed is None or not active:
        print("Pas assez de données pour calculer un rythme (aucun jour actif observé, ou donnée indisponible).")
        return None
    per_active = observed / active
    per_all = observed / (active + (inactive or 0))
    print(f"Travail observé        : {observed:,} unités sur {active} jour(s) actif(s) et {inactive} jour(s) sans activité")
    print(f"Moyenne, jours actifs  : {per_active:,.0f} unités/jour")
    print(f"Moyenne, tous les jours: {per_all:,.0f} unités/jour")
    if median is not None:
        print(f"Médiane, jours actifs  : {median:,} unités/jour")
    # heure de pointe : début (en minutes UTC) de la demi-heure la plus active, converti à l'heure de cet ordinateur
    peak = as_int(s.get("peakWindowStartMinuteUtc"))
    if peak is not None:
        local = (peak + time.localtime().tm_gmtoff // 60) % 1440
        print(f"Demi-heure la plus active : {local // 60:02d}h{local % 60:02d} (heure de cet ordinateur)"
              + (f", jour record : {s.get('mostActiveDate')}" if s.get("mostActiveDate") else ""))
    cov = act.get("coverage") or {}
    if cov.get("complete") is False:
        print("ATTENTION : la couverture n'est pas complète (le compteur n'a pas tout observé) : le vrai rythme peut être plus haut.")
    peak = ((data.get("records") or {}).get("peakObservedRpmMilli") or {}).get("value")
    if as_int(peak):
        print(f"Vitesse record observée: {as_int(peak) / 1000:.0f} tours/min")
    if base_wu:
        k = current_scale()
        for name, pace in (("jours actifs", per_active), ("tous les jours", per_all)):
            days = base_wu / pace
            scale = k * pace * target / base_wu  # valeur ABSOLUE à écrire dans config.json (le contenu actuel inclut déjà wu_scale = k)
            print(f"Contenu actuel ({base_wu:,} unités, wu_scale = {k:g}) au rythme « {name} » : {days:.1f} jours"
                  f"  -> pour viser {target} jours : \"wu_scale\": {scale:.2f}")
    return per_active, per_all


def main():
    target = 30
    if "--target" in sys.argv:
        target = int(sys.argv[sys.argv.index("--target") + 1])
    base = content_wu()
    print("Historique réel du hamster (API Squeekchain, réseau Sepolia). Lecture seule.")
    for i, (label, rng) in enumerate((("7 derniers jours", "7d"), ("30 derniers jours", "30d"))):
        if i:
            time.sleep(1.5)  # l'API limite à 5 appels/s ; on reste très en dessous
        try:
            data = get(rng)
        except urllib.error.HTTPError as e:
            print(f"\n=== {label} ===\nL'API a répondu {e.code}. Réessaie dans une minute.")
            continue
        except Exception as e:
            print(f"\n=== {label} ===\nImpossible de joindre l'API ({type(e).__name__}). Vérifie ta connexion.")
            continue
        if isinstance(data, dict) and data.get("status") == "unavailable":
            print(f"\n=== {label} ===\nDonnée indisponible côté API (inconnu, pas zéro).")
            continue
        report(label, data, base, target)
    print("\nPour changer la durée du contenu : ouvre content/config.json, mets la valeur proposée dans \"wu_scale\","
          "\npuis lance  python tools/check_balance.py  pour vérifier. Un historique court ou incomplet donne un rythme"
          "\nincertain : recalcule après quelques jours de live.")


if __name__ == "__main__":
    main()
