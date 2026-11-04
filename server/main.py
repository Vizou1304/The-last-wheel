#!/usr/bin/env python3
"""The Last Wheel — simulation, chronique et page web.

  python3 server/main.py                         # ville réelle, branchée sur l'API Squeekchain
  python3 server/main.py --sim --speed 60        # faux hamster, 1 h simulée par minute
  python3 server/main.py --sim --speed 0 --hours 168 --quiet --fresh   # 7 jours d'équilibrage d'un coup

La ville simulée (--sim) a sa propre sauvegarde: elle ne touche jamais la ville réelle.
La page web est servie sur http://<ip-du-pi>:8080 (désactiver avec --no-web).
"""
import argparse
import json
import os
import random
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state as store  # noqa: E402
from chronicle import Chronicle, fmt_duration  # noqa: E402
from feed import LiveFeed, SimFeed  # noqa: E402
from settlements import SettlementsFeed  # noqa: E402
from sim import City  # noqa: E402
from web import Shared, serve  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")
DATA = os.environ.get("TLW_DATA", os.path.join(ROOT, "data"))
API_URL = os.environ.get("SQUEEK_API", "https://api.squeekchain.com/v1/status")
SETTLE_URL = os.environ.get("SQUEEK_SETTLEMENTS", API_URL.rsplit("/", 1)[0] + "/settlements?range=24h")
PAUSE_LINKS = ("lost", "fault", "unverified")  # états où le hamster est inconnu (voir feed.py)
WEB_DIR = os.path.join(ROOT, "web")


def load_json(name):
    with open(os.path.join(CONTENT, name), encoding="utf-8") as f:
        return json.load(f)


def status_line(city, smp, now):
    v = city.snapshot(smp["rpm"])
    p = v["project"]
    proj = f"{p['name']} {p['pct']}%" if p else "-"
    phase = "HIBERNATION" if v["frozen"] else v["phase"]
    wait = f"+{v['waiting']} camp" if v["waiting"] else ""
    return (f"[{time.strftime('%a %H:%M', time.localtime(now))}] {phase:<11} "
            f"{v['temperature']:>6.1f}°C  heat {v['reserve']}/{v['reserve_cap']}  "
            f"frost {round(v['frost'] * 100)}%  pop {v['population']}/{v['capacity']}{wait}  "
            f"build: {proj}  api={smp['status']}")


def summary(city):
    s = city.s
    st = s["stats"]
    el = max(st["elapsed_s"], 1)
    built = ", ".join(f"{k}x{n}" if n > 1 else k for k, n in s["built"].items())
    print("\n===== RÉSUMÉ =====")
    print(f"durée simulée   : {fmt_duration(el)} ({el / 86400:.1f} jours)")
    print(f"hamster actif   : {100 * st['active_s'] / el:.0f}% du temps, {s['total_work']} work units")
    print(f"ville gelée     : {100 * st['frozen_s'] / el:.0f}% du temps, givre actuel {round(s['frost'] * 100)}%")
    jours = el / 86400
    if jours >= 1:
        print(f"chaleur produite : {st.get('heat_produced', 0) / jours:.0f} unités/jour")
        print(f"chaleur consommée: {st.get('heat_consumed', 0) / jours:.0f} unités/jour")
    print(f"population      : {s['population']} (+{s['waiting']} au camp), capacité {city.capacity()}")
    print(f"bâtiments       : {built}")
    print(f"nuits / rêves   : {s['nights']} / {s['dreams']}")
    r = s["records"]
    print(f"records         : {r['max_rpm'] / 1000:.0f} tr/min, sprint {fmt_duration(r['longest_sprint_s'])}, "
          f"sieste {fmt_duration(r['longest_sleep_s'])}")
    print(f"chronique       : {sum(city.ch.counts.values())} lignes {dict(city.ch.counts)}")


def apply_wu_scale(cfg, buildings):
    """Un seul réglage (`wu_scale` dans config.json) pour recaler le jeu sur le vrai rythme du hamster.
    C'est un facteur de conversion : si le hamster produit k fois plus de travail que prévu, tout ce qui se compte en
    work units est multiplié par k (coût des bâtiments, seuils des stades, espacement des arrivées) et tout ce qui
    est donné par work unit est divisé par k (chaleur, dégivrage). Le jeu garde alors exactement le même équilibre,
    simplement au rythme réel. Le faux hamster (--sim) produit aussi k fois plus, pour que les tests restent comparables.
    1.0 = valeurs écrites dans les fichiers."""
    k = float(cfg.get("wu_scale", 1.0))
    if k == 1.0 or k <= 0:
        return
    for b in buildings:
        if "cost" in b:
            b["cost"] = round(b["cost"] * k)
    for st in cfg.get("infra_stages", []):
        for key in ("wu", "wu_to"):
            if st.get(key) is not None:
                st[key] = round(st[key] * k)
    cfg["heat_per_work"] = cfg["heat_per_work"] / k
    cfg["thaw_per_work"] = cfg["thaw_per_work"] / k
    cfg["arrivals"]["every_blocks"] = max(1, round(cfg["arrivals"]["every_blocks"] * k))
    cfg["sim"]["work_per_rev"] = cfg["sim"]["work_per_rev"] * k


