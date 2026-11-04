"""Sources de données du hamster.

Chaque feed renvoie un dict "sample" à chaque appel de read(now, dt):
  work   : nouveaux work units depuis le dernier appel (int)
  rpm    : vitesse en milli-tours/minute (int)
  active : le hamster court (bool)
  block  : hauteur de Squeek block (int ou None)
  status : texte de diagnostic
"""
import json
import time
import urllib.error
import urllib.request


def _sample(work=0, rpm=0, active=False, block=None, status="", link="live", live_total=None, settled_total=None,
            distance_mm=None):
    """link : "live" (donnée fraîche), "lost" (signal perdu ou inconnu), "fault" (panne du compteur,
    ce n'est PAS le hamster qui dort), "unverified" (provenance non matérielle), "sim" (faux hamster)."""
    # live_total : travail cumulé mesuré par la roue ; settled_total : la part déjà réglée sur Ethereum (toujours ≤ live).
    # None = inconnu (jamais zéro).
    return {"work": work, "rpm": rpm, "active": active, "block": block, "status": status, "link": link,
            "live_total": live_total, "settled_total": settled_total,
            "distance_mm": distance_mm}  # distance courue aujourd'hui (selon l'appareil), None = inconnue


def _int(v):
    """Entier, ou None si la valeur est absente ou « unavailable » : inconnu n'est jamais zéro."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class LiveFeed:
    """Lit https://api.squeekchain.com/v1/status (lecture seule, sans clé)."""

    STALE = ("stale", "offline", "unavailable")

    def __init__(self, url, poll_seconds=2.0, max_work_per_s=16.7):
        self.url = url
        self.poll = poll_seconds
        # plafond de l'API : 10 000 unités par round de 600 s. Le travail en retard (coupure, rattrapage)
        # est libéré à ce rythme au plus, jamais d'un coup.
        self.max_per_poll = max(1, int(max_work_per_s * poll_seconds))
        self.backlog = 0
        self.etag = None
        self.epoch = None
        self.last_work = None
        self.next_poll = 0.0
        self.last = _sample(status="init")

    def export(self):
        return {"epoch": self.epoch, "last_work": self.last_work, "backlog": self.backlog}

    def restore(self, d):
        if d:
            self.epoch, self.last_work = d.get("epoch"), d.get("last_work")
            self.backlog = int(d.get("backlog") or 0)

    def read(self, now, dt):
        if now < self.next_poll:
            # entre deux appels: on garde la dernière vitesse, pas de nouveau work
            return {**self.last, "work": 0}
        self.next_poll = now + self.poll

        req = urllib.request.Request(
            self.url, headers={"accept": "application/json", "user-agent": "the-last-wheel/0.1"}
        )
        if self.etag:
            req.add_header("If-None-Match", self.etag)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                self.etag = r.headers.get("ETag")
                data = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return {**self.last, "work": 0, "status": "unchanged"}
            if e.code in (429, 503):
                try:
                    wait = int(e.headers.get("Retry-After") or 10)
                except ValueError:
                    wait = 10
                self.next_poll = now + wait
            self.last = _sample(status=f"http{e.code}", link="lost")
            return self.last
        except Exception as e:  # réseau coupé, timeout, JSON invalide
            self.last = _sample(status=f"error:{type(e).__name__}", link="lost")
            return self.last

        m = data.get("measurement") or {}
        anchor = (data.get("builder") or {}).get("anchor") or {}
        block = _int(anchor.get("blockHeight"))

        if m.get("coreStatus") == "COUNTER_FAULT":
            self.last = _sample(block=block, status="ignored:COUNTER_FAULT", link="fault")
            return self.last
        if not m:  # aucune mesure acceptée pour l'instant (avant la première lecture) : inconnu
            self.last = _sample(block=block, status="no-measurement", link="lost")
            return self.last
        # provenance : hardware, simulated, replay ou derived (docs). Seul "hardware" compte : le vrai hamster
        if m.get("provenance") != "hardware":
            self.last = _sample(block=block, status=f"ignored:{m.get('provenance')}", link="unverified")
            return self.last

        rpm_raw, total = _int(m.get("rpmMilli")), _int(m.get("cumulativeWorkUnits"))
        stale = m.get("freshness") in self.STALE or rpm_raw is None  # donnée périmée ou inconnue
        work, fresh = 0, 0
        if total is not None and not stale:
            epoch = m.get("counterEpoch")
            if self.last_work is None or epoch != self.epoch:
                self.epoch, self.last_work, self.backlog = epoch, total, 0  # nouveau départ, pas de rattrapage
            else:
                fresh = max(total - self.last_work, 0)  # passages d'aimant acceptés depuis la dernière lecture
                self.backlog += fresh
                self.last_work = total
        if not stale:
            work = min(self.backlog, self.max_per_poll)  # libération lissée du travail en retard
            self.backlog -= work

        # Le hamster court si le compteur est ACTIVE ou si de nouveaux passages viennent d'être acceptés.
        # La vitesse seule ne prouve rien : l'exemple de la doc montre IDLE avec rpmMilli = 77005 (dernière valeur).
        active = (m.get("coreStatus") == "ACTIVE" or fresh > 0) and not stale
        rpm = rpm_raw if active else 0
        self.last = _sample(work, rpm, active, block, f"{m.get('freshness')}/{m.get('coreStatus')}",
                            link="lost" if stale else "live",
                            live_total=None if stale else total, settled_total=_int(anchor.get("cumulativeWork")),
                            distance_mm=None if stale else _int(m.get("distanceMm")))
        return self.last


class SimFeed:
    """Faux hamster: alterne sommeil et sessions de course."""

    def __init__(self, cfg, rng):
        self.c = cfg["sim"]
        self.rng = rng
        self.running = False
        self.until = None
        self.target = 0
        self.frac = 0.0
        self.total = 0

    def export(self):
        return {"total": self.total}

    def restore(self, d):
        if d:
            self.total = d.get("total", 0)

    def read(self, now, dt):
        r, c = self.rng, self.c
        if self.until is None:
            self.until = now + r.uniform(*c["first_sleep_s"])
        if now >= self.until:
            self.running = not self.running
            if self.running:
                span = c["run_s"]
            else:  # hamster nocturne: siestes courtes la nuit, longues le jour
                # time.localtime() utilise le fuseau système. Sur le Pi, régler avec:
                #   sudo timedatectl set-timezone Europe/Paris
                h = time.localtime(now).tm_hour
                start, end = c["night_hours"]
                night = h >= start or h < end
                span = c["sleep_s_night"] if night else c["sleep_s_day"]
            self.until = now + r.uniform(*span)
            self.target = r.uniform(*c["rpm_milli"])
        rpm = int(max(0, self.target * (1 + r.gauss(0, 0.06)))) if self.running else 0
        self.frac += rpm / 1000 / 60 * dt * c["work_per_rev"]
        work = int(self.frac)
        self.frac -= work
        self.total += work
        return _sample(work, rpm, self.running, self.total // c["work_per_block"], "sim", link="sim")
