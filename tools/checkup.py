"""Bilan de santé de la ville en une commande, à lancer sur le Pi (ou sur le PC si la ville y tourne).

Usage :
    python3 tools/checkup.py            # port 8080 par défaut
    python3 tools/checkup.py --port 8081

Lecture seule : il interroge la page locale de la ville (/api/state, /api/chronicle) et, sur le Pi, l'état du service.
Il ne modifie rien. Copie-colle son résultat à Claude pour un diagnostic.
"""
import json
import shutil
import subprocess
import sys
import urllib.request

PORT = 8080
if "--port" in sys.argv:
    PORT = int(sys.argv[sys.argv.index("--port") + 1])
BASE = f"http://127.0.0.1:{PORT}"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=8) as r:
        return json.load(r)


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return None


def num(n):
    return "inconnu" if n is None else f"{n:,}".replace(",", " ")


def main():
    problems, watch = [], []
    service_state = None
    print("=== The Last Wheel — bilan de santé ===")

    # service (Pi / Linux seulement)
    if shutil.which("systemctl"):
        active = run(["systemctl", "is-active", "the-last-wheel"])
        print(f"Service           : {active or 'inconnu'}")
        service_state = active
        if shutil.which("journalctl"):
            errs = run(["journalctl", "-u", "the-last-wheel", "--since", "1 hour ago", "-p", "err", "--no-pager", "-q"])
            n_err = len([l for l in (errs or "").splitlines() if l.strip()])
            print(f"Erreurs (1 h)     : {n_err}")
            if n_err:
                problems.append(f"{n_err} ligne(s) d'erreur dans le journal : journalctl -u the-last-wheel -p err --since '1 hour ago'")

    try:
        s = get("/api/state")
        chron = get("/api/chronicle?since=0")
    except Exception as e:
        print(f"La ville ne répond pas sur {BASE} ({type(e).__name__}).")
        print("VERDICT : PROBLÈME — le programme ne tourne pas ou n'écoute pas sur ce port.")
        return 1

    if service_state in ("inactive", "failed"):
        watch.append("la ville répond mais le service n'est pas actif : elle a été lancée à la main et ne redémarrera pas seule")
    h = s.get("hamster", {})
    link = h.get("link", "live")
    print(f"Mode              : {s.get('mode')}   |   signal : {link} ({h.get('api')})")
    if s.get("mode") == "sim":
        watch.append("mode simulation : ce n'est pas le vrai hamster")
    if link not in ("live", "sim"):
        watch.append(f"signal {link} : la colonie est en pause tant que la donnée est inconnue")
    run_txt = f"court à {round((h.get('rpm') or 0) / 1000)} tours/min" if h.get("active") else "au repos"
    km = f", {h['distance_mm'] / 1e6:.2f} km aujourd'hui" if h.get("distance_mm") else ""
    print(f"Hamster           : {run_txt}{km}")
    print(f"Ville             : {'nuit' if s.get('phase') == 'night' else 'jour'} n°{s.get('nights')}, météo {s.get('weather')}, "
          f"{s.get('temperature'):.0f} °C")
    print(f"Chaleur / givre   : {round(s.get('reserve', 0))} / {s.get('reserve_cap')}   |   givre {round(s.get('frost', 0) * 100)} %"
          + ("   |   HIBERNATION" if s.get("frozen") else ""))
    if s.get("frozen"):
        watch.append("la ville hiberne (plus de chaleur) : normal si le hamster dort longtemps, elle repart quand il court")
    print(f"Population        : {s.get('population')} / {s.get('capacity')}" + (f"  (+{s.get('waiting')} au camp)" if s.get("waiting") else ""))
    built = s.get("built", {})
    proj = s.get("project")
    print(f"Bâtiments         : {sum(built.values())}" + (f"   |   chantier : {proj['name']} {proj['pct']} %" if proj else ""))
    print(f"Travail cumulé    : {num(s.get('total_work'))} unités de la colonie")

    ch = s.get("chain")
    if ch:
        st = ch.get("settlements") or {}
        print(f"Chaîne            : live {num(ch.get('live_work'))}  |  réglé {num(ch.get('settled_work'))}  |  "
              f"{len(st.get('items', []))} lot(s) lus ({st.get('status')})")
        if st.get("status") != "ok":
            watch.append("les lots Ethereum ne sont pas lus (normal pendant la première minute)")

    print("Dernières lignes de la chronique :")
    for e in chron[-5:]:
        print("  -", e["text"][:110])

    print()
    if problems:
        print("VERDICT : PROBLÈME")
        for p in problems:
            print("  *", p)
        return 1
    if watch:
        print("VERDICT : OK, avec des points à surveiller")
        for w in watch:
            print("  *", w)
        return 0
    print("VERDICT : TOUT VA BIEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
