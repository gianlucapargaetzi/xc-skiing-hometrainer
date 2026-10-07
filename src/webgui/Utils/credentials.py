# Utils/credentials.py
"""
Zugangsdaten (SMTP, Strava) werden NICHT im Code abgelegt.

Reihenfolge:
1) Umgebungsvariable
2) .env-Datei im Projektverzeichnis (wird nicht versioniert, siehe .env.example)
"""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_DIR / ".env"


def _load_env_file(path: Path = ENV_FILE) -> dict:
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_credential(name: str, default: str = None) -> str:
    value = os.environ.get(name)
    if value:
        return value
    return _load_env_file().get(name, default)