def main():
    ap = argparse.ArgumentParser(description="The Last Wheel — V0")
    ap.add_argument("--sim", action="store_true", help="faux hamster au lieu de l'API")
    ap.add_argument("--speed", type=float, default=1, help="sim: accélération (0 = le plus vite possible)")
    ap.add_argument("--hours", type=float, default=0, help="sim: s'arrêter après N heures simulées")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--fresh", action="store_true", help="repartir d'une ville neuve")
    ap.add_argument("--quiet", action="store_true", help="pas de chronique ni de statut, juste le résumé")
    ap.add_argument("--no-web", action="store_true", help="ne pas lancer la page web")
    ap.add_argument("--host", default=os.environ.get("TLW_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TLW_PORT", "8080")))
    args = ap.parse_args()

    cfg = load_json("config.json")
    buildings = load_json("buildings.json")
    phrases = load_json("phrases.json")
    apply_wu_scale(cfg, buildings)
    os.makedirs(DATA, exist_ok=True)
    tag = "sim" if args.sim else "live"
    state_path = os.path.join(DATA, f"state_{tag}.json")
    chron_path = os.path.join(DATA, f"chronicle_{tag}.jsonl")
    if args.fresh:
        for p in [state_path, chron_path] + [f"{state_path}.{i}" for i in range(1, 4)]:
            if os.path.exists(p):
                os.remove(p)

    rng = random.Random(args.seed)
    saved = store.load(state_path) or {}
    chron = Chronicle(phrases, chron_path, rng, echo=not args.quiet)
    chron.load_recent()
    city = City(cfg, buildings, chron, rng, saved.get("city"))
    feed = SimFeed(cfg, rng) if args.sim else LiveFeed(API_URL, cfg["poll_seconds"], cfg.get("max_work_per_s", 16.7))
    feed.restore(saved.get("feed"))
    settle = None if args.sim else SettlementsFeed(SETTLE_URL, cfg.get("settlements_poll_s", 60))
    if settle and not args.no_web:
        settle.start()

    shared = None
    if not args.no_web:
        shared = Shared()
        try:
            serve(shared, WEB_DIR, args.host, args.port)
            if not args.quiet:
                print(f"Page web: http://localhost:{args.port}  (ou http://<ip-du-pi>:{args.port})")
        except OSError as e:
            print(f"[web] impossible d'ouvrir le port {args.port}: {e}")
            shared = None
    catalog = [{"id": b["id"], "name": b["name"]} for b in buildings]
    last_pub = 0.0

    def publish(smp, now):
        v = city.snapshot(smp["rpm"])
        v.update({
            "t": now, "mode": tag,
            "hamster": {"rpm": smp["rpm"], "active": bool(smp["active"]), "sprinting": bool(city.s["sprint_since"]), "api": smp["status"],
                        "link": smp.get("link", "live"), "distance_mm": smp.get("distance_mm")},
            "catalog": catalog,
            # « live » (mesuré par la roue) et « réglé » (écrit sur Ethereum) sont deux chiffres séparés ; None = inconnu
            "chain": None if settle is None else {
                "live_work": smp.get("live_total"), "settled_work": smp.get("settled_total"),
                "settlements": settle.snapshot(), "explorer_tx": cfg.get("explorer_tx_url", ""),
            },
        })
        shared.publish(v, chron.recent)

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    def save():
        store.save(state_path, {"city": city.s, "feed": feed.export()})

    dt = float(cfg["poll_seconds"])
    now = time.time()
    if args.sim and city.s["t"]:
        now = city.s["t"]  # la ville simulée reprend à son heure virtuelle
    start, last_save, last_status = now, now, now - cfg["status_every_s"]
    next_day_mark = start + 86400  # pour le log jour par jour
    day_num = 0
    prev_frozen_s = 0.0
    if args.quiet and args.hours:
        print(f"J01  reserve={round(city.s['reserve']):>5}  givre={round(city.s['frost']*100):>3}%  gel_h=  0.0h  tw=0", flush=True)
    if not args.quiet:
        print(f"The Last Wheel — mode {tag}" + (f", x{args.speed:g}" if args.sim else f", {API_URL}"))

    while running:
        smp = feed.read(now, dt)
        if smp.get("link", "live") in PAUSE_LINKS:
            city.pause(now, dt)   # donnée inconnue : la colonie attend, elle ne gèle ni ne s'endort
        else:
            city.tick(now, dt, smp)
        if shared and time.time() - last_pub >= 0.5:
            publish(smp, now)
            last_pub = time.time()

        if now - last_status >= cfg["status_every_s"] and not args.quiet:
            print(status_line(city, smp, now), flush=True)
            last_status = now
        if now - last_save >= cfg["save_every_s"]:
            save()
            last_save = now
        if args.hours and now - start >= args.hours * 3600:
            break
        # log jour par jour (mode --quiet uniquement pour ne pas polluer le mode normal)
        if args.quiet and args.hours and now >= next_day_mark:
            day_num += 1
            v = city.s
            frozen_s = v["stats"]["frozen_s"]
            gel_h = (frozen_s - prev_frozen_s) / 3600
            prev_frozen_s = frozen_s
            # imprime le début du PROCHAIN jour (= fin du jour qui vient de s'écouler)
            print(f"J{day_num + 1:02d}  reserve={round(v['reserve']):>5}  givre={round(v['frost']*100):>3}%  "
                  f"gel_h={gel_h:>4.1f}h  tw={v['total_work']}", flush=True)
            next_day_mark += 86400

        if args.sim:
            now += dt
            if args.speed > 0:
                time.sleep(dt / args.speed)
        else:
            time.sleep(max(0.0, dt - (time.time() - now)))
            prev, now = now, time.time()
            dt = min(max(now - prev, 0.5), 10.0)  # après une coupure: pas de rattrapage géant

    save()
    if args.sim or args.quiet:
        summary(city)


if __name__ == "__main__":
    main()
