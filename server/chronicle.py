"""Journal de la ville: phrases tirées de content/phrases.json."""
import collections
import json
import time


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fmt_duration(seconds):
    m = int(seconds // 60)
    if m < 60:
        return f"{max(m, 1)} min"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}"


class Chronicle:
    def __init__(self, phrases, path, rng, echo=True, keep=200):
        self.phrases = phrases
        self.path = path
        self.rng = rng
        self.echo = echo
        self.recent = collections.deque(maxlen=keep)
        self.counts = collections.Counter()

    def load_recent(self):
        """Recharge les dernières lignes du journal (pour la page web après un redémarrage)."""
        try:
            with open(self.path, encoding="utf-8") as f:
                # deque(f, maxlen=keep) ne charge que les keep dernières lignes en mémoire
                for line in collections.deque(f, maxlen=self.recent.maxlen):
                    try:
                        self.recent.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            pass

    def emit(self, t, key, **kw):
        templates = self.phrases.get(key)
        if not templates:
            return
        text = self.rng.choice(templates).format_map(_Safe(kw))
        text = text[0].upper() + text[1:]
        entry = {"t": round(t), "key": key, "text": text}
        self.recent.append(entry)
        self.counts[key] += 1
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if self.echo:
            stamp = time.strftime("%a %H:%M", time.localtime(t))
            print(f"{stamp} — {text}", flush=True)
