# launcher.py – Startmenü: zuerst den Trainingsmodus wählen, dann x-ski.py im gewählten Modus starten
#
# Der Launcher berührt den Antrieb nicht. Nach der Wahl ersetzt er sich per exec durch x-ski.py
# (gleicher Prozess, gleiches Log, Port 5000 wird frei) mit den passenden Kommandozeilen-Schaltern.

import argparse
import json
import os
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

from flask import Flask, jsonify, render_template, request

from Utils.access import install_access_control, is_local
from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.route import Route, list_route_files, resolve_route_file
from Utils.profile_page import create_profile_blueprint
from Utils.machine_page import create_machine_blueprint
from Utils.settings import Settings
from Utils.speed_compare import (comparison_payload, fit_overview, load_fit_records, match_route, training_payload,
                                 training_summary)

SCRIPT_DIR = Path(__file__).resolve().parent
XSKI_SCRIPT = SCRIPT_DIR / "x-ski.py"
ROUTES_DIR = SCRIPT_DIR.parent / "routes"
# X_SKI_TRAININGS_DIR: anderer Ordner nur für Tests (damit der echte Trainingsordner unberührt bleibt)
TRAININGS_DIR = Path(os.environ.get("X_SKI_TRAININGS_DIR") or SCRIPT_DIR.parents[1] / "trainings")
COMPARISON_INFO_FILE = "letzter_vergleich.json"   # von x-ski.py nach einem Streckentraining geschrieben
RESUME_MIN_REST_KM = 0.3   # «Weiterlaufen» nur anbieten, wenn bis zum Ziel noch so viel Strecke bleibt
PORT = 5000
# Ohne Lebenszeichen vom Browser (Startseite fragt alle 5 s nach) beendet sich x-ski. Grosszügig, weil
# Browser Zeitgeber in Hintergrund-Tabs auf 1×/min drosseln.
BROWSER_TIMEOUT_S = 90
STRAVA_CONNECT_GRACE_S = 900   # beim Verbinden mit Strava ist der Browser länger auf strava.com

MODES = {
    # Modus -> Startseite in x-ski
    "skier": "/strecke",
    "profile": "/sic",
    "interval": "/iic",
    "calib": "/kalibrierung",   # Seilzug kalibrieren (aus dem Profil-Formular)
}


def build_xski_argv(mode: str, route: Optional[str], *, config_path: Optional[str], host: str,
                    no_browser: bool, start_km: Optional[float] = None, end_km: Optional[float] = None) -> List[str]:
    """Kommandozeile für x-ski.py zum gewählten Modus."""
    if mode not in MODES:
        raise ValueError(f"Unbekannter Modus '{mode}'")
    argv = [sys.executable, "-u", str(XSKI_SCRIPT), "--mode", mode, "--host", host]
    if mode == "skier":
        if not route:
            raise ValueError("In der Streckensimulation muss eine Strecke gewählt werden.")
        argv += ["--route", route]
        if start_km is not None:
            argv += ["--route-start-km", f"{float(start_km):.3f}"]
        if end_km is not None:
            argv += ["--route-end-km", f"{float(end_km):.3f}"]
    if config_path:
        argv += ["--config", config_path]
    # Die Seite ist schon offen (Startmenü) – x-ski soll keinen neuen Browser-Tab öffnen
    argv.append("--no-browser" if no_browser else "--no-open")
    return argv


def power_off():
    """Raspberry Pi herunterfahren (sudo ohne Passwort ist auf dem Pi eingerichtet)."""
    import subprocess
    subprocess.Popen(["sudo", "-n", "/usr/bin/systemctl", "poweroff"])


