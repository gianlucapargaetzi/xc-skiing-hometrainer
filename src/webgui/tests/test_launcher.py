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


def test_shutdown_only_on_device(client, monkeypatch):
    c, _ = client
    calls = []
    monkeypatch.setattr(launcher, "power_off", lambda: calls.append("off"))
    monkeypatch.setattr(launcher.os, "_exit", lambda code: calls.append(("exit", code)))
    monkeypatch.setattr(launcher.threading, "Timer", lambda delay, fn: type("T", (), {"start": lambda self: fn()})())
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    assert "Ausschalten" in c.get("/header?active=start").get_data(as_text=True)
    assert c.post("/api/shutdown", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 403
    assert calls == []
    assert c.post("/api/shutdown", environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_json()["ok"] is True
    assert calls == ["off", ("exit", 0)]


def test_comparison_without_training(client, monkeypatch, tmp_path):
    c, _ = client
    monkeypatch.setattr(launcher, "TRAININGS_DIR", tmp_path)
    assert c.get("/api/vergleich").status_code == 404
    assert c.get("/api/launcher").get_json()["has_comparison"] is False
    assert c.get("/vergleich").status_code == 200


def _make_fit(path, seconds=400, gps=False):
    from Utils.fit_export import FitRecorder, FitSample
    rec = FitRecorder()
    for i in range(seconds):
        rec.add(FitSample(t=1_791_300_000.0 + i, distance_m=i * 3.0, speed_m_s=3.0, heart_rate=140, cadence=50, power=40,
                          lat=46.70 + i * 2.2e-5 if gps else None, lon=9.80 if gps else None,
                          altitude_m=1500 + i * 0.1 if gps else None, grade_percent=None), lap_key=None, lap_trigger=0)
    rec.write(str(path))


def test_training_list_analysis_and_upload(client, monkeypatch, tmp_path):
    import io
    c, _ = client
    trainings = tmp_path / "trainings"
    trainings.mkdir()
    monkeypatch.setattr(launcher, "TRAININGS_DIR", trainings)
    assert c.get("/api/trainings").get_json() == {"files": []}
    _make_fit(trainings / "skiErg_a.fit")
    files = c.get("/api/trainings").get_json()["files"]
    assert [f["file"] for f in files] == ["skiErg_a.fit"]
    assert files[0]["duration_s"] == 399 and files[0]["has_gps"] is False and files[0]["power_avg"] == 40

    # ohne GPS: Auswertung nur mit dem Training, mit Kennzahlen und Zonen
    d = c.get("/api/vergleich?fit=skiErg_a.fit").get_json()
    assert d["ok"] and d["has_original"] is False and d["route_name"] == ""
    assert d["summary"]["power_avg"] == 40 and "hr" in d["summary"]["zones"]
    # kein Zugriff auf Dateien ausserhalb des Trainingsordners
    assert c.get("/api/vergleich?fit=../x-ski.json").status_code == 404
    assert c.get("/api/vergleich?fit=fehlt.fit").status_code == 404

    # Laden von aussen: nur FIT, nur lokal, kaputte Dateien werden abgelehnt
    local = {"REMOTE_ADDR": "127.0.0.1"}
    good = io.BytesIO((trainings / "skiErg_a.fit").read_bytes())
    r = c.post("/api/trainings/upload", data={"file": (good, "mein lauf.fit")}, environ_base=local)
    assert r.get_json() == {"ok": True, "file": "mein_lauf.fit"} and (trainings / "mein_lauf.fit").exists()
    r = c.post("/api/trainings/upload", data={"file": (io.BytesIO(b"kein fit"), "x.fit")}, environ_base=local)
    assert r.status_code == 400 and not (trainings / "x.fit").exists()
    r = c.post("/api/trainings/upload", data={"file": (io.BytesIO(b"<tcx/>"), "x.tcx")}, environ_base=local)
    assert r.status_code == 400
    r = c.post("/api/trainings/upload", data={"file": (io.BytesIO(b"x"), "y.fit")}, environ_base={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403


def test_analysis_recognises_route_from_gps(client, monkeypatch, tmp_path):
    c, _ = client
    trainings = tmp_path / "trainings"
    trainings.mkdir()
    monkeypatch.setattr(launcher, "TRAININGS_DIR", trainings)
    _make_fit(trainings / "skiErg_gps.fit", seconds=300, gps=True)     # läuft auf a.gpx (46.70 -> 46.71, 9.80)
    d = c.get("/api/vergleich?fit=skiErg_gps.fit").get_json()
    assert d["ok"] and d["route_name"] == "a"
    assert d["has_original"] is False          # das Test-GPX hat keine Zeitstempel
    assert len(d["elevation_m"]) == len(d["x_km"])


def test_resume_point_per_route(client, monkeypatch, tmp_path):
    """Weiterlaufen: pro Strecke zählt das zuletzt gestartete Training; am Ziel gibt es nichts fortzusetzen."""
    from Utils.fit_export import FitRecorder, FitSample

    def fit_on_route(name, t0, start_m, length_m):
        rec = FitRecorder()
        n = int(length_m / 3.0)
        for i in range(n + 1):
            d = start_m + i * 3.0
            rec.add(FitSample(t=t0 + i, distance_m=i * 3.0, speed_m_s=3.0, heart_rate=140, cadence=50, power=40,
                              lat=46.70 + d / 111_195.0, lon=9.80, altitude_m=1500 + d * 0.045, grade_percent=None),
                    lap_key=None, lap_trigger=0)
        rec.write(str(trainings / name))

    c, _ = client
    trainings = tmp_path / "trainings"
    trainings.mkdir()
    monkeypatch.setattr(launcher, "TRAININGS_DIR", trainings)
    assert "resume" not in c.get("/api/launcher").get_json()["routes"][0]
    fit_on_route("a_alt.fit", 1_791_300_000.0, 0.0, 300.0)          # älter: bis 300 m
    fit_on_route("a_neu.fit", 1_791_400_000.0, 300.0, 300.0)        # neuer: von 300 m bis 600 m
    route = c.get("/api/launcher").get_json()["routes"][0]          # a.gpx ist ~1.1 km lang
    assert route["resume"]["file"] == "a_neu.fit" and route["resume"]["km"] == pytest.approx(0.6, abs=0.02)
    fit_on_route("a_ziel.fit", 1_791_500_000.0, 600.0, 500.0)       # neuestes Training läuft bis ins Ziel
    assert "resume" not in c.get("/api/launcher").get_json()["routes"][0]


# ---------------------- Zuschauer: nur ansehen, dem Gerät folgen ----------------------
REMOTE = {"REMOTE_ADDR": "192.168.1.50"}
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}


def test_remote_browser_cannot_control(client, monkeypatch):
    c, started = client
    monkeypatch.setattr(launcher.os, "_exit", lambda code: pytest.fail("darf nicht beenden"))
    # ansehen geht
    assert c.get("/", environ_base=REMOTE).status_code == 200
    assert c.get("/api/launcher", environ_base=REMOTE).status_code == 200
    assert c.get("/api/role", environ_base=REMOTE).get_json() == {"control": False}
    assert c.get("/api/role", environ_base=LOCAL).get_json() == {"control": True}
    # steuern nicht: jede ändernde Anfrage wird abgelehnt
    for path, body in (("/start", {"mode": "profile"}), ("/start", {"mode": "skier", "route": "a.gpx"}), ("/api/quit", {}),
                       ("/api/profiles/activate", {"file": "x"}), ("/api/profiles/new", {"name": "x"}),
                       ("/api/profile", {"values": {}}), ("/api/screen", {"path": "/profil"})):
        r = c.post(path, json=body, environ_base=REMOTE)
        assert r.status_code == 403 and r.get_json()["ok"] is False, path
    assert started == []


def test_viewer_follows_screen_of_local_browser(client):
    c, _ = client
    # Startmenü = kein Training: Zuschauer warten und erfahren nicht, welche Seite am Gerät offen ist
    c.post("/api/screen", json={"path": "/profil"}, environ_base=LOCAL)
    assert c.get("/api/screen", environ_base=REMOTE).get_json() == {"path": None, "training": False}

    # Trainingsprogramm: Zuschauer folgen der Seite des Geräts
    from flask import Flask
    from Utils.access import install_access_control
    app = Flask(__name__)
    install_access_control(app, training=True)
    t = app.test_client()
    assert t.get("/api/screen", environ_base=REMOTE).get_json() == {"path": None, "training": True}   # noch nichts gemeldet
    assert t.post("/api/screen", json={"path": "/strecke"}, environ_base=LOCAL).get_json() == {"ok": True}
    assert t.get("/api/screen", environ_base=REMOTE).get_json() == {"path": "/strecke", "training": True}
    # fremde Adressen werden nicht übernommen, Zuschauer können nichts melden
    t.post("/api/screen", json={"path": "https://example.org/"}, environ_base=LOCAL)
    t.post("/api/screen", json={"path": "//example.org/"}, environ_base=LOCAL)
    assert t.post("/api/screen", json={"path": "/sic"}, environ_base=REMOTE).status_code == 403
    assert t.get("/api/screen", environ_base=REMOTE).get_json()["path"] == "/strecke"


def test_only_local_browser_keeps_app_alive(client):
    c, _ = client
    alive = c.application.config["XSKI_ALIVE"]
    alive["until"] = 0.0
    c.get("/api/alive", environ_base=REMOTE)
    c.get("/", environ_base=REMOTE)
    assert alive["until"] == 0.0                       # Zuschauer verlängern die Frist nicht
    c.get("/api/alive", environ_base=LOCAL)
    assert alive["until"] > 0.0


def test_every_page_loads_viewer_script():
    templates = Path(launcher.__file__).parent / "templates"
    for page in templates.glob("*.html"):
        assert "/static/js/viewer.js" in page.read_text(encoding="utf-8"), page.name
