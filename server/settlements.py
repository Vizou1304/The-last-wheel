"""Derniers lots de travail écrits sur Ethereum, lus sur /v1/settlements (lecture seule, sans clé).

Chaque lot vérifié est écrit par une transaction Ethereum (son « hash »). La page affiche un lien vers l'explorateur
pour que n'importe qui puisse vérifier que le travail du hamster est bien sur la chaîne.

Règles :
  - aucun montant de SQK n'est lu ni publié (le jeu n'affiche jamais d'argent) ;
  - un identifiant de transaction n'est gardé que s'il a la forme 0x + 64 caractères hexadécimaux ;
  - réponse absente ou « unavailable » = inconnu, jamais zéro ;
  - un appel toutes les `ttl` secondes (la page ne contacte jamais l'API directement).
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request

TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse(data, limit=8):
    """Extrait de la réponse ce que la page affiche, ou None si la donnée est inconnue."""
    if not isinstance(data, dict) or data.get("status") not in (None, "available"):
        return None
    rows = []
    for r in data.get("recentSettlements") or []:
        if not isinstance(r, dict):
            continue
        tx = r.get("transactionHash")
        if not isinstance(tx, str) or not TX_RE.match(tx):
            continue
        rows.append({
            "tx": tx,
            "work": _int(r.get("workAdded")),          # unités de travail ajoutées par ce lot
            "block": _int(r.get("blockHeight")),        # hauteur de bloc Squeek (pas un bloc Ethereum)
            "eth_block": _int(r.get("ethereumBlockNumber")),
            "confirmation": str(r.get("confirmationStatus") or "")[:12],
        })
    rows.sort(key=lambda x: x["eth_block"] or 0, reverse=True)
    chain = data.get("chain") if isinstance(data.get("chain"), dict) else {}
    return {"network": str(chain.get("target") or "sepolia")[:20], "items": rows[:limit]}


class SettlementsFeed:
    """Interroge /v1/settlements dans un fil d'arrière-plan et garde la dernière réponse valide."""

    def __init__(self, url, ttl=60.0, stale_after=600.0):
        self.url, self.ttl, self.stale_after = url, ttl, stale_after
        self.lock = threading.Lock()
        self.data = None          # dernier résultat de parse()
        self.ok_at = 0.0
        self.etag = None
        self.running = False

    def start(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._loop, daemon=True).start()

    def snapshot(self):
        """{"status": "ok" | "unknown", "network": ..., "items": [...]} — "unknown" si pas de donnée récente."""
        with self.lock:
            fresh = self.data is not None and time.time() - self.ok_at < self.stale_after
            return {"status": "ok" if fresh else "unknown",
                    "network": (self.data or {}).get("network", "sepolia"),
                    "items": (self.data or {}).get("items", []) if fresh else []}

    def fetch_once(self):
        """Un appel. Renvoie le nombre de secondes à attendre avant le suivant."""
        req = urllib.request.Request(self.url, headers={"accept": "application/json", "user-agent": "the-last-wheel/0.1"})
        if self.etag:
            req.add_header("If-None-Match", self.etag)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                etag = r.headers.get("ETag")
                parsed = parse(json.load(r))
        except urllib.error.HTTPError as e:
            if e.code == 304:
                with self.lock:
                    self.ok_at = time.time()
                return self.ttl
            if e.code in (429, 503):
                try:
                    return max(self.ttl, int(e.headers.get("Retry-After") or 0))
                except ValueError:
                    return self.ttl
            return self.ttl
        except Exception:  # réseau coupé, timeout, JSON invalide : on garde la dernière donnée, qui vieillit
            return self.ttl
        if parsed is not None:
            with self.lock:
                self.data, self.ok_at, self.etag = parsed, time.time(), etag
        return self.ttl

    def _loop(self):
        while self.running:
            time.sleep(self.fetch_once())