def create_app(args) -> Flask:
    app = Flask(__name__, template_folder=str(SCRIPT_DIR / "templates"), static_folder=str(SCRIPT_DIR / "static"))
    cfg_manager = ConfigManager(script_dir=SCRIPT_DIR, active_filename="x-ski.json", config_dirname="configs",
                                default_config=DEFAULT_CONFIG, env_var="X_SKI_CONFIG")
    state = {}

    def load_config():
        config, _ = cfg_manager.load_from_candidates(cli_path=args.config_path)
        state["config"] = config
        state["settings"] = Settings.from_config(config, cfg_manager.get_training_targets())

    load_config()
    allow_remote = os.environ.get("X_SKI_ALLOW_REMOTE_CONFIG", "0") == "1"
    starting = threading.Event()
    alive = {"until": time.monotonic() + BROWSER_TIMEOUT_S}   # Frist bis zum nächsten Lebenszeichen
    app.config["XSKI_ALIVE"] = alive

    # Steuern nur am Gerät (siehe Utils/access.py) – zuerst registriert, damit die Sperre zuerst greift
    install_access_control(app, allow_remote=allow_remote)

    @app.before_request
    def browser_seen():
        if not is_local():
            return      # nur der Browser am Gerät hält x-ski am Leben, Zuschauer nicht
        grace = STRAVA_CONNECT_GRACE_S if request.path == "/strava/connect" else BROWSER_TIMEOUT_S
        alive["until"] = max(alive["until"], time.monotonic() + grace)

    @app.route("/api/alive")
    def api_alive():
        return jsonify({"ok": True})

    @app.route("/api/quit", methods=["POST"])
    def api_quit():
        if not allow_remote and request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"ok": False, "message": "x-ski kann nur direkt am Gerät beendet werden."}), 403
        print("🛑 x-ski wird beendet (Kachel «Beenden»).", flush=True)
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return jsonify({"ok": True})

    @app.route("/api/shutdown", methods=["POST"])
    def api_shutdown():
        """Kachel «Ausschalten»: x-ski beenden und den Raspberry Pi herunterfahren (nur am Gerät, nicht während
        ein Training startet)."""
        if not allow_remote and request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"ok": False, "message": "Ausschalten geht nur direkt am Gerät."}), 403
        if starting.is_set():
            return jsonify({"ok": False, "message": "Ein Training startet gerade."}), 409
        print("⏻ Raspberry Pi wird heruntergefahren (Kachel «Ausschalten»).", flush=True)
        release_hr()

        def off():
            power_off()
            time.sleep(2)
            os._exit(0)
        threading.Timer(1.0, off).start()
        return jsonify({"ok": True})

    # Pulsgurt im Startmenü: erst wenn die Profilseite danach fragt (der ANT-Stick gehört dann dem Startmenü,
    # bis ein Training startet – vorher wird er freigegeben)
    hr = {"mgr": None}
    hr_lock = threading.Lock()

    def hr_manager():
        s = state["settings"]
        with hr_lock:
            if hr["mgr"] is None and s.ant_hr_enabled and not starting.is_set():
                from Utils.ant_hr_manager import ANTHRManager
                hr["mgr"] = ANTHRManager(device_id=s.ant_hr_device_id, enabled=True)
            return hr["mgr"]

    def release_hr():
        with hr_lock:
            mgr, hr["mgr"] = hr["mgr"], None
        if mgr is not None:
            try:
                mgr.close()
            except Exception as e:
                print(f"Warnung beim Freigeben des Pulsgurts: {e}")

    app.register_blueprint(create_profile_blueprint(cfg_manager, on_saved=load_config, allow_remote=allow_remote,
                                                    hr_manager=hr_manager))
    app.register_blueprint(create_machine_blueprint(cfg_manager, on_saved=load_config, allow_remote=allow_remote))

    @app.route("/")
    def start_page():
        return render_template("start.html")

    @app.route("/3d")
    def route_3d_page():
        # Tablet mit der 3D-Ansicht: im Startmenü «Warten auf Training», beim Trainingsstart übernimmt x-ski
        return render_template("route3d.html")

    @app.route("/header")
    def header():
        return render_template("partials/header.html", user=state["config"].get("user", {}),
                               active=request.args.get("active", "start"), show_route=False, mode=None,
                               show_config=False, show_quit=request.args.get("active", "start") == "start")

    route_cache = {}  # Dateiname -> ((Änderungszeit, Grösse), Eintrag)

    def route_entry(name: str) -> dict:
        """Streckendaten für die Auswahl; nur neue oder geänderte GPX-Dateien werden neu eingelesen."""
        stat = (ROUTES_DIR / name).stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = route_cache.get(name)
        if cached and cached[0] == key:
            return cached[1]
        try:
            r = Route.from_gpx(ROUTES_DIR / name)
            prof = r.to_geojson_payload(max_points=50)["profile"]["elevation_m"]
            step = max(1, len(prof) // 60)
            entry = {"file": name, "name": r.name.replace("_", " "), "length_km": round(r.length_m / 1000, 1),
                     "gain_m": round(r.elevation_gain_m), "loss_m": round(r.elevation_loss_m),
                     "sparkline": prof[::step]}  # Mini-Höhenprofil für die Kachel
        except Exception as e:
            entry = {"file": name, "name": Path(name).stem.replace("_", " "), "error": str(e)}
        route_cache[name] = (key, entry)
        return entry

    @app.route("/api/launcher")
    def api_launcher():
        # Bei jedem Aufruf Konfiguration und Streckenordner neu lesen (auch extern geänderte Dateien)
        try:
            load_config()
        except Exception as e:
            print(f"⚠️ Konfiguration nicht lesbar: {e}")
        routes = [dict(route_entry(name)) for name in list_route_files(ROUTES_DIR)]
        # Weiterlaufen: Endpunkt des letzten Trainings auf dieser Strecke – nur wenn noch genug Strecke übrig ist
        try:
            resume = resume_points()
        except Exception as e:
            print(f"⚠️ Fortsetzungspunkte nicht bestimmt: {e}")
            resume = {}
        for r in routes:
            point = resume.get(r["file"])
            if point and "length_km" in r and 0.05 < point["km"] < r["length_km"] - RESUME_MIN_REST_KM:
                r["resume"] = point
        return jsonify({
            "launcher": True,
            "skier_available": state["settings"].motor_rated_torque_nm > 0,
            "has_comparison": comparison_info() is not None,
            "routes": routes,
        })

    @app.route("/api/launcher/route")
    def api_launcher_route():
        path = resolve_route_file(ROUTES_DIR, request.args.get("file", ""))
        if path is None:
            return jsonify({"message": "Strecke nicht gefunden"}), 404
        r = Route.from_gpx(path)
        payload = r.to_geojson_payload()
        payload["file"] = path.name
        return jsonify(payload)

    # ---------------------- Tempovergleich nach dem Streckentraining ----------------------
    def comparison_info():
        path = TRAININGS_DIR / COMPARISON_INFO_FILE
        if not path.exists():
            return None
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        fit = TRAININGS_DIR / Path(str(info.get("fit", ""))).name
        gpx = resolve_route_file(ROUTES_DIR, str(info.get("route_file", "")))
        if not fit.exists() or gpx is None:
            return None
        info.update(fit_path=fit, gpx_path=gpx)
        return info

    @app.route("/vergleich")
    def comparison_page():
        return render_template("vergleich.html")

    route_objects = {}   # Dateiname -> ((Änderungszeit, Grösse), Route) für die Streckenerkennung

    def all_routes():
        out = []
        for name in list_route_files(ROUTES_DIR):
            stat = (ROUTES_DIR / name).stat()
            key = (stat.st_mtime_ns, stat.st_size)
            if name not in route_objects or route_objects[name][0] != key:
                try:
                    route_objects[name] = (key, Route.from_gpx(ROUTES_DIR / name))
                except Exception:
                    continue
            out.append((name, route_objects[name][1]))
        return out

    def training_file(name: str):
        """Nur Dateien direkt im Trainingsordner (kein Pfad von aussen)."""
        path = TRAININGS_DIR / Path(str(name)).name
        return path if path.suffix.lower() == ".fit" and path.is_file() else None

    def info_for_file(fit: Path):
        """Strecke und Abschnitt einer beliebigen Aufzeichnung (anhand ihrer GPS-Punkte, siehe training_info)."""
        e = training_info(fit)
        if e.get("error"):
            raise ValueError(e["error"])
        info = {"fit_path": fit, "gpx_path": None, "title": "", "route_name": "",
                "stamp": (re.search(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(-\d{2})?", fit.stem) or [""])[0]}
        if e.get("route_file"):
            route = next(r for n, r in all_routes() if n == e["route_file"])
            info.update(gpx_path=ROUTES_DIR / e["route_file"], route_name=e["route_name"],
                        section_start_m=e["section_start_m"], route_length_m=route.length_m)
        return info

    @app.route("/api/vergleich")
    def api_comparison():
        wanted = request.args.get("fit")
        if wanted:
            fit = training_file(wanted)
            if fit is None:
                return jsonify({"ok": False, "message": "Diese Trainingsdatei gibt es nicht."}), 404
            try:
                info = info_for_file(fit)
            except Exception as e:
                return jsonify({"ok": False, "message": f"Datei nicht lesbar: {e}"}), 400
        else:
            info = comparison_info()
        if info is None:
            return jsonify({"ok": False, "message": "Es gibt noch kein Streckentraining zum Vergleichen."}), 404
        try:
            if info.get("gpx_path"):
                data = comparison_payload(info["fit_path"], info["gpx_path"], float(info.get("section_start_m") or 0.0),
                                          float(info.get("route_length_m") or 0.0) or None)
            else:
                data = training_payload(info["fit_path"])      # ohne GPS/Strecke: nur das Training
        except Exception as e:
            return jsonify({"ok": False, "message": f"Auswertung nicht möglich: {e}"}), 400
        try:
            data["summary"] = training_summary(info["fit_path"], cfg_manager.get_training_targets(),
                                               state["settings"].weight_kg)
        except Exception as e:
            print(f"⚠️ Kennzahlen der Auswertung nicht berechnet: {e}")
        data.update(ok=True, title=info.get("title", ""), route_name=info.get("route_name", ""), stamp=info.get("stamp", ""))
        return jsonify(data)

    # ---------------------- Trainingsdateien wählen / laden ----------------------
    file_cache = {}   # Dateiname -> ((Änderungszeit, Grösse), Info)

    def training_info(path: Path) -> dict:
        """Kurzinfo einer Aufzeichnung inkl. erkannter Strecke und Endpunkt auf dieser Strecke (zwischengespeichert)."""
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = file_cache.get(path.name)
        if cached and cached[0] == key:
            return cached[1]
        try:
            entry = fit_overview(path)
            routes = all_routes()
            match = match_route(load_fit_records(path), [r for _, r in routes])
            if match:
                name = next(n for n, r in routes if r is match["route"])
                entry.update(route_file=name, route_name=match["route"].name.replace("_", " "),
                             section_start_m=round(match["section_start_m"], 1),
                             end_m=round(match["section_start_m"] + entry["distance_km"] * 1000.0, 1))
        except Exception as e:
            entry = {"error": str(e)}
        file_cache[path.name] = (key, entry)
        return entry

    def training_files():
        if not TRAININGS_DIR.is_dir():
            return []
        return sorted(TRAININGS_DIR.glob("*.fit"), key=lambda q: q.stat().st_mtime, reverse=True)[:80]

    def resume_points() -> dict:
        """Pro Strecke das zuletzt gelaufene Training (nach Startzeit) und wo es aufgehört hat:
        {GPX-Datei: {"km": …, "start": Startzeit, "file": …}}. Die Strecke wird aus den GPS-Punkten der
        Aufzeichnung erkannt, nicht aus dem Dateinamen."""
        latest = {}
        for path in training_files():
            e = training_info(path)
            if e.get("route_file") and (e["route_file"] not in latest or e["start"] > latest[e["route_file"]]["start"]):
                latest[e["route_file"]] = {"km": round(e["end_m"] / 1000.0, 2), "start": e["start"], "file": path.name}
        return latest

    @app.route("/auswertung")
    def analysis_page():
        return render_template("auswertung.html")

    @app.route("/api/trainings")
    def api_trainings():
        return jsonify({"files": [{"file": path.name, **training_info(path)} for path in training_files()]})

    @app.route("/api/trainings/upload", methods=["POST"])
    def api_trainings_upload():
        if not allow_remote and request.remote_addr not in ("127.0.0.1", "::1"):
            return jsonify({"ok": False, "message": "Dateien können nur direkt am x-ski geladen werden."}), 403
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"ok": False, "message": "Keine Datei gewählt."}), 400
        name = Path(f.filename).name
        if not name.lower().endswith(".fit"):
            return jsonify({"ok": False, "message": "Bitte eine FIT-Datei wählen (TCX enthält kein GPS und keine Sekundenwerte)."}), 400
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        TRAININGS_DIR.mkdir(parents=True, exist_ok=True)
        target = TRAININGS_DIR / safe
        if target.exists():
            target = TRAININGS_DIR / f"{target.stem}_{int(time.time())}.fit"
        f.save(target)
        try:
            fit_overview(target)
        except Exception as e:
            target.unlink(missing_ok=True)
            file_cache.pop(target.name, None)
            return jsonify({"ok": False, "message": f"Die Datei ist keine lesbare FIT-Aufzeichnung: {e}"}), 400
        print(f"📥 Trainingsdatei geladen: {target.name}")
        return jsonify({"ok": True, "file": target.name})

    @app.route("/start", methods=["POST"])
    def start():
        data = request.get_json(silent=True) or {}
        mode = str(data.get("mode", ""))
        route = data.get("route") or None
        start_km = data.get("start_km")
        end_km = data.get("end_km")
        if mode == "skier":
            path = resolve_route_file(ROUTES_DIR, route or "")
            if path is None:
                return jsonify({"ok": False, "message": "Bitte eine gültige Strecke wählen."}), 400
            try:
                start_m, end_m = Route.from_gpx(path).section(start_km, end_km)  # prüft den Abschnitt
            except (ValueError, TypeError) as e:
                return jsonify({"ok": False, "message": str(e)}), 400
            start_km = None if start_km is None else start_m / 1000.0
            end_km = None if end_km is None else end_m / 1000.0
        try:
            argv = build_xski_argv(mode, route, config_path=args.config_path, host=args.host,
                                   no_browser=args.no_browser, start_km=start_km, end_km=end_km)
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400
        if starting.is_set():
            return jsonify({"ok": True, "next": MODES[mode]})
        starting.set()

        def exec_xski():
            release_hr()               # ANT-Stick freigeben, x-ski öffnet ihn neu
            print(f"▶️ Starte x-ski: {' '.join(argv[2:])}", flush=True)
            os.chdir(SCRIPT_DIR)
            # Alle geerbten Dateideskriptoren ausser stdin/stdout/stderr schliessen – sonst bleibt der
            # Server-Socket des Launchers offen und x-ski kann Port 5000 nicht übernehmen.
            os.closerange(3, 4096)
            os.execv(argv[0], argv)

        # Erst antworten, dann den Prozess ersetzen
        threading.Timer(0.5, exec_xski).start()
        return jsonify({"ok": True, "next": MODES[mode]})

    return app


def watch_browser(app):
    """x-ski beenden, wenn der Browser geschlossen wurde (kein Lebenszeichen mehr innerhalb der Frist)."""
    alive = app.config["XSKI_ALIVE"]
    while True:
        time.sleep(5)
        if time.monotonic() > alive["until"]:
            print("🛑 Browser geschlossen (kein Lebenszeichen) – x-ski wird beendet.", flush=True)
            os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="x-ski Startmenü")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-browser", dest="no_browser", action="store_true")
    parser.add_argument("--port", type=int, default=PORT, help="nur für Tests; x-ski selbst läuft immer auf 5000")
    args = parser.parse_args()

    app = create_app(args)
    print(f"🏠 x-ski Startmenü: http://localhost:{args.port}/", flush=True)
    threading.Thread(target=watch_browser, args=(app,), daemon=True, name="browser-watch").start()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}/")).start()
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
