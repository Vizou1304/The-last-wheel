"""Cœur de la simulation: chaleur, réserves, givre, jour/nuit, météo, construction, arrivées.

Règle d'or: la seule source d'énergie est le hamster. Sans lui, la ville
consomme ses réserves puis hiberne. Elle ne meurt jamais.
"""
from chronicle import fmt_duration

DAY, NIGHT = "day", "night"

SYL1 = ["Ar", "Bel", "Cor", "Da", "El", "Fen", "Gri", "Hal", "Ivo", "Ka", "Lio", "Mor",
        "Nel", "Os", "Pim", "Rhu", "Sa", "Tov", "Ul", "Ves", "Wyn", "Yo", "Bram", "Clo"]
SYL2 = ["a", "en", "is", "o", "ric", "wen", "ka", "dor", "mi", "ne", "th", "la", "ros", "vin", "ette"]


class City:
    def __init__(self, cfg, buildings, chronicle, rng, state=None):
        self.cfg = cfg
        self.order = [b["id"] for b in buildings]
        self.B = {b["id"]: b for b in buildings}
        self.ch = chronicle
        self.rng = rng
        self.s = state or self._new_state()
        self.is_new = state is None
        self.s.setdefault("weather", None)  # sauvegardes d'avant la météo
        self.s["stats"].setdefault("heat_produced", 0.0)
        self.s["stats"].setdefault("heat_consumed", 0.0)
        # rattrapage silencieux pour les sauvegardes d'avant l'infra progressive
        if "infra_stage" not in self.s:
            stages = cfg.get("infra_stages", [])
            tw = self.s.get("total_work", 0)
            self.s["infra_stage"] = sum(1 for st in stages if tw >= st["wu"])

    # ------------------------------------------------------------- état ---
    def _new_state(self):
        c = self.cfg
        return {
            "version": 1,
            "t": None,
            "reserve": float(c["start_reserve"]),
            "frost": 0.0,
            "frost_stage": 0,
            "population": c["start_population"],
            "waiting": 0,
            "residents": [],
            "built": {b["id"]: 1 for b in self.B.values() if b.get("start")},
            "project": None,
            "phase": NIGHT,
            "phase_since": None,
            "last_active_t": None,
            "frozen": False,
            "last_dream_t": None,
            "sprint_since": None,
            "session_max_rpm": 0,
            "last_block": None,
            "nights": 0,
            "dreams": 0,
            "total_work": 0,
            "infra_stage": 0,
            "records": {"max_rpm": 0, "longest_sprint_s": 0, "longest_sleep_s": 0},
            "weather": None,
            "stats": {"elapsed_s": 0.0, "active_s": 0.0, "frozen_s": 0.0, "heat_produced": 0.0, "heat_consumed": 0.0},
        }

    def _say(self, key, **kw):
        self.ch.emit(self.s["t"], key, **kw)

    def _bid_say(self, event, bid, **kw):
        """Utilise event_<bid> si défini dans phrases.json, sinon la clé générique."""
        specific = f"{event}_{bid}"
        self._say(specific if specific in self.ch.phrases else event, **kw)

    def count(self, bid):
        return self.s["built"].get(bid, 0)

    def effect(self, key):
        return sum(self.B[b].get("effects", {}).get(key, 0) * n
                   for b, n in self.s["built"].items() if b in self.B)

    def capacity(self):
        return int(self.effect("housing"))

    def reserve_cap(self):
        return self.cfg["base_reserve_cap"] + self.effect("storage")

    def demand(self, active=True):
        c = self.cfg
        d = c["base_demand_per_s"] + self.s["population"] * c["demand_per_person_per_s"]
        d += sum(self.B[b].get("demand_per_s", 0) * n for b, n in self.s["built"].items() if b in self.B)
        d *= self.weather_cfg()["cold"]
        if not active:
            d *= c.get("sleep_demand_mult", 1.0)
        return d * (1 - min(0.6, self.effect("insulation")))

    # ------------------------------------------------------------- météo ---
    def weather_cfg(self):
        w = self.s.get("weather")
        states = self.cfg["weather"]["states"]
        return states[w["kind"]] if w and w["kind"] in states else states[self.cfg["weather"]["start"]]

    def _weather(self, now):
        s, W = self.s, self.cfg["weather"]
        w = s.get("weather")
        if w and now < w["until"]:
            return
        if not w:
            kind = W["start"]
        else:
            nxt = W["states"][w["kind"]]["next"]
            kind = self.rng.choices(list(nxt), weights=list(nxt.values()))[0]
        lo, hi = W["states"][kind]["hours"]
        prev = w["kind"] if w else None
        s["weather"] = {"kind": kind, "since": now, "until": now + self.rng.uniform(lo, hi) * 3600}
        if prev is None:
            return
        if prev == "blizzard":
            self._say("weather_blizzard_end")
        elif kind != prev:
            self._say(f"weather_{kind}")

    def temperature(self, rpm=0):
        c, s = self.cfg, self.s
        fill = 0 if s["frozen"] else min(1.0, s["reserve"] / c["comfort_reserve"])
        t = c["temp_cold"] + (c["temp_warm"] - c["temp_cold"]) * fill * (1 - 0.5 * s["frost"])
        t += self.weather_cfg()["temp"] * (0 if s["frozen"] else 1)
        return t + c["rpm_bonus_max"] * min(1.0, rpm / c["rpm_bonus_at_milli"])

    def _name(self):
        n = self.rng.choice(SYL1) + self.rng.choice(SYL2)
        return n if n not in self.s["residents"] else n + self.rng.choice(SYL2)

    # -------------------------------------------------------- construction ---
    def _available(self, b):
        r = b.get("requires", {})
        if b.get("start") or self.count(b["id"]) >= b.get("max", 1):
            return False
        if self.s["population"] < r.get("population", 0):
            return False
        return all(self.count(dep) for dep in r.get("built", []))

    def _pick_project(self):
        cands = [self.B[i] for i in self.order if self._available(self.B[i])]
        if not cands:
            return None
        if self.s["waiting"] > 0:
            housing = [b for b in cands if b.get("effects", {}).get("housing")]
            if housing:
                return min(housing, key=lambda b: b["cost"])
        if self.s["reserve"] >= 0.9 * self.reserve_cap():
            storage = [b for b in cands if b.get("effects", {}).get("storage")]
            if storage:
                return storage[0]
        return cands[0]

    def _build(self, work):
        s = self.s
        if s["project"] is None:
            b = self._pick_project()
            if b is None:
                return
            s["project"] = {"id": b["id"], "progress": 0.0}
            self._bid_say("build_start", b["id"], building=b["name"])
        speed = (1 + self.effect("build_speed")) * (1 - self.cfg["frost_build_penalty"] * s["frost"])
        s["project"]["progress"] += work * speed
        b = self.B[s["project"]["id"]]
        if s["project"]["progress"] >= b["cost"]:
            overflow = s["project"]["progress"] - b["cost"]
            s["built"][b["id"]] = self.count(b["id"]) + 1
            s["project"] = None
            self._bid_say("build_done", b["id"], building=b["name"])
            self._house_waiting()
            # démarrer le prochain chantier avec le surplus (en unités de progress)
            if overflow > 0:
                nxt = self._pick_project()
                if nxt:
                    s["project"] = {"id": nxt["id"], "progress": overflow}
                    self._bid_say("build_start", nxt["id"], building=nxt["name"])

    def _house_waiting(self):
        s = self.s
        room = self.capacity() - s["population"]
        moved = min(max(room, 0), s["waiting"])
        if moved > 0:
            s["population"] += moved
            s["waiting"] -= moved
            self._say("housed", count=moved)

    # ------------------------------------------------------------ événements ---
    def _arrivals(self, block):
        s, a = self.s, self.cfg["arrivals"]
        lo, hi = a["people"]
        eff = self.effect("arrivals")
        extra = int(eff) + (1 if self.rng.random() < (eff % 1) else 0)
        n = self.rng.randint(lo, hi) + extra
        room = max(self.capacity() - s["population"], 0) + max(a["camp_max"] - s["waiting"], 0)
        n = min(n, room)  # pas de place nulle part: personne ne s'aventure jusqu'ici
        if n <= 0:
            return
        names = [self._name() for _ in range(n)]
        s["residents"].extend(names)
        room = max(self.capacity() - s["population"], 0)
        joined = min(n, room)
        s["population"] += joined
        s["waiting"] += n - joined
        label = names[0] if n == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        self._say("arrivals", block=block, names=label)
        if n - joined > 0:
            self._say("camp", count=s["waiting"])

    def _wake(self, now):
        s = self.s
        slept = now - (s["last_active_t"] or s["phase_since"])
        s["phase"], s["phase_since"] = DAY, now
        s["session_max_rpm"] = 0
        if s["nights"] == 0:
            return  # premier réveil après le lancement: pas de phrase "after X of sleep"
        self._say("wake", slept=fmt_duration(slept))
        if s["frost"] >= 0.4:
            self._say("wake_frozen", pct=round(s["frost"] * 100))
        if slept > s["records"]["longest_sleep_s"] and slept >= self.cfg["record_min_sleep_s"]:
            if s["records"]["longest_sleep_s"]:
                self._say("record_sleep", slept=fmt_duration(slept))
            s["records"]["longest_sleep_s"] = slept

    def _nightfall(self, now):
        s, c = self.s, self.cfg
        ran = (s["last_active_t"] or now) - s["phase_since"]
        s["nights"] += 1
        self._say("nightfall", night=s["nights"], ran=fmt_duration(ran))
        top = s["session_max_rpm"]
        if top >= s["records"]["max_rpm"] * c["record_step"] and top >= c["record_min_rpm_milli"]:
            s["records"]["max_rpm"] = top
        s["phase"], s["phase_since"] = NIGHT, now
        s["last_dream_t"] = now

    # ------------------------------------------------------------------ tick ---
    TIME_KEYS = ("phase_since", "last_active_t", "last_dream_t", "sprint_since", "sprint_low_since")

    def pause(self, now, dt):
        """Hamster inconnu (signal perdu, panne du compteur) : le temps de la colonie s'arrête.
        Inconnu n'est pas zéro : pas de consommation, pas de givre, pas de nuit déclenchée par l'absence de donnée.
        Les repères de temps avancent d'autant pour que rien ne se déclenche d'un coup à la reprise."""
        s = self.s
        if s["t"] is None:
            return
        for k in self.TIME_KEYS:
            if s.get(k) is not None:
                s[k] += dt
        w = s.get("weather")
        if w:
            w["since"] += dt
            w["until"] += dt
        s["t"] = now

    def tick(self, now, dt, smp):
        s, c = self.s, self.cfg
        if s["t"] is None:
            s["phase_since"] = s["last_dream_t"] = now
            s["t"] = now
            self._say("start", count=s["population"])
        s["t"] = now
        st = s["stats"]
        st["elapsed_s"] += dt

        self._weather(now)
        work, rpm = smp["work"], smp["rpm"]
        active = smp["active"] or work > 0
        s["total_work"] += work

        # stades d'infrastructure (chronique une fois par seuil, jamais ré-émis au rechargement)
        stages = self.cfg.get("infra_stages", [])
        while s["infra_stage"] < len(stages) and s["total_work"] >= stages[s["infra_stage"]]["wu"]:
            self._say(f"infra_{stages[s['infra_stage']]['id']}")
            s["infra_stage"] += 1

        # jour / nuit
        if active:
            if s["phase"] == NIGHT:
                self._wake(now)
            s["last_active_t"] = now
            st["active_s"] += dt
            s["session_max_rpm"] = max(s["session_max_rpm"], rpm)
        elif s["phase"] == DAY and now - (s["last_active_t"] or now) >= c["night_after_idle_s"]:
            self._nightfall(now)

        # chaleur
        produced = work * c["heat_per_work"]
        consumed = self.demand(active) * dt
        s["reserve"] = min(self.reserve_cap(), s["reserve"] + produced)
        s["reserve"] -= consumed
        st["heat_produced"] += produced
        st["heat_consumed"] += consumed
        if s["reserve"] <= 0:
            s["reserve"] = 0.0
            if not s["frozen"]:
                s["frozen"] = True
                self._say("freeze")
        elif s["frozen"] and s["reserve"] >= c["unfreeze_reserve"]:
            s["frozen"] = False
            self._say("unfreeze")

        # givre
        if s["frozen"]:
            st["frozen_s"] += dt
            s["frost"] = min(1.0, s["frost"] + c["frost_rate_per_h"] * dt / 3600)
            stage = int(s["frost"] * 4)  # paliers 25 / 50 / 75 / 100 %
            if stage > s["frost_stage"]:
                s["frost_stage"] = stage
                self._say("frost", pct=stage * 25)
        elif work:
            s["frost"] = max(0.0, s["frost"] - work * c["thaw_per_work"] * (1 + self.effect("thaw")))
            s["frost_stage"] = min(s["frost_stage"], int(s["frost"] * 4))

        # construction (seulement quand la ville a chaud et que le hamster court)
        if work and not s["frozen"]:
            self._build(work)

        # sprints (avec un délai de grâce pour ignorer les micro-ralentissements)
        if rpm >= c["sprint_rpm_milli"]:
            if s["sprint_since"] is None:
                s["sprint_since"] = now
            s["sprint_low_since"] = None
        elif s["sprint_since"] is not None:
            if s.get("sprint_low_since") is None:
                s["sprint_low_since"] = now
            if now - s["sprint_low_since"] >= c["sprint_grace_s"]:
                d = s["sprint_low_since"] - s["sprint_since"]
                s["sprint_since"] = s["sprint_low_since"] = None
                if d >= c["sprint_min_s"]:
                    record = d > s["records"]["longest_sprint_s"]
                    if now - s.get("last_sprint_say", 0) >= c["sprint_say_every_s"]:
                        self._say("sprint", minutes=fmt_duration(d))
                    s["last_sprint_say"] = now
                    if record:
                        s["records"]["longest_sprint_s"] = d

        # rêves (la nuit)
        if s["phase"] == NIGHT and s["nights"] > 0:
            every = c["dream_every_s"] / (1 + self.effect("dream"))
            if now - s["last_dream_t"] >= every:
                s["last_dream_t"] = now
                s["dreams"] += 1
                self._say("dream")

        # Squeek blocks -> arrivées (une tous les N blocks, les blocks sont très fréquents)
        b = smp.get("block")
        if b is not None:
            if s["last_block"] is None or b < s["last_block"]:
                s["last_block"] = b  # premier contact ou remise à zéro (testnet -> mainnet)
            elif b - s["last_block"] >= c["arrivals"]["every_blocks"]:
                s["last_block"] = b
                self._arrivals(b)

    # ---------------------------------------------------------------- vue ---
    def snapshot(self, rpm=0):
        s = self.s
        p = s["project"]
        return {
            "phase": s["phase"],
            "frozen": s["frozen"],
            "temperature": round(self.temperature(rpm), 1),
            "reserve": round(s["reserve"]),
            "reserve_cap": round(self.reserve_cap()),
            "frost": round(s["frost"], 3),
            "population": s["population"],
            "waiting": s["waiting"],
            "capacity": self.capacity(),
            "built": dict(s["built"]),
            "project": None if not p else {
                "id": p["id"], "name": self.B[p["id"]]["name"],
                "pct": round(100 * p["progress"] / self.B[p["id"]]["cost"]),
            },
            "weather": (s.get("weather") or {}).get("kind", self.cfg["weather"]["start"]),
            "nights": s["nights"],
            "dreams": s["dreams"],
            "records": dict(s["records"]),
            # sprint_since n'est effacé qu'après sprint_grace_s de bas régime: le délai de grâce est déjà inclus
            "sprinting": s["sprint_since"] is not None,
            "total_work": s["total_work"],
            "infra_cfg": self.cfg.get("infra_stages", []),
            "inhabitants_cfg": self.cfg.get("inhabitants", {}),
        }
