# launcher.py – Startmenü: zuerst den Trainingsmodus wählen, dann x-ski.py im gewählten Modus starten
#
# Der Launcher berührt den Antrieb nicht. Nach der Wahl ersetzt er sich per exec durch x-ski.py
# (gleicher Prozess, gleiches Log, Port 5000 wird frei) mit den passenden Kommandozeilen-Schaltern.

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

from flask import Flask, jsonify, render_template, request

from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.route import Route, list_route_files, resolve_route_file
from Utils.profile_page import create_profile_blueprint
from Utils.settings import Settings

SCRIPT_DIR = Path(__file__).resolve().parent
XSKI_SCRIPT = SCRIPT_DIR / "x-ski.py"
ROUTES_DIR = SCRIPT_DIR.parent / "routes"
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
    starting = threading.Event()
    alive = {"until": time.monotonic() + BROWSER_TIMEOUT_S}   # Frist bis zum nächsten Lebenszeichen
    app.config["XSKI_ALIVE"] = alive

    @app.before_request
    def browser_seen():
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

    allow_remote = os.environ.get("X_SKI_ALLOW_REMOTE_CONFIG", "0") == "1"
    app.register_blueprint(create_profile_blueprint(cfg_manager, on_saved=load_config, allow_remote=allow_remote))

    @app.route("/")
    def start_page():
        return render_template("start.html")

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
        routes = [route_entry(name) for name in list_route_files(ROUTES_DIR)]
        return jsonify({
            "launcher": True,
            "skier_available": state["settings"].motor_rated_torque_nm > 0,
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
