import os
import sys
from pathlib import Path

# src/webgui auf den Pfad, damit "from Utils..." wie im Programm funktioniert
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests sehen nie die Maschinen-Einstellungen dieses Geräts (maschine.json)
os.environ["X_SKI_MACHINE_FILE"] = "/nonexistent/maschine.json"


import pytest  # noqa: E402

LOCAL = {"REMOTE_ADDR": "127.0.0.1"}


@pytest.fixture(autouse=True)
def _access_file(tmp_path, monkeypatch):
    """Jeder Test hat seine eigene Anmeldung (Steuergerät), nicht die des laufenden x-ski."""
    monkeypatch.setenv("X_SKI_ACCESS_FILE", str(tmp_path / "access.json"))


def become_controller(client, pin="1234", environ=LOCAL):
    """Testgerät mit dem PIN zum Steuergerät machen (Standard-PIN 1234)."""
    r = client.post("/api/login", json={"pin": pin, "takeover": True}, environ_base=environ)
    assert r.get_json()["ok"], r.get_json()
    return client
