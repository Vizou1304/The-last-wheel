"""Sauvegarde atomique de la ville avec copies de secours."""
import json
import os

BACKUPS = 3


def load(path):
    for p in [path] + [f"{path}.{i}" for i in range(1, BACKUPS + 1)]:
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def save(path, data):
    for i in range(BACKUPS, 1, -1):
        if os.path.exists(f"{path}.{i - 1}"):
            os.replace(f"{path}.{i - 1}", f"{path}.{i}")
    if os.path.exists(path):
        os.replace(path, f"{path}.1")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
