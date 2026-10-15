import json
import shutil
from pathlib import Path

import pytest
from flask import Flask

from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.access import install_access_control
from Utils.profile_page import create_profile_blueprint, profile_label
from conftest import become_controller

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
    install_access_control(app)
    app.register_blueprint(create_profile_blueprint(cm, on_saved=lambda: saved.append(1)))
    return become_controller(app.test_client()), tmp_path, saved


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


def test_machine_fields_are_not_in_the_profile(env):
    client, _, _ = env
    sections = {f["section"] for f in client.get("/api/profile").get_json()["fields"]}
    assert "drive" not in sections and "hardware" not in sections


def make_machine_app(env, monkeypatch, locked=None):
    from Utils.machine_page import create_machine_blueprint
    client, tmp, _ = env
    monkeypatch.setenv("X_SKI_MACHINE_FILE", str(tmp / "maschine.json"))
    cm = ConfigManager(script_dir=tmp, active_filename="x-ski.json", config_dirname="configs",
                       default_config=DEFAULT_CONFIG, env_var="X_SKI_CONFIG_TEST")
    app = Flask(__name__, template_folder=str(WEBGUI / "templates"))
    install_access_control(app)
    app.register_blueprint(create_machine_blueprint(cm, locked_reason=locked))
    return become_controller(app.test_client()), tmp


def test_machine_page_needs_password(env, monkeypatch):
    client, tmp = make_machine_app(env, monkeypatch)
    local = {"REMOTE_ADDR": "127.0.0.1"}
    data = client.get("/api/maschine").get_json()
    assert data["values"]["drive.type"] == "m751" and not data["password_set"]
    assert [o["value"] for o in next(f for f in data["fields"] if f["key"] == "type")["options"]] == ["m751", "delta_b3"]

    # ohne Passwort: erst festlegen
    r = client.post("/api/maschine", json={"values": {"drive.type": "delta_b3"}}, environ_base=local)
    assert r.status_code == 400 and not (tmp / "maschine.json").exists()
    r = client.post("/api/maschine", json={"values": {"drive.type": "delta_b3", "drive.axes": "2"}, "password": "geheim"},
                    environ_base=local)
    assert r.get_json()["ok"]
    stored = json.loads((tmp / "maschine.json").read_text())
    assert stored["drive"] == {"type": "delta_b3", "axes": 2}
    assert "geheim" not in json.dumps(stored) and stored["password_hash"]       # nur als Hash
    assert "type" not in json.loads((tmp / "x-ski.json").read_text())["drive"]   # Profil bleibt unberührt

    # falsches Passwort
    r = client.post("/api/maschine", json={"values": {"drive.axes": "1"}, "password": "falsch"}, environ_base=local)
    assert r.status_code == 403
    assert client.get("/api/maschine").get_json()["values"]["drive.axes"] == 2
    # richtiges Passwort, Trommel ändern, Passwort wechseln
    r = client.post("/api/maschine", json={"values": {"hardware.pulli_diameter": "60"}, "password": "geheim",
                                           "new_password": "neu123"}, environ_base=local)
    assert r.get_json()["ok"]
    assert client.get("/api/maschine").get_json()["values"]["hardware.pulli_diameter"] == 60
    assert client.post("/api/maschine", json={"values": {}, "password": "geheim"}, environ_base=local).status_code == 403
    # nur am Gerät
    r = client.application.test_client().post("/api/maschine", json={"values": {}, "password": "neu123"},
                                               environ_base={"REMOTE_ADDR": "10.0.0.5"})
    assert r.status_code == 403
    r = client.post("/api/maschine", json={"values": {"drive.type": "siemens"}, "password": "neu123"}, environ_base=local)
    assert r.status_code == 400


def test_machine_page_locked_during_training(env, monkeypatch):
    client, _ = make_machine_app(env, monkeypatch, locked=lambda: "Training läuft")
    assert client.get("/api/maschine").get_json()["locked"] == "Training läuft"
    r = client.post("/api/maschine", json={"values": {}, "password": "x"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.status_code == 409


def test_profile_locked_and_heart_rate_api(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "x-ski.json").write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
    cm = ConfigManager(script_dir=tmp_path, active_filename="x-ski.json", config_dirname="configs",
                       default_config=DEFAULT_CONFIG, env_var="X_SKI_CONFIG_TEST")

    class FakeHr:
        enabled = True
        searched = 0
        def status(self): return {"enabled": True, "connected": True, "heart_rate": 132, "searching": False}
        def research(self): FakeHr.searched += 1

    lock = {"reason": "Das Training läuft – das Profil lässt sich nur in der Pause ändern."}
    app = Flask(__name__, template_folder=str(WEBGUI / "templates"))
    install_access_control(app)
    app.register_blueprint(create_profile_blueprint(cm, hr_manager=lambda: FakeHr(), edit_lock=lambda: lock["reason"]))
    c = become_controller(app.test_client())
    assert c.get("/api/profile").get_json()["locked"].startswith("Das Training läuft")
    assert c.post("/api/profile", json={"values": {"user.ftp_w": "160"}}).status_code == 409
    lock["reason"] = None
    assert c.post("/api/profile", json={"values": {"user.ftp_w": "160"}}).status_code == 200
    assert c.get("/api/hr").get_json() == {"available": True, "enabled": True, "connected": True,
                                           "heart_rate": 132, "searching": False}
    assert c.post("/api/hr/search").get_json()["ok"] and FakeHr.searched == 1
