import json
import shutil
from pathlib import Path

import pytest
from flask import Flask

from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.profile_page import create_profile_blueprint, profile_label

WEBGUI = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(tmp_path):
    (tmp_path / "configs").mkdir()
    active = json.loads(json.dumps(DEFAULT_CONFIG))
    active["user"].update(firstname="Jürg", lastname="Test", mu=0.037)
    text = json.dumps(active, indent=2, ensure_ascii=False) + "\n"
    (tmp_path / "x-ski.json").write_text(text, encoding="utf-8")
    (tmp_path / "configs" / "x-ski.aktuell.json").write_text(text, encoding="utf-8")
    other = json.loads(text); other["user"]["firstname"] = "Anna"
    (tmp_path / "configs" / "x-ski.anna.json").write_text(json.dumps(other), encoding="utf-8")
    cm = ConfigManager(script_dir=tmp_path, active_filename="x-ski.json", config_dirname="configs",
                       default_config=DEFAULT_CONFIG, env_var="X_SKI_CONFIG_TEST")
    saved = []
    app = Flask(__name__, template_folder=str(WEBGUI / "templates"))
    app.register_blueprint(create_profile_blueprint(cm, on_saved=lambda: saved.append(1)))
    return app.test_client(), tmp_path, saved


def test_label():
    assert profile_label("x-ski.aktuell.json", "Jürg Pargätzi") == "Jürg Pargätzi (aktuell)"
    assert profile_label("x-ski.default.json", "") == "default"


def test_get_and_save_profile_mirrors_active_file(env):
    c, root, saved = env
    data = c.get("/api/profile").get_json()
    assert data["values"]["user.firstname"] == "Jürg" and data["values"]["user.mu"] == 0.037
    r = c.post("/api/profile", json={"values": {"user.diagonal_from_slope_percent": "3.5",
                                                "user.diagonal_hysteresis_percent": "1", "user.max_hr_bpm": "176"}})
    assert r.status_code == 200 and r.get_json()["mirrored"] == "x-ski.aktuell.json"
    for f in ("x-ski.json", "configs/x-ski.aktuell.json"):
        u = json.loads((root / f).read_text())["user"]
        assert u["diagonal_from_slope_percent"] == 3.5 and u["max_hr_bpm"] == 176 and u["firstname"] == "Jürg"
    assert saved == [1]


def test_save_rejects_invalid_values(env):
    c, root, saved = env
    before = (root / "x-ski.json").read_text()
    assert c.post("/api/profile", json={"values": {"user.weight_kg": "abc"}}).status_code == 400
    assert c.post("/api/profile", json={"values": {"user.max_hr_bpm": "999"}}).status_code == 400
    # Hysterese grösser als Schwelle -> Gesamtprüfung schlägt fehl
    assert c.post("/api/profile", json={"values": {"user.diagonal_from_slope_percent": "2",
                                                   "user.diagonal_hysteresis_percent": "3"}}).status_code == 400
    assert (root / "x-ski.json").read_text() == before and saved == []


def test_list_activate_and_new_profile(env):
    c, root, saved = env
    data = c.get("/api/profiles").get_json()
    assert data["active"] == "x-ski.aktuell.json"
    assert {p["file"]: p["person"] for p in data["profiles"]} == {"x-ski.aktuell.json": "Jürg Test", "x-ski.anna.json": "Anna Test"}

    assert c.post("/api/profiles/activate", json={"file": "x-ski.anna.json"}).status_code == 200
    assert json.loads((root / "x-ski.json").read_text())["user"]["firstname"] == "Anna"
    assert c.get("/api/profiles").get_json()["active"] == "x-ski.anna.json"
    assert c.post("/api/profiles/activate", json={"file": "../x-ski.json"}).status_code == 400

    # Vorlage mit Maschinenwerten und fremden Personendaten
    tpl = json.loads((root / "configs" / "x-ski.aktuell.json").read_text())
    tpl["simulation"]["motor_rated_torque_nm"] = 2.88
    tpl["user"].update(firstname="Vorlage", email="vorlage@example.com")
    (root / "configs" / "x-ski.default.json").write_text(json.dumps(tpl))

    r = c.post("/api/profiles/new", json={"name": "Skating Ski"})
    assert r.status_code == 200 and r.get_json()["active"] == "x-ski.skating-ski.json" and r.get_json()["edit"]
    new = json.loads((root / "configs" / "x-ski.skating-ski.json").read_text())
    assert new["simulation"]["motor_rated_torque_nm"] == 2.88          # Maschinenwerte aus der Vorlage
    assert new["user"]["firstname"] == "Skating Ski" and new["user"]["email"] == ""   # Personendaten leer
    assert new["user"]["mu"] == 0.037
    assert new["strava"] == {"auto_upload": False}   # neues Profil: kein fremdes Strava-Konto
    assert c.post("/api/profiles/new", json={"name": "Skating Ski"}).status_code == 400
    assert c.post("/api/profiles/new", json={"name": "  "}).status_code == 400
    assert len(saved) == 2


def test_drive_selection_is_saved_for_the_machine_not_the_profile(env, monkeypatch):
    client, tmp, _ = env
    monkeypatch.setenv("X_SKI_MACHINE_FILE", str(tmp / "maschine.json"))
    data = client.get("/api/profile").get_json()
    assert data["values"]["drive.type"] == "m751" and data["values"]["drive.axes"] == 1
    field = next(f for f in data["fields"] if f["key"] == "type" and f["section"] == "drive")
    assert [o["value"] for o in field["options"]] == ["m751", "delta_b3"]

    r = client.post("/api/profile", json={"values": {"drive.type": "delta_b3", "drive.axes": "2"}},
                    environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ok"]
    assert json.loads((tmp / "maschine.json").read_text())["drive"] == {"type": "delta_b3", "axes": 2}
    assert "type" not in json.loads((tmp / "x-ski.json").read_text())["drive"]      # Profil bleibt unberührt
    assert client.get("/api/profile").get_json()["values"]["drive.axes"] == 2

    r = client.post("/api/profile", json={"values": {"drive.type": "siemens"}}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 400
