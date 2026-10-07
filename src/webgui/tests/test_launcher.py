import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import launcher


def test_argv_per_mode():
    a = launcher.build_xski_argv("skier", "sertig.gpx", config_path=None, host="0.0.0.0", no_browser=False)
    assert a[0] == sys.executable and a[2].endswith("x-ski.py")
    assert a[3:] == ["--mode", "skier", "--host", "0.0.0.0", "--route", "sertig.gpx", "--no-open"]

    b = launcher.build_xski_argv("profile", None, config_path="/x/c.json", host="127.0.0.1", no_browser=True)
    assert b[3:] == ["--mode", "profile", "--host", "127.0.0.1", "--config", "/x/c.json", "--no-browser"]

    c = launcher.build_xski_argv("interval", "ignored.gpx", config_path=None, host="0.0.0.0", no_browser=False)
    assert "--route" not in c and c[3:5] == ["--mode", "interval"]


def test_argv_rejects_bad_input():
    with pytest.raises(ValueError):
        launcher.build_xski_argv("skier", None, config_path=None, host="0.0.0.0", no_browser=False)
    with pytest.raises(ValueError):
        launcher.build_xski_argv("rennen", None, config_path=None, host="0.0.0.0", no_browser=False)


@pytest.fixture
def client(monkeypatch, tmp_path):
    started = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.fn = fn

        def start(self):
            started.append(self.fn)  # nicht ausführen: kein exec im Test

    monkeypatch.setattr(launcher.threading, "Timer", FakeTimer)
    routes = tmp_path / "routes"
    routes.mkdir()
    (routes / "a.gpx").write_text(
        '<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="46.70" lon="9.80"><ele>1500</ele></trkpt>'
        '<trkpt lat="46.71" lon="9.80"><ele>1550</ele></trkpt>'
        '</trkseg></trk></gpx>')
    monkeypatch.setattr(launcher, "ROUTES_DIR", routes)
    app = launcher.create_app(SimpleNamespace(config_path=None, host="0.0.0.0", no_browser=True))
    return app.test_client(), started


def test_api_lists_routes(client):
    c, _ = client
    data = c.get("/api/launcher").get_json()
    assert data["launcher"] is True
    assert [r["file"] for r in data["routes"]] == ["a.gpx"]
    assert data["routes"][0]["length_km"] == pytest.approx(1.1, abs=0.1)


def test_start_requires_valid_route_for_skier(client):
    c, started = client
    assert c.post("/start", json={"mode": "skier"}).status_code == 400
    assert c.post("/start", json={"mode": "skier", "route": "../../etc/passwd"}).status_code == 400
    assert c.post("/start", json={"mode": "nix"}).status_code == 400
    assert started == []


def test_start_profile_and_skier(client):
    c, started = client
    r = c.post("/start", json={"mode": "skier", "route": "a.gpx"}).get_json()
    assert r == {"ok": True, "next": "/strecke"}
    assert len(started) == 1
    # Ein zweiter Klick startet nicht doppelt
    c.post("/start", json={"mode": "profile"})
    assert len(started) == 1


def test_argv_with_section():
    a = launcher.build_xski_argv("skier", "a.gpx", config_path=None, host="0.0.0.0", no_browser=False,
                                 start_km=13.0, end_km=18.25)
    assert a[a.index("--route-start-km") + 1] == "13.000"
    assert a[a.index("--route-end-km") + 1] == "18.250"


def test_start_validates_section(client):
    c, started = client
    assert c.post("/start", json={"mode": "skier", "route": "a.gpx", "start_km": 0.5, "end_km": 0.6}).status_code == 400
    r = c.post("/start", json={"mode": "skier", "route": "a.gpx", "start_km": 0.2, "end_km": 0.9})
    assert r.get_json()["ok"] is True and len(started) == 1


def test_launcher_route_payload(client):
    c, _ = client
    data = c.get("/api/launcher/route?file=a.gpx").get_json()
    assert data["file"] == "a.gpx" and len(data["coordinates"]) >= 2
    assert c.get("/api/launcher/route?file=../x.gpx").status_code == 404


def test_route_list_always_current(client, monkeypatch):
    c, _ = client
    routes = launcher.ROUTES_DIR
    assert [r["file"] for r in c.get("/api/launcher").get_json()["routes"]] == ["a.gpx"]
    (routes / "B neue Strecke.GPX").write_text((routes / "a.gpx").read_text())   # neu abgelegt, Endung gross
    (routes / "notiz.txt").write_text("keine Strecke")
    files = [r["file"] for r in c.get("/api/launcher").get_json()["routes"]]
    assert files == ["B neue Strecke.GPX", "a.gpx"]
    (routes / "a.gpx").unlink()                                                      # entfernt
    assert [r["file"] for r in c.get("/api/launcher").get_json()["routes"]] == ["B neue Strecke.GPX"]


def test_start_calibration(client):
    c, started = client
    assert c.post("/start", json={"mode": "calib"}).get_json() == {"ok": True, "next": "/kalibrierung"}
    assert len(started) == 1
    a = launcher.build_xski_argv("calib", None, config_path=None, host="0.0.0.0", no_browser=False)
    assert a[3:5] == ["--mode", "calib"] and "--route" not in a


def test_browser_heartbeat_and_quit(client, monkeypatch):
    c, _ = client
    alive = c.application.config["XSKI_ALIVE"]
    alive["until"] = 0.0
    assert c.get("/api/alive").get_json() == {"ok": True}
    assert alive["until"] > launcher.time.monotonic() + launcher.BROWSER_TIMEOUT_S - 5
    # Header der Startseite hat die Kachel «Beenden», das Profil nicht
    assert "quit-tile" in c.get("/header").get_data(as_text=True)
    assert "quit-tile" not in c.get("/header?active=profil").get_data(as_text=True)
    exits = []
    monkeypatch.setattr(launcher.os, "_exit", lambda code: exits.append(code))
    r = c.post("/api/quit", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ok"] is True
    assert c.post("/api/quit", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 403
