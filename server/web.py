"""Petit serveur HTTP (bibliothèque standard) qui tourne à côté de la simulation.

  GET /                      la page web (web/index.html)
  GET /assets/...            la ville 3D (city.glb) et ses images fixes, exportées par Blender
  GET /vendor/...            Three.js (moteur 3D), embarqué pour ne dépendre d'aucun service externe
  GET /api/state             état de la ville + du hamster (JSON)
  GET /api/chronicle?since=T lignes de chronique plus récentes que T (timestamp)
"""
import json
import mimetypes
import os
import re
import socket
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("model/gltf-binary", ".glb")


class Shared:
    """État publié par la boucle de simulation, lu par le serveur."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = b"{}"
        self.chronicle = []

    def publish(self, state, chronicle):
        body = json.dumps(state, ensure_ascii=False).encode("utf-8")
        with self.lock:
            self.state = body
            self.chronicle = list(chronicle)

    def read(self):
        with self.lock:
            return self.state, self.chronicle


class DualStackServer(ThreadingHTTPServer):
    """Écoute en IPv6 ET en IPv4 : Windows et les téléphones résolvent souvent les noms en .local en IPv6 d'abord."""
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # 0 = accepte aussi l'IPv4
        except (AttributeError, OSError):
            pass
        super().server_bind()


def make_server(host, port, handler):
    """« 0.0.0.0 » (tout le réseau) devient « :: » en double pile ; si l'IPv6 n'existe pas, retour à l'IPv4 seul."""
    if host in ("0.0.0.0", ""):
        try:
            return DualStackServer(("::", port), handler)
        except OSError:
            pass
    return ThreadingHTTPServer((host, port), handler)


def serve(shared, web_dir, host, port):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=web_dir, **kw)

        def log_message(self, *args):
            pass

        def list_directory(self, path):  # pas de listing de dossiers
            self.send_error(404)
            return None

        def _json(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            # cache partagé très court (2 s) : un tunnel / CDN peut servir des milliers de visiteurs avec ~1 appel
            # toutes les 2 s sur le Pi. Les navigateurs ne le gardent pas (la page demande no-store).
            self.send_header("Cache-Control", "public, max-age=1, s-maxage=2")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _page(self):
            """index.html avec l'adresse complète du site dans les balises d'aperçu (X, Discord… exigent https://...).
            Elle vient de l'en-tête de la requête, donc ça marche avec n'importe quel domaine ou tunnel."""
            with open(os.path.join(web_dir, "index.html"), encoding="utf-8") as f:
                html = f.read()
            host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost").split(",")[0].strip()
            proto = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip()
            if not re.fullmatch(r"[A-Za-z0-9.\-]+(:[0-9]{1,5})?", host) or proto not in ("http", "https"):
                host, proto = "localhost", "http"  # en-tête douteux : on n'écrit rien d'inattendu dans la page
            body = html.replace("__BASE__", f"{proto}://{host}").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=60")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self._page()
            if url.path == "/api/state":
                state, _ = shared.read()
                return self._json(state)
            if url.path == "/api/chronicle":
                q = urllib.parse.parse_qs(url.query)
                try:
                    since = float(q.get("since", ["0"])[0])
                except ValueError:
                    since = 0.0
                _, chron = shared.read()
                rows = [e for e in chron if e["t"] > since][-60:]
                return self._json(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
            return super().do_GET()

        def end_headers(self):
            if self.path.startswith("/vendor/"):
                self.send_header("Cache-Control", "public, max-age=86400")
            elif self.path.startswith("/assets/"):
                self.send_header("Cache-Control", "public, max-age=300")
            elif self.path.split("?")[0].endswith((".js", ".css")):
                # le code du jeu (city3d.js, hud.js…): 1 min, pour qu'une mise à jour arrive vite
                # chez les visiteurs et dans le cache de Cloudflare (sans en-tête il garde 2 h)
                self.send_header("Cache-Control", "public, max-age=60")
            super().end_headers()

    srv = make_server(host, port, Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
