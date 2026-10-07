# x-ski.py – x-ski WebGUI + Training + Konfig-Management mit ConfigManager & BLEManager

import json
import os
import sys
import time
import argparse
import dataclasses
import statistics
import traceback
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread

import numpy as np
from flask import jsonify, render_template, request

from BasicWebGUI import Backend
from HardwareController.DriveM751 import DriveM751
from IntensityController.IntervallIntensityController import IntervallIntensityController
from IntensityController.SimpleIntensityController import SimpleIntensityController
from ValueHandler.Scope import Scope
from Utils.ant_hr_manager import ANTHRManager
from Utils.ble_manager import BLEManager
from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.email_utils import send_training_email
from Utils.force_profile import build_force_profile_absolute, build_target_torque_curve_absolute
from Utils.settings import MAX_TRAVEL_MM, Settings, safe_float
from Utils.skier_model import (
    StrokeForcePlanner,
    RopeSpeedEstimator,
    Terrain,
    VirtualSkier,
    estimate_rated_torque_nm,
    force_to_torque_pct,
    intensity_to_slope_percent,
)
from Utils.stroke_analysis import StrokeAnalyzer
from Utils.tcx_export import write_tcx
from Utils.fit_export import FitRecorder, FitSample
from Utils import strava_client
from Utils.route import Route, RoutePosition, list_route_files, resolve_route_file
from Utils.profile_page import create_profile_blueprint, update_active_profile
from Utils.rope_calibration import RopeCalibration
from Utils.traccar_eelink import TrackerFix
from Utils.traccar_osmand import create_tracker


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[1]
TRAININGS_DIR = PROJECT_DIR / "trainings"
ROUTES_DIR = SCRIPT_DIR.parent / "routes"
ROUTE_PUBLISH_INTERVAL_S = 0.25

# Uhr / Session startet beim ersten Zug mit |speed| über diesem Wert
PULL_START_SPEED_THRESHOLD = 5.0
# Abstand des Software-Nullpunkts vom oberen Anschlag [mm]
SOFT_ZERO_OFFSET_MM = 50
# Zusätzliche Pause pro Regelzyklus. 0 = keine: die Modbus-Anfragen (~5 ms pro Anfrage)
# takten die Schleife ohnehin; die Pause kostete ~25 % der Regelfrequenz (23 Hz gemessen).
LOOP_SLEEP_S = 0.0
# Das Drehzahlregister wird nur noch zur Plausibilisierung gelesen; in der Regelschleife
# wird die Seilgeschwindigkeit aus der Encoderposition berechnet (spart eine Modbus-Anfrage).
SPEED_REGISTER_CHECK_INTERVAL_S = 1.0
# Thermische Auslastung von Motor und Bremswiderstand (Drive-Schutzmodelle) überwachen
THERMAL_CHECK_INTERVAL_S = 5.0
THERMAL_WARN_PCT = 75.0
# Ab dieser Seilgeschwindigkeit nach unten gilt ein Zug (sonst Rückzug/Stillstand)
PULL_DETECT_M_S = 0.05
FTMS_PUSH_INTERVAL_S = 0.25
# Kürzere Trainings: beim Stop fragen, ob gespeichert werden soll
SHORT_SESSION_S = 300
# «Weiter» nach einer Pause: so lange Countdown, dann wird der Antrieb freigegeben und spannt das Seil
RESUME_COUNTDOWN_S = 3.0
# Ohne Lebenszeichen vom Browser (Trainingsseiten fragen jede Sekunde nach) wird x-ski beendet.
# Grosszügig, weil Browser Zeitgeber in Hintergrund-Tabs auf 1×/min drosseln.
BROWSER_TIMEOUT_S = 90
STRAVA_CONNECT_GRACE_S = 900

# Diese Endpunkte verändern die Konfiguration bzw. legen Dateien ab und sind nur
# direkt am x-ski (localhost) erlaubt, ausser X_SKI_ALLOW_REMOTE_CONFIG=1.
LOCAL_ONLY_PATHS = {
    "/api/config/save",
    "/api/config/activate",
    "/api/reload_config",
    "/upload_interval_file",
    "/api/profile",
    "/api/profiles/activate",
    "/api/profiles/new",
    "/api/calibration",
}
ALLOW_REMOTE_CONFIG = os.environ.get("X_SKI_ALLOW_REMOTE_CONFIG", "0") == "1"

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--config", dest="config_path", default=None)
parser.add_argument("--controller", choices=["sic", "iic"], default="sic")
parser.add_argument("--mode", choices=["skier", "profile", "interval", "calib"], default=None,
                    help="Trainingsmodus: skier (Streckensimulation), profile (Belastungsprofil), interval, "
                         "calib (Seilzug kalibrieren). "
                         "Ohne Angabe gelten --controller und simulation.load_mode aus der Konfiguration.")
parser.add_argument("--route", default=None, help="GPX-Datei aus src/routes (nur Streckensimulation)")
parser.add_argument("--route-start-km", dest="route_start_km", type=float, default=None,
                    help="Abschnitt: Start bei km (Standard: Streckenanfang)")
parser.add_argument("--route-end-km", dest="route_end_km", type=float, default=None,
                    help="Abschnitt: Ziel bei km (Standard: Streckenende)")
parser.add_argument("--no-browser", dest="no_browser", action="store_true")
parser.add_argument("--no-open", dest="no_open", action="store_true",
                    help="Browser nicht öffnen (die Seite ist schon offen, z.B. vom Startmenü), aber auf sie warten")
parser.add_argument("--host", default="0.0.0.0",
                    help="Adresse für den Webserver (127.0.0.1 = nur lokal erreichbar)")
known_args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]

MODE = known_args.mode
if MODE == "interval":
    known_args.controller = "iic"
elif MODE in ("skier", "profile", "calib"):
    known_args.controller = "sic"

cfg_manager = ConfigManager(
    script_dir=SCRIPT_DIR,
    active_filename="x-ski.json",
    config_dirname="configs",
    default_config=DEFAULT_CONFIG,
    env_var="X_SKI_CONFIG",
)
config, config_path = cfg_manager.load_from_candidates(cli_path=known_args.config_path)


def mode_overrides() -> dict:
    """Vorgaben aus --mode/--route haben Vorrang vor der Konfigurationsdatei (auch nach einem Reload)."""
    overrides = {}
    if MODE == "skier":
        overrides["load_mode"] = "skier"
    elif MODE in ("profile", "interval", "calib"):
        overrides.update(load_mode="profile", route_file="")  # keine Strecke im Belastungsprofil/Intervall
    if known_args.route is not None and MODE in (None, "skier"):
        overrides["route_file"] = known_args.route
    return overrides


def build_settings(cfg) -> Settings:
    new_settings = Settings.from_config(cfg, cfg_manager.get_training_targets())
    overrides = mode_overrides()
    if overrides:
        new_settings = dataclasses.replace(new_settings, **overrides)
    new_settings.validate_geometry()
    return new_settings


settings = build_settings(config)
current_gui_intensity = 60.0


SKIER_INITIAL_INTENSITY = 100  # Skifahrer-Modus: 100 % = Strecke ohne Zusatz-Steigung


def initial_intensity(s: Settings) -> float:
    """Startwert der +/- Tasten: im Skifahrer-Modus immer 100 (Strecke wie sie ist),
    im Belastungsprofil der Wert aus dem Profil (control.simple_initial_power_pct)."""
    return SKIER_INITIAL_INTENSITY if s.skier_mode_requested else s.simple_initial_power_pct


def create_ble_manager():
    return BLEManager(
        enable_ftms=settings.ble_enabled,
        ftms_device_name=settings.ble_name,
        ftms_adapter=settings.ble_adapter,
    )


def create_ant_hr_manager():
    return ANTHRManager(
        device_id=settings.ant_hr_device_id,
        enabled=settings.ant_hr_enabled,
    )


def print_settings_summary():
    s = settings
    print(f"Max HR: {s.max_hr_bpm}")
    print(f"FTP: {s.ftp_w} W")
    print(f"SIC Initial Power: {s.simple_initial_power_pct}")
    print(f"Training targets: {s.training_targets}")
    print(f"MyWhoosh BLE enabled: {s.ble_enabled}")
    print(f"MyWhoosh BLE name: {s.ble_name}")
    print(f"MyWhoosh BLE adapter: {s.ble_adapter}")
    print(f"ANT HR enabled: {s.ant_hr_enabled}")
    print(f"ANT HR device_id: {s.ant_hr_device_id}")
    print(f"Lastmodell: {s.load_mode} (Streckensimulation verfügbar: {s.skier_mode_available}), "
          f"CdA {s.cda_m2} m², µ {s.mu}, Grundsteigung {s.slope_percent} %")


def apply_runtime_reload():
    global config, config_path, settings, ble_manager, ant_hr_manager

    old = settings
    result = cfg_manager.reload_active()
    # Erst validieren, dann übernehmen: bei ungültiger Geometrie bleiben die alten Werte aktiv
    new_settings = build_settings(cfg_manager.config)

    config = cfg_manager.config
    config_path = cfg_manager.ACTIVE_CONFIG_PATH
    settings = new_settings

    ant_config_changed = (
        old.ant_hr_enabled != settings.ant_hr_enabled
        or old.ant_hr_device_id != settings.ant_hr_device_id
    )
    ftms_config_changed = (
        old.ble_enabled != settings.ble_enabled
        or old.ble_name != settings.ble_name
        or old.ble_adapter != settings.ble_adapter
    )

    if ant_hr_manager is None or ant_config_changed:
        try:
            if ant_hr_manager is not None and hasattr(ant_hr_manager, "close"):
                ant_hr_manager.close()
        except Exception as e:
            print(f"Warnung beim Schließen des alten ANT HR Managers: {e}")

        ant_hr_manager = create_ant_hr_manager()

    if ble_manager is None:
        ble_manager = create_ble_manager()

    if ftms_config_changed:
        print("Hinweis: Änderungen an mywhoosh_ble werden erst nach einem Neustart vollständig wirksam.")

    if scope is not None:
        scope.max_hr_bpm = settings.max_hr_bpm
        scope.ftp_w = settings.ftp_w
        scope.training_targets = settings.training_targets

    if drive is not None:
        drive.max_torque_pct = float(settings.max_torque_pct)

    if isinstance(active_ic, SimpleIntensityController) and hasattr(active_ic, "set_init_value"):
        active_ic.set_init_value(initial_intensity(settings), apply_now=False)

    print("Konfiguration neu geladen.")
    print_settings_summary()

    return result


page_loaded = False
page_lock = Lock()

ble_manager = create_ble_manager()
ant_hr_manager = create_ant_hr_manager()
scope = None
drive = None

app = Backend(__name__)

ACTIVE_CONTROLLER_NAME = known_args.controller

if ACTIVE_CONTROLLER_NAME == "iic":
    active_ic = IntervallIntensityController()
    START_PAGE = "http://localhost:5000/iic"
else:
    active_ic = SimpleIntensityController(init_value=initial_intensity(settings))
    current_gui_intensity = float(active_ic.getIntensity())
    # Skifahrer-Modus: Kartenansicht (Strecke); Belastungsprofil: Training ohne Karte
    START_PAGE = "http://localhost:5000/strecke" if settings.skier_mode_requested else "http://localhost:5000/sic"
if MODE == "calib":
    START_PAGE = "http://localhost:5000/kalibrierung"

print(f"Aktiver Controller: {ACTIVE_CONTROLLER_NAME} | Modus: {MODE or 'aus Konfiguration'} | "
      f"Lastmodell: {settings.load_mode} | Strecke: {settings.route_file or '-'}")


def _first_attr(obj, names):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _safe_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_interval_phase(raw_phase, is_active):
    if raw_phase is None:
        return "active" if is_active else "idle"

    txt = str(raw_phase).strip().lower()

    if any(token in txt for token in ["work", "belast", "interval", "on"]):
        return "work"
    if any(token in txt for token in ["rest", "pause", "recover", "off", "locker"]):
        return "rest"
    if any(token in txt for token in ["idle", "ready", "wait", "stop", "stopped"]):
        return "idle"

    return txt


def get_controller_status():
    ic = active_ic
    is_active = bool(getattr(ic, "active", False))

    raw_phase = _first_attr(ic, [
        "interval_phase",
        "phase",
        "current_phase",
        "work_rest_state",
        "state",
    ])

    current_interval = _safe_int_or_none(_first_attr(ic, [
        "current_interval",
        "current_intervall",
        "interval_index",
        "current_rep",
        "current_repetition",
        "current_step",
    ]))

    total_intervals = _safe_int_or_none(_first_attr(ic, [
        "total_intervals",
        "total_intervalls",
        "num_intervals",
        "nr_intervals",
        "repetitions",
        "num_reps",
        "total_repetitions",
    ]))

    return {
        "controller_mode": ACTIVE_CONTROLLER_NAME,
        "interval_active": is_active,
        "interval_phase": _normalize_interval_phase(raw_phase, is_active),
        "current_interval": current_interval,
        "total_intervals": total_intervals,
    }


# ---------------------- Web-Routen ----------------------
# /dashboard, /sic, /iic, /simple und /interval werden von BasicWebGUI.Backend registriert.

@app.before_request
def restrict_config_changes_to_localhost():
    if request.path not in LOCAL_ONLY_PATHS or ALLOW_REMOTE_CONFIG:
        return None
    if request.remote_addr in ("127.0.0.1", "::1"):
        return None
    return jsonify({
        "ok": False,
        "success": False,
        "message": "Konfigurationsänderungen sind nur direkt am x-ski erlaubt.",
        "error": "Konfigurationsänderungen sind nur direkt am x-ski erlaubt.",
    }), 403


def _profile_saved():
    # Profil-Formular hat x-ski.json geändert -> wie «Konfiguration neu laden»
    apply_runtime_reload()


app.register_blueprint(create_profile_blueprint(cfg_manager, on_saved=_profile_saved,
                                                allow_remote=ALLOW_REMOTE_CONFIG))


@app.route("/header")
def header():
    active = request.args.get("active", "")
    u = config.get("user", {})
    return render_template("partials/header.html", user=u, active=active,
                           show_route=settings.skier_mode_requested, mode=MODE or settings.load_mode)


@app.route("/config")
def config_page():
    return render_template("config.html")


# ---------------------- Strecke (GPX) ----------------------

class RouteState:
    """Aktive Strecke und Abschnitt [section_start_m, section_end_m]. Gefahren wird ab dem Moment,
    in dem die Strecke im Training aktiv wird (start_distance_m = Distanz des virtuellen Skifahrers)."""

    def __init__(self):
        self._lock = Lock()
        self.route: Route = None
        self.file_name = ""
        self.start_distance_m = None
        self.section_start_m = 0.0
        self.section_end_m = 0.0

    def select(self, file_name: str, start_km=None, end_km=None) -> Route:
        path = resolve_route_file(ROUTES_DIR, file_name)
        if path is None:
            raise ValueError(f"Strecke '{file_name}' nicht gefunden (Ordner {ROUTES_DIR}).")
        route = Route.from_gpx(path)
        start_m, end_m = route.section(start_km, end_km)
        with self._lock:
            self.route = route
            self.file_name = path.name
            self.section_start_m, self.section_end_m = start_m, end_m
            self.start_distance_m = None  # Start beim nächsten Regelzyklus
        part = "" if (start_m == 0 and end_m == route.length_m) else \
            f", Abschnitt km {start_m / 1000:.1f}–{end_m / 1000:.1f}"
        print(f"🗺️ Strecke geladen: {route.name} ({route.length_m / 1000:.1f} km, ↑{route.elevation_gain_m:.0f} m{part})")
        return route

    def clear(self):
        with self._lock:
            self.route = None
            self.file_name = ""
            self.start_distance_m = None

    def position(self, skier_distance_m: float):
        """Position auf der Strecke für die aktuelle Distanz des Skifahrers, oder (None, None)."""
        with self._lock:
            if self.route is None:
                return None, None
            if self.start_distance_m is None:
                self.start_distance_m = skier_distance_m
            return self.route, self.route.section_position(
                self.section_start_m, self.section_end_m, skier_distance_m - self.start_distance_m)


route_state = RouteState()


class TechniqueState:
    """Gewählte Technik im Skifahrer-Modus: "auto" (nach Steigung), "dp" (Double Poling) oder "diagonal"."""
    VALID = ("auto", "dp", "diagonal")
    LABELS = {"auto": "Auto", "dp": "Double Poling", "diagonal": "Diagonal"}

    def __init__(self):
        self._lock = Lock()
        self._value = "auto"

    def get(self) -> str:
        with self._lock:
            return self._value

    def set(self, value: str) -> str:
        if value not in self.VALID:
            raise ValueError(f"Unbekannte Technik '{value}' (erlaubt: auto, dp, diagonal)")
        with self._lock:
            if value != self._value:
                print(f"🎿 Technik-Wahl: {self.LABELS[value]}")
            self._value = value
        return value


technique_state = TechniqueState()


@app.route("/api/technique", methods=["GET", "POST"])
def api_technique():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            technique_state.set(str(data.get("technique", "")))
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400
    return jsonify({"ok": True, "technique": technique_state.get(),
                    "available": settings.skier_mode_requested,
                    "arm_share": settings.diagonal_arm_share})


def create_traccar_tracker(s: Settings):
    if not s.traccar_enabled:
        return None
    try:
        return create_tracker(s.traccar_protocol, url=s.traccar_url, host=s.traccar_host, port=s.traccar_port,
                              device_id=s.traccar_device_id, interval_s=s.traccar_interval_s)
    except Exception as e:
        print(f"⚠️ Traccar deaktiviert: {e}")
        return None


traccar_tracker = create_traccar_tracker(settings)
if settings.route_file:
    try:
        route_state.select(settings.route_file, known_args.route_start_km, known_args.route_end_km)
    except Exception as e:
        print(f"⚠️ Strecke aus der Konfiguration nicht ladbar: {e}")


@app.route("/route")
def route_page():
    return render_template("route.html")


@app.route("/strecke")
def route_dual_page():
    return render_template("multi_view_route.html")


@app.route("/api/routes", methods=["GET"])
def api_routes():
    return jsonify({
        "files": list_route_files(ROUTES_DIR),
        "active": route_state.file_name,
        "load_mode": "skier" if settings.skier_mode_available else "profile",
        "slope_per_intensity_pct": settings.slope_per_intensity_pct,
    })


@app.route("/api/route", methods=["GET"])
def api_route():
    route = route_state.route
    if route is None:
        return jsonify({"active": False}), 200
    payload = route.to_geojson_payload()
    payload.update({"active": True, "file": route_state.file_name, "slope_factor": settings.route_slope_factor,
                    "section_start_m": round(route_state.section_start_m, 1),
                    "section_end_m": round(route_state.section_end_m, 1)})
    return jsonify(payload)


@app.route("/api/route/select", methods=["POST"])
def api_route_select():
    try:
        data = request.get_json(force=True) or {}
        route_state.select(str(data.get("name", "")), data.get("start_km"), data.get("end_km"))
        return api_route()
    except Exception as e:
        return jsonify({"active": False, "message": str(e)}), 400


@app.route("/api/route/clear", methods=["POST"])
def api_route_clear():
    route_state.clear()
    return jsonify({"active": False})


@app.route("/dual")
def dual_page():
    return render_template("multi_view_sic.html")


@app.route("/dual_iic")
def dual_iic_page():
    if ACTIVE_CONTROLLER_NAME != "iic":
        return (
            "Dual-IIC ist nur verfügbar, wenn der Intervall-Controller aktiv ist. "
            "Bitte x-ski.py mit --controller iic starten.",
            400,
        )
    return render_template("multi_view_iic.html")


@app.route("/api/user", methods=["GET"])
def api_user():
    u = config.get("user", {})
    return jsonify({
        "firstname": u.get("firstname", ""),
        "lastname": u.get("lastname", ""),
        "birthdate": u.get("birthdate", ""),
        "club": u.get("club", ""),
        "email": u.get("email", ""),
        "max_hr_bpm": safe_float(u.get("max_hr_bpm", 0), 0.0),
        "ftp_w": safe_float(u.get("ftp_w", 0), 0.0)
    })


@app.route("/api/config/list", methods=["GET"])
def api_config_list():
    try:
        return jsonify(cfg_manager.list_files())
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@app.route("/api/config/get", methods=["GET"])
def api_config_get():
    try:
        name = request.args.get("name", "")
        return jsonify(cfg_manager.get(name))
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@app.route("/api/config/save", methods=["POST"])
def api_config_save():
    try:
        data = request.get_json(force=True)
        name = data.get("name", "")
        content = data.get("content", "")
        return jsonify(cfg_manager.save(name, content))
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@app.route("/api/config/activate", methods=["POST"])
def api_config_activate():
    try:
        data = request.get_json(force=True)
        name = data.get("name", "")
        return jsonify(cfg_manager.activate(name))
    except Exception as e:
        return jsonify({"message": str(e)}), 400


@app.route("/api/training_targets", methods=["GET"])
def api_training_targets():
    return jsonify(settings.training_targets)


@app.route("/api/reload_config", methods=["POST"])
def api_reload_config():
    try:
        result = apply_runtime_reload()
        return jsonify({
            "ok": True,
            "message": "Konfiguration erfolgreich neu geladen",
            "config_source": str(config_path) if config_path else None,
            "max_hr_bpm": settings.max_hr_bpm,
            "ftp_w": settings.ftp_w,
            "simple_initial_power_pct": settings.simple_initial_power_pct,
            "training_targets": settings.training_targets,
            "controller_status": get_controller_status(),
            "reload_result": result
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "message": f"Reload fehlgeschlagen: {e}"
        }), 400


@app.route("/page_ready", methods=["POST"])
def page_ready():
    global page_loaded
    with page_lock:
        page_loaded = True
    return jsonify({"status": "ok"})


@app.route("/api/dashboard_config", methods=["GET"])
def api_dashboard_config():
    s = settings
    target_torque_curve = build_target_torque_curve_absolute(
        total_length_mm=MAX_TRAVEL_MM,
        swing_start_mm=s.swing_start_mm,
        swing_end_mm=s.swing_end_mm,
        min_torque_pct_value=s.min_torque_pct,
        current_intensity_value=current_gui_intensity,
        max_torque_limit_value=s.max_torque_pct,
        smooth_window=1,
    )
    return jsonify({
        "max_travel_mm": MAX_TRAVEL_MM,
        "load_mode": "skier" if s.skier_mode_available else "profile",
        "max_torque_pct": s.max_torque_pct,
        "max_hr_bpm": s.max_hr_bpm,
        "ftp_w": s.ftp_w,
        "simple_initial_power_pct": s.simple_initial_power_pct,
        "training_targets": s.training_targets,
        "controller_status": get_controller_status(),
        "markers": {
            "swing_start_mm": s.swing_start_mm,
            "max_torque_start_mm": s.max_torque_start_mm,
            "max_torque_end_mm": s.max_torque_end_mm,
            "swing_end_mm": s.swing_end_mm
        },
        "target_torque": {
            "x": list(range(0, MAX_TRAVEL_MM + 1)),
            "y": target_torque_curve.tolist()
        }
    })


# ---------------------- Training ----------------------

class StatusLog:
    """Statusmeldungen ans WebGUI nur bei Änderung senden. Unveränderte Meldungen werden
    höchstens alle REPEAT_S Sekunden wiederholt, damit neu geöffnete Seiten sie auch sehen."""
    REPEAT_S = 1.0

    def __init__(self, target: Scope):
        self._target = target
        self._last_message = None
        self._last_sent = 0.0

    def __call__(self, message: str):
        now = time.monotonic()
        if message != self._last_message or now - self._last_sent >= self.REPEAT_S:
            self._target.log_message(message)
            self._last_message = message
            self._last_sent = now


class LoopTimer:
    """Misst die tatsächliche Frequenz der Regelschleife und gibt sie periodisch aus."""
    REPORT_INTERVAL_S = 30.0
    SLOW_CYCLE_WARN_S = 0.3

    def __init__(self):
        self._last_warning = 0.0
        self._window_start = time.monotonic()
        self._last_tick = None
        self._count = 0
        self._max_dt = 0.0

    def tick(self) -> bool:
        """Gibt True zurück, wenn gerade ein Bericht ausgegeben wurde."""
        now = time.monotonic()
        if self._last_tick is not None:
            dt = now - self._last_tick
            self._max_dt = max(self._max_dt, dt)
            # Lange Aussetzer sofort melden (Watchdog-Grenze des Drive: 1 s)
            if dt > self.SLOW_CYCLE_WARN_S and now - self._last_warning >= 1.0:
                print(f"⚠️ Langsamer Regelzyklus: {dt * 1000:.0f} ms")
                self._last_warning = now
        self._last_tick = now
        self._count += 1

        elapsed = now - self._window_start
        if elapsed >= self.REPORT_INTERVAL_S:
            print(f"⏱️ Regelschleife: {self._count / elapsed:.0f} Hz, max. Zykluszeit {self._max_dt * 1000:.0f} ms")
            self._window_start = now
            self._count = 0
            self._max_dt = 0.0
            return True
        return False


class ThermalMonitor:
    """Auslastung von Motor (Pr 04.019) und Bremswiderstand (Pr 10.039) laut Drive. Bei 100 % greift der
    Schutz des Drive (Strom reduziert bzw. Abschaltung). Ab THERMAL_WARN_PCT wird sofort gewarnt."""
    WARN_REPEAT_S = 30.0

    def __init__(self, log_message):
        self._log = log_message
        self.motor_pct = None
        self.brake_pct = None
        self.motor_peak = 0.0
        self.brake_peak = 0.0
        self._last_warning = 0.0

    def update(self, motor_pct, brake_pct):
        self.motor_pct, self.brake_pct = motor_pct, brake_pct
        self.motor_peak = max(self.motor_peak, motor_pct or 0.0)
        self.brake_peak = max(self.brake_peak, brake_pct or 0.0)
        hot = [(name, v) for name, v in (("Motor", motor_pct), ("Bremswiderstand", brake_pct))
               if v is not None and v >= THERMAL_WARN_PCT]
        now = time.monotonic()
        if hot and now - self._last_warning >= self.WARN_REPEAT_S:
            self._last_warning = now
            text = ", ".join(f"{name} {v:.0f} %" for name, v in hot)
            print(f"⚠️ Hohe Auslastung: {text} – bei 100 % reduziert der Drive die Kraft oder schaltet ab")
            self._log(f"⚠️ Hohe Auslastung: {text} – etwas lockerer ziehen")

    def report(self):
        if self.motor_pct is None and self.brake_pct is None:
            return
        fmt = lambda v: "–" if v is None else f"{v:.0f} %"
        print(f"🌡️ Auslastung: Motor {fmt(self.motor_pct)} (max {self.motor_peak:.0f} %), "
              f"Bremswiderstand {fmt(self.brake_pct)} (max {self.brake_peak:.0f} %)")


class SimulationDiagnostics:
    """Sammelt Werte für die periodische Konsolenausgabe: Spitzen-Seilgeschwindigkeit aus Position
    und Drehzahlregister (Plausibilisierung) sowie Schätzwerte des Motor-Nenndrehmoments."""

    def __init__(self, dist_per_rev_mm: float):
        self._rpm_to_m_s = dist_per_rev_mm / 1000.0 / 60.0
        self._torque_estimates = deque(maxlen=500)
        self._reset_window()

    def _reset_window(self):
        self.peak_rope_m_s_position = 0.0
        self.peak_rope_m_s_register = 0.0

    def add(self, rope_speed_m_s, speed_register, active_power_w, torque_pct, min_torque_pct, drum_radius_m):
        """speed_register: Drehzahlregister [rpm] oder None, wenn in diesem Zyklus nicht gelesen."""
        self.peak_rope_m_s_position = max(self.peak_rope_m_s_position, rope_speed_m_s)
        if speed_register is not None:
            self.peak_rope_m_s_register = max(self.peak_rope_m_s_register, -speed_register * self._rpm_to_m_s)

        # Nur kräftige, schnelle Züge sind für die Schätzung aussagekräftig
        if rope_speed_m_s > 0.5 and active_power_w > 30 and torque_pct > min_torque_pct + 10:
            est = estimate_rated_torque_nm(active_power_w, torque_pct, rope_speed_m_s, drum_radius_m)
            if est is not None:
                self._torque_estimates.append(est)

    def report(self, skier: VirtualSkier, terrain: Terrain, force_planner=None):
        print(f"🎿 Virtueller Skifahrer: {skier.speed_m_s * 3.6:.1f} km/h, Steigung {terrain.slope_percent:+.1f} %, "
              f"Distanz {skier.distance_m:.0f} m")
        if force_planner is not None:
            print(f"   Stosskraft: {force_planner.peak_force_n:.0f} N (Ziel {force_planner.target_force_n:.0f} N), "
                  f"Rhythmus {force_planner.cycle_s:.2f} s / Stoss {force_planner.push_s:.2f} s")
        print(f"   Spitzen-Seilgeschwindigkeit: aus Position {self.peak_rope_m_s_position:.2f} m/s, "
              f"aus Drehzahlregister (1×/s gelesen, daher meist tiefer) {self.peak_rope_m_s_register:.2f} m/s")
        if self._torque_estimates:
            print(f"   Geschätztes Motor-Nenndrehmoment: {statistics.median(self._torque_estimates):.2f} Nm "
                  f"(Median aus {len(self._torque_estimates)} Werten, Richtwert – Typenschild ist massgebend)")
        self._reset_window()


@dataclass
class TrainingSession:
    file_stamp: str
    records: list = field(default_factory=list)
    stopped_by_user: bool = False
    fit: FitRecorder = field(default_factory=FitRecorder)
    title: str = "x-ski Indoor"
    technique_seconds: dict = field(default_factory=dict)


# Laufendes Training: Start, Pause und Stop-Entscheid (save: None = normal speichern, False = verwerfen)
session_state = {"started_at": None, "save": None, "paused": False, "paused_since": None, "paused_total": 0.0,
                 "resume_at": None}
session_lock = Lock()


def session_resume_if_due(now: float = None) -> bool:
    """Countdown nach «Weiter» abgelaufen? Dann Pause beenden: Antrieb frei, Uhr und Intervall laufen weiter."""
    st = session_state
    now = time.time() if now is None else now
    with session_lock:
        if not (st["paused"] and st["resume_at"] and now >= st["resume_at"]):
            return False
        st["paused_total"] += now - (st["paused_since"] or now)
        st.update(paused=False, paused_since=None, resume_at=None)
    if hasattr(active_ic, "resume"):
        active_ic.resume()
    print(f"▶️ Weiter nach Pause (Pausen gesamt {st['paused_total'] / 60:.1f} min)")
    if scope is not None:
        scope.log_message("✅ Training läuft")
    return True


def session_active_elapsed(now: float = None) -> float:
    """Trainingszeit ohne Pausen [s]."""
    st = session_state
    if st["started_at"] is None:
        return 0.0
    now = time.time() if now is None else now
    paused = st["paused_total"] + ((now - st["paused_since"]) if st["paused"] and st["paused_since"] else 0.0)
    return max(0.0, now - st["started_at"] - paused)


def send_rower_metrics(analyzer: StrokeAnalyzer, session_started_at: float, *,
                       stroke_rate_spm, power_w, hr_bpm, running, avg_power_w=None):
    if avg_power_w is None:
        avg_power_w = analyzer.avg_power_w if analyzer.stroke_count else 0

    ble_manager.update_rower_metrics(
        stroke_rate_spm=float(stroke_rate_spm),
        stroke_count=analyzer.stroke_count,
        total_distance_m=float(analyzer.total_distance_m),
        pace_s_per_500=int(analyzer.last_pace_s500),
        avg_pace_s_per_500=int(round(analyzer.avg_pace_s500)) if analyzer.stroke_count else 0,
        power_w=int(round(power_w)),
        avg_power_w=int(round(avg_power_w)),
        hr_bpm=int(hr_bpm) if hr_bpm else 0,
        elapsed_s=int(session_active_elapsed()),
        running=bool(running),
    )


def wait_for_page():
    global page_loaded

    if known_args.no_browser:
        with page_lock:
            page_loaded = True
        print("Browser-Start deaktiviert (--no-browser).")
    elif known_args.no_open:
        print("Browser ist bereits offen (--no-open).")
    else:
        webbrowser.open(START_PAGE)

    print("🔁 Warte auf WebGUI-Start ...")
    while not page_loaded:
        time.sleep(0.1)
    print("✅ WebGUI geladen – starte Log")


def current_terrain(s: Settings, intensity_pct: float, skier_mode: bool, route_pos: RoutePosition = None) -> Terrain:
    """Steigung, in dieser Reihenfolge:
    1) Strecke (GPX) × route_slope_factor; im Skifahrer-Modus verschieben die +/- Tasten die
       Steigung zusätzlich (100 % = Strecke wie sie ist)
    2) Intervalldatei, falls dort angegeben
    3) Skifahrer-Modus: aus der Intensität (100 % = Grundsteigung); Profil-Modus: Grundsteigung"""
    if route_pos is not None:
        slope = route_pos.slope_percent * s.route_slope_factor
        if skier_mode:
            slope = intensity_to_slope_percent(intensity_pct, slope, s.slope_per_intensity_pct)
        return Terrain(slope_percent=float(slope), mu=float(s.mu))

    slope = None
    get_slope = getattr(active_ic, "getSlopePercent", None)
    if callable(get_slope):
        slope = get_slope()
    if slope is None:
        if skier_mode:
            slope = intensity_to_slope_percent(intensity_pct, s.slope_percent, s.slope_per_intensity_pct)
        else:
            slope = s.slope_percent
    return Terrain(slope_percent=float(slope), mu=float(s.mu))


def force_terrain(s: Settings, terrain: Terrain) -> Terrain:
    """Gelände für die Stosskraft am Seil: echte Steigung, aber eigene Gleitreibung (Fahrgefühl)."""
    return Terrain(slope_percent=terrain.slope_percent, mu=s.feel_mu)


def effective_technique(choice: str, slope_percent: float, previous: str, threshold_percent: float,
                        hysteresis_percent: float) -> str:
    """Auto: Diagonal ab der Schwelle, zurück auf Double Poling erst unter Schwelle minus Hysterese."""
    if choice in ("dp", "diagonal"):
        return choice
    if slope_percent >= threshold_percent:
        return "diagonal"
    if slope_percent < threshold_percent - hysteresis_percent:
        return "dp"
    return previous


def technique_factors(s: Settings, technique: str):
    """(Anteil der Arme an der Stosskraft, Faktor auf die Vortriebsleistung).
    Diagonal: die Arme bringen nur diagonal_arm_share des Vortriebs auf; der Rest ist ein fiktiver
    Beinabstoss, der die gemessene Armleistung auf die Gesamtleistung hochrechnet (1 / Armanteil)."""
    if technique == "diagonal":
        return s.diagonal_arm_share, 1.0 / s.diagonal_arm_share
    return 1.0, 1.0


def prepare_drive(drv: DriveM751, s: Settings, *, swing_length: float, dist_per_rev: float,
                  start_torque_pct: float, start_speed_rpm: float, log=None) -> dict:
    """Antrieb vorbereiten (Strombegrenzung, Motorschutz, STO, Endlage) und freigeben.
    Gibt die Positionen in Encoder-Inkrementen zurück (65536 pro Umdrehung)."""
    log = log or scope.log_message
    drv.wait_until_ready()
    drv.set_enabled(False)
    drv.set_torque(0)
    drv.set_speed(0)
    drv.set_forward_direction(0)
    drv.set_watchdog_enabled(False)
    drv.set_current_limit(s.current_limit)
    # Bei Motor-Überlast (Pr 04.019 = 100 %) Strom begrenzen statt mitten im Stoss abschalten
    mode = drv.set_thermal_protection_mode(DriveM751.THERMAL_MODE_MOTOR_LIMIT)
    if mode == DriveM751.THERMAL_MODE_MOTOR_LIMIT:
        print("🌡️ Motorschutz: Strom begrenzen statt abschalten (Pr 04.016 = 1)")
    else:
        print(f"⚠️ Pr 04.016 konnte nicht gesetzt werden (gelesen: {mode}) – Motorschutz schaltet bei Überlast ab")

    log("Bitte Seil 50 cm herausziehen, dann Sicherheitsschalter auslösen")
    drv.wait_for_sto_off()
    drv.set_forward_limit_enabled(False)
    drv.wait_for_sto_on()
    log("Bitte langsam zum oberem Anschlag führen")

    drv.calibrate_end_position(s.current_limit, s.min_torque_calib_pct, s.min_speed_calib)

    # Positionen in Encoder-Inkrementen (65536 pro Umdrehung)
    pole_offset = round((s.top_position - s.pole_length) / dist_per_rev * 65536)
    zero_offset = round(SOFT_ZERO_OFFSET_MM / dist_per_rev * 65536)
    abs_zero_position = drv.read_position()
    if abs_zero_position is None:
        raise RuntimeError("Position nach der Kalibrierung nicht lesbar – Training wird abgebrochen.")
    pole_zero_position = abs_zero_position - pole_offset
    soft_zero_position = abs_zero_position - zero_offset
    end_swing_position = pole_zero_position - round(swing_length / dist_per_rev * 65536)

    drv.wait_for_sto_on()
    log("✅ System bereit")

    drv.set_forward_limit_enabled(True)
    drv.set_forward_direction(1)
    drv.set_torque(start_torque_pct)
    drv.set_speed(start_speed_rpm)
    drv.set_watchdog_enabled(True)
    drv.set_enabled(True)
    return {"abs_zero": abs_zero_position, "pole_zero": pole_zero_position,
            "soft_zero": soft_zero_position, "end_swing": end_swing_position}


def run_training(drv: DriveM751) -> TrainingSession:
    global current_gui_intensity

    ic = active_ic
    s = settings
    status = StatusLog(scope)

    scope.log_message("❌ Warte bis Drive bereit")
    time.sleep(2)

    # Lastmodell wird für die ganze Session festgelegt
    skier_mode = s.skier_mode_available
    if s.skier_mode_requested and not skier_mode:
        print("⚠️ Streckensimulation angefordert, aber simulation.motor_rated_torque_nm ist 0 – "
              "verwende Profil-Modus.")
        scope.log_message("⚠️ Streckensimulation braucht das Motor-Nenndrehmoment – Belastungsprofil aktiv")
    print(f"Lastmodell dieser Session: {'Streckensimulation' if skier_mode else 'Profil'}")

    # Geometrie wird zu Trainingsbeginn festgelegt (Kalibrierung basiert darauf)
    swing_start_mm = int(s.swing_start_mm)
    swing_end_mm = int(s.swing_end_mm)
    swing_length = float(s.swing_length)
    dist_per_rev = s.dist_per_rev

    print(f"Montagehöhe / Anzeigeachse: 0..{MAX_TRAVEL_MM} mm")
    print(f"Schwungbeginn: {swing_start_mm} mm")
    print(f"Max-Drehmoment Start (Legacy-Marker): {int(s.max_torque_start_mm)} mm")
    print(f"Max-Drehmoment Ende (Legacy-Marker): {int(s.max_torque_end_mm)} mm")
    print(f"Schwungende: {swing_end_mm} mm")
    print(f"Max torque limit: {s.max_torque_pct}")
    print_settings_summary()

    f_push = build_force_profile_absolute(
        total_length_mm=MAX_TRAVEL_MM,
        swing_start_mm=swing_start_mm,
        swing_end_mm=swing_end_mm,
        min_torque_value=0.0,
        max_torque_value=100.0,
        smooth_window=1,
    )

    geo = prepare_drive(drv, s, swing_length=swing_length, dist_per_rev=dist_per_rev, start_torque_pct=s.min_torque_pct,
                        start_speed_rpm=s.pull_speed)
    abs_zero_position, pole_zero_position = geo["abs_zero"], geo["pole_zero"]
    soft_zero_position, end_swing_position = geo["soft_zero"], geo["end_swing"]

    session = TrainingSession(file_stamp=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    session.title = strava_title(skier_mode)
    analyzer = StrokeAnalyzer(swing_start_mm=swing_start_mm, swing_end_mm=swing_end_mm)
    loop_timer = LoopTimer()
    skier = VirtualSkier(mass_kg=s.system_mass_kg, cda_m2=s.cda_m2, air_density_kg_m3=s.air_density_kg_m3)
    # Mittelwert der Profilform im Schwungbereich (für die Umrechnung Kraftstoss -> Spitzenkraft)
    profile_mean = float(np.mean(f_push[swing_start_mm:swing_end_mm + 1])) / 100.0
    force_planner = StrokeForcePlanner(
        profile_mean=profile_mean,
        force_scale=s.force_scale,
        max_force_n=s.max_rope_force_n,
        max_step_n=s.max_force_step_n,
    )
    rope_speed_estimator = RopeSpeedEstimator(dist_per_rev_mm=dist_per_rev, alpha=s.rope_speed_alpha)
    diagnostics = SimulationDiagnostics(dist_per_rev_mm=dist_per_rev)
    thermal = ThermalMonitor(scope.log_message)
    last_position = abs_zero_position
    last_speed_register_check = 0.0
    last_fit_sample = 0.0
    last_clock_publish = 0.0
    speed_ref_rpm = s.pull_speed     # beim Start an den Antrieb geschickt (prepare_drive)
    fit_power_sum, fit_power_n = 0.0, 0
    last_thermal_check = 0.0
    last_model_t = None
    last_route_publish = 0.0
    route_finished_announced = False
    terrain = Terrain(slope_percent=s.slope_percent, mu=s.mu)
    # Startwert der Stosskraft (Widerstand im Stand); baut sich über max_step_n pro Stoss auf
    force_planner.update(skier.resistance_force_n(0.0, force_terrain(s, terrain)))
    technique = "dp"

    first_pull_detected = False
    session_started_at = None
    ftms_last_push_monotonic = 0.0
    current_hr = 0

    ble_manager.reset_rower_session()

    while drv.hardware_enabled():
        if loop_timer.tick():
            diagnostics.report(skier, terrain, force_planner if skier_mode else None)
            thermal.report()
        drv.service_watchdog()
        just_started_clock = False
        s = settings  # min/max-Torque, Zonen, Schnee und Steigung wirken live nach einem Reload

        intensity = float(ic.getIntensity())
        current_gui_intensity = intensity
        ic_torque = max(0.0, min(intensity, float(s.max_torque_pct)))

        position_read = drv.read_position()
        # Bei einem Lesefehler die letzte gültige Position weiterverwenden
        actual_position = position_read if position_read is not None else last_position
        last_position = actual_position
        # In der Pause ist der Antrieb aus (kein Drehmoment, Seil frei); «Weiter» gibt ihn nach dem
        # Countdown wieder frei – der Rückzug spannt dann das Seil
        session_resume_if_due()
        drv.update_enabled(actual_position <= soft_zero_position and not session_state["paused"])

        power = drv.read_power()
        now = time.time()

        # Seilgeschwindigkeit aus der Position; für die bestehende Auswertung (Richtung, Zugstart,
        # Scope) in die bisherige Einheit des Drehzahlregisters umgerechnet: rpm, Zug negativ.
        rope_speed = rope_speed_estimator.update(now, position_read)
        speed = -rope_speed / (dist_per_rev / 1000.0) * 60.0

        speed_register = None
        if now - last_thermal_check >= THERMAL_CHECK_INTERVAL_S:
            last_thermal_check = now
            thermal.update(drv.read_motor_overload_pct(), drv.read_brake_resistor_pct())

        if now - last_speed_register_check >= SPEED_REGISTER_CHECK_INTERVAL_S:
            speed_register = drv.read_speed()
            last_speed_register_check = now

        # Uhr / Session beim ersten echten Zug starten – unabhängig vom Vorzeichen
        if not first_pull_detected and abs(speed) > PULL_START_SPEED_THRESHOLD:
            first_pull_detected = True
            just_started_clock = True
            session_started_at = now
            session_state["started_at"] = now

            if hasattr(ic, "active"):
                ic.active = True

            scope.log_message("✅ Training läuft – Uhr wurde automatisch mit dem ersten Zug gestartet")

        current_hr = ant_hr_manager.get_heart_rate()

        denom_real = end_swing_position - pole_zero_position
        if denom_real:
            pos_real_mm = (swing_length / denom_real) * (actual_position - pole_zero_position)
        else:
            pos_real_mm = 0.0
        pos_real_mm = max(0.0, min(pos_real_mm, swing_length))

        pos_mm = max(0.0, min(float(swing_start_mm) + pos_real_mm, float(MAX_TRAVEL_MM)))

        active_power = abs(power) if power < 0 else 0.0
        route, route_pos = route_state.position(skier.distance_m)
        terrain = current_terrain(s, intensity, skier_mode, route_pos)
        if route_pos is not None:
            if route_pos.finished and not route_finished_announced:
                route_finished_announced = True
                scope.log_message(f"🏁 Ziel erreicht: {route.name} ({route.length_m / 1000:.1f} km)")
                print(f"🏁 Ziel erreicht: {route.name}")
            elif not route_pos.finished:
                route_finished_announced = False
            if now - last_route_publish >= ROUTE_PUBLISH_INTERVAL_S:
                last_route_publish = now
                if traccar_tracker is not None and session_started_at is not None:
                    # Nur speichern – Senden und Drosselung (interval_s) laufen im eigenen Thread
                    traccar_tracker.update(TrackerFix(
                        timestamp=now, lat=route_pos.lat, lon=route_pos.lon, altitude_m=route_pos.elevation_m,
                        speed_kmh=skier.speed_m_s * 3.6, course_deg=route_pos.bearing_deg,
                    ))
                Backend().publish("route_position", {
                    "distance_m": round(route_pos.distance_m, 1),
                    "length_m": round(route.length_m, 1),
                    "section_start_m": round(route_state.section_start_m, 1),
                    "section_end_m": round(route_state.section_end_m, 1),
                    "lat": route_pos.lat,
                    "lon": route_pos.lon,
                    "elevation_m": round(route_pos.elevation_m, 1),
                    "route_slope_percent": round(route_pos.slope_percent, 1),
                    "slope_percent": round(terrain.slope_percent, 1),
                    "bearing_deg": round(route_pos.bearing_deg, 1),
                    "speed_kmh": round(skier.speed_m_s * 3.6, 1),
                    "finished": route_pos.finished,
                    "technique": technique,
                    "technique_choice": technique_state.get(),
                    "diagonal_hint": technique == "dp" and terrain.slope_percent >= s.diagonal_from_slope_percent,
                    "elapsed_s": int(session_active_elapsed(now)),
                    "paused": session_state["paused"],
                })
        dt_model = (now - last_model_t) if last_model_t is not None else 0.0
        last_model_t = now

        # Positionsabhängige Bremskurve; die Stärke kommt im Skifahrer-Modus aus dem virtuellen
        # Skifahrer (einmal pro Stoss festgelegt), im Profil-Modus aus der Intensität.
        # Das Tempo des Skifahrers folgt in beiden Modi aus der gemessenen Leistung am Seil.
        # Die Stosskraft wirkt nur beim Ziehen (Seil läuft nach unten). Beim Rückzug – die Hände gehen
        # wieder hoch und durchlaufen denselben Positionsbereich – zieht der Motor nur mit der Rückzugskraft.
        idx = max(0, min(int(round(pos_mm)), len(f_push) - 1))
        pulling = rope_speed > PULL_DETECT_M_S
        # Pause: Antrieb aus (siehe oben), keine Stosskraft; Uhr, Strecke und Aufzeichnung stehen
        paused = session_state["paused"]
        stroke_share = f_push[idx] / 100.0 if pulling and not paused else 0.0
        base_pct = s.min_torque_pct if pulling else s.recovery_torque_pct
        if skier_mode:
            peak_pct = force_to_torque_pct(force_planner.peak_force_n, s.drum_radius_m, s.motor_rated_torque_nm)
            act_torque_pct = round(base_pct + peak_pct * stroke_share, 1)
            record_intensity = intensity
        else:
            act_torque_pct = round(base_pct + ic_torque * stroke_share)
            record_intensity = ic_torque
        # Seilleistung -> Vortrieb auf Schnee (power_scale aus dem Abgleich mit GPS-Läufen)
        if skier_mode:
            new_technique = effective_technique(technique_state.get(), terrain.slope_percent, technique,
                                                s.diagonal_from_slope_percent, s.diagonal_hysteresis_percent)
            if new_technique != technique:
                print(f"🎿 Technik: {TechniqueState.LABELS[new_technique]} (Steigung {terrain.slope_percent:+.1f} %)")
            technique = new_technique
        else:
            technique = "dp"
        arm_share, leg_boost = technique_factors(s, technique)
        if paused:
            skier.speed_m_s = 0.0   # in der Pause steht der Skifahrer
        else:
            skier.step(dt_model, terrain, propulsive_power_w=active_power * s.power_scale * leg_boost)

        act_torque_pct = max(0, min(act_torque_pct, s.max_torque_pct))
        drv.update_torque(act_torque_pct)
        if s.pull_speed != speed_ref_rpm:
            # Rückzugs-Drehzahlgrenze im Profil geändert -> sofort an den Antrieb
            drv.set_speed(s.pull_speed)
            print(f"🔁 Rückzugs-Drehzahlgrenze jetzt {s.pull_speed:.0f} rpm")
            speed_ref_rpm = s.pull_speed
        diagnostics.add(rope_speed, speed_register, active_power, act_torque_pct, s.min_torque_pct, s.drum_radius_m)

        cycle_complete = analyzer.add_sample(now, pos_mm, speed, power, act_torque_pct, record_intensity)
        act_power = analyzer.last_active_power_w

        scope.evaluateValue(np.array(
            [pos_mm, speed, act_torque_pct, act_power, current_hr, analyzer.last_cadence_spm], dtype=float
        ))

        if cycle_complete:
            stroke = analyzer.close_cycle(now, current_hr, s.training_targets, skier.distance_m)
            if skier_mode and not paused:
                # Stosskraft für den nächsten Stoss aus Tempo, Gelände und gemessenem Rhythmus
                # Kraftgefühl mit eigener Gleitreibung (feel_mu), Tempo mit der gemessenen (user.mu)
                force_planner.update(
                    skier.resistance_force_n(skier.speed_m_s, force_terrain(s, terrain)) * arm_share,
                    cycle_s=stroke.duration_s if stroke else None,
                    push_s=stroke.push_duration_s if stroke else None,
                )
            if stroke is not None and not paused:
                if session_started_at is not None:
                    send_rower_metrics(
                        analyzer, session_started_at,
                        stroke_rate_spm=stroke.cadence_spm,
                        power_w=stroke.mean_power_w,
                        hr_bpm=current_hr,
                        running=getattr(ic, "active", False),
                    )

                scope.set_summary_values(
                    current_hr,
                    stroke.mean_power_w,
                    stroke.cadence_spm,
                    stroke.distance_m,
                    stroke.total_distance_m,
                    swing_efficiency_pct=stroke.swing_efficiency_pct,
                    mean_target_torque_pct=stroke.mean_target_torque_pct,
                    torque_power_index=stroke.torque_power_index,
                    push_phase_energy_j=stroke.push_phase_energy_j,
                    reference_push_energy_j=stroke.reference_push_energy_j,
                    push_phase_utilization_pct=stroke.push_phase_utilization_pct,
                    reference_zone_key=stroke.reference_zone_key,
                    reference_spm=stroke.reference_spm,
                    reference_power_w=stroke.reference_power_w,
                    virtual_speed_kmh=round(skier.speed_m_s * 3.6, 1),
                    slope_percent=round(terrain.slope_percent, 1),
                    load_mode="skier" if skier_mode else "profile",
                )
                session.records.append(stroke.to_record())

        if getattr(ic, "stop_requested", False):
            scope.log_message("⛔ Training wurde gestoppt")
            print("Training wurde über Webinterface gestoppt.")
            if session_started_at is not None:
                send_rower_metrics(analyzer, session_started_at,
                                   stroke_rate_spm=0.0, power_w=0, hr_bpm=current_hr, running=False)
            session.stopped_by_user = True
            return session

        if getattr(ic, "active", False):
            if not just_started_clock:
                if not first_pull_detected:
                    status("✅ Training bereit – Uhr startet automatisch mit dem ersten Zug")
                else:
                    status("Pause – Antrieb aus, Uhr angehalten" if paused else "✅ Training läuft")
        else:
            status("⏳ Warte auf Trainingsstart")

        now_mono = time.monotonic()
        if session_started_at is not None and (now_mono - ftms_last_push_monotonic) >= FTMS_PUSH_INTERVAL_S:
            send_rower_metrics(
                analyzer, session_started_at,
                stroke_rate_spm=analyzer.last_cadence_spm,
                power_w=act_power or analyzer.last_power_w,
                avg_power_w=analyzer.avg_power_w if analyzer.stroke_count else act_power,
                hr_bpm=current_hr,
                running=getattr(ic, "active", False),
            )
            ftms_last_push_monotonic = now_mono

        # FIT: ab dem ersten Zug jede Sekunde ein Messwert; Runden pro Intervallblock bzw. pro km.
        # GPS (virtuelle Position) nur in der Streckensimulation.
        fit_power_sum += active_power
        fit_power_n += 1
        if session_started_at is not None and now - last_clock_publish >= 1.0:
            # Trainingsuhr (ohne Pausen) für die Anzeigen
            last_clock_publish = now
            Backend().publish("session_clock", {"elapsed_s": round(session_active_elapsed(now), 1),
                                                "paused": session_state["paused"]})
        if session_started_at is not None and not paused and now - last_fit_sample >= 1.0:
            last_fit_sample = now
            if ACTIVE_CONTROLLER_NAME == "iic" and hasattr(ic, "_block_navigation_state"):
                lap_key, lap_trigger = ic._block_navigation_state().get("block_index"), 0
            else:
                lap_key, lap_trigger = int(skier.distance_m // 1000), 2
            session.fit.add(FitSample(
                t=now, distance_m=skier.distance_m, speed_m_s=skier.speed_m_s,
                heart_rate=current_hr or None, cadence=analyzer.last_cadence_spm or None,
                power=fit_power_sum / fit_power_n if fit_power_n else None,
                lat=route_pos.lat if route_pos is not None else None,
                lon=route_pos.lon if route_pos is not None else None,
                altitude_m=route_pos.elevation_m if route_pos is not None else None,
                grade_percent=terrain.slope_percent if route_pos is not None else None,
            ), lap_key=lap_key, lap_trigger=lap_trigger)
            fit_power_sum, fit_power_n = 0.0, 0
            if skier_mode:
                session.technique_seconds[technique] = session.technique_seconds.get(technique, 0) + 1

        if LOOP_SLEEP_S > 0:
            time.sleep(LOOP_SLEEP_S)

    print("Training gestoppt oder abgebrochen")
    if session_started_at is not None:
        send_rower_metrics(analyzer, session_started_at,
                           stroke_rate_spm=0.0, power_w=0, hr_bpm=0, running=False)
    return session


# ---------------------- Seilzug-Kalibrierung ----------------------

calibration = None                     # RopeCalibration, sobald der Antrieb bereit ist
calibration_status = {"message": "Antrieb wird vorbereitet …", "drive_ready": False, "finished": False}
calibration_exit = None                # threading.Event: «Zum Startmenü» gedrückt


@app.route("/kalibrierung")
def calibration_page():
    return render_template("calibration.html")


@app.route("/api/calibration", methods=["GET", "POST"])
def api_calibration():
    cal = calibration
    if request.method == "GET":
        data = cal.summary() if cal is not None else {}
        data.update(calibration_status, mode=MODE)
        return jsonify(data)
    action = str((request.get_json(silent=True) or {}).get("action", ""))
    stars = (request.get_json(silent=True) or {}).get("stars")
    if action == "exit":
        if cal is not None:
            cal.stop_requested = True
        if calibration_exit is not None:
            calibration_exit.set()
        return jsonify({"ok": True})
    if cal is None:
        return jsonify({"ok": False, "message": "Die Kalibrierung läuft noch nicht."}), 409
    if action == "rate":
        cal.rate(stars)
    elif action == "skip":
        cal.skip()
    elif action == "repeat":
        cal.repeat()
    elif action == "apply":
        if not cal.result:
            return jsonify({"ok": False, "message": "Noch kein Ergebnis."}), 409
        r = cal.result["recommended"]
        try:
            update_active_profile(cfg_manager, {"control": {
                "min_torque_pct": r["pull_pct"], "recovery_torque_pct": r["recovery_pct"], "pull_speed": r["speed_rpm"]}})
            apply_runtime_reload()
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400
        cal.applied = True
        print(f"🧪 Kalibrierung übernommen: Grundzug {r['pull_pct']:.0f} %, Rückzug {r['recovery_pct']:.0f} %, "
              f"Drehzahlgrenze {r['speed_rpm']:.0f} rpm")
    else:
        return jsonify({"ok": False, "message": f"Unbekannte Aktion '{action}'"}), 400
    return jsonify({"ok": True})


def run_calibration(drv: DriveM751):
    """Geführter Seilzug-Test: der Ablauf (RopeCalibration) gibt Drehmoment und Drehzahlgrenze vor,
    die Schleife misst die Seilposition. Grenzen: Grundzug/Rückzug ≤ 40 %, Drehzahl ≤ 3000 rpm."""
    global calibration
    s = settings
    swing_start_mm, swing_end_mm = int(s.swing_start_mm), int(s.swing_end_mm)
    swing_length, dist_per_rev = float(s.swing_length), s.dist_per_rev
    m_per_count = dist_per_rev / 1000.0 / 65536

    def log(message):
        calibration_status["message"] = message
        print(f"🧪 {message}")

    f_push = build_force_profile_absolute(total_length_mm=MAX_TRAVEL_MM, swing_start_mm=swing_start_mm,
                                          swing_end_mm=swing_end_mm, min_torque_value=0.0,
                                          max_torque_value=100.0, smooth_window=1)
    cal = RopeCalibration(rated_torque_nm=s.motor_rated_torque_nm, drum_radius_m=s.drum_radius_m,
                          dist_per_rev_mm=dist_per_rev, current_pull_pct=s.min_torque_pct,
                          current_recovery_pct=s.recovery_torque_pct, current_speed_rpm=s.pull_speed)
    first_torque, first_speed = cal.command(False, 0.0)
    geo = prepare_drive(drv, s, swing_length=swing_length, dist_per_rev=dist_per_rev,
                        start_torque_pct=first_torque, start_speed_rpm=first_speed, log=log)
    calibration = cal
    calibration_status.update(drive_ready=True, message="")
    print(f"🧪 Seilzug-Kalibrierung gestartet (aktuell: Grundzug {s.min_torque_pct:.0f} %, "
          f"Rückzug {s.recovery_torque_pct:.0f} %, Drehzahlgrenze {s.pull_speed:.0f} rpm)")

    loop_timer = LoopTimer()
    thermal = ThermalMonitor(log)
    estimator = RopeSpeedEstimator(dist_per_rev_mm=dist_per_rev, alpha=s.rope_speed_alpha)
    last_position, last_speed_rpm, last_thermal_check = geo["abs_zero"], first_speed, 0.0
    denom = geo["end_swing"] - geo["pole_zero"]
    last_step_title = None

    while drv.hardware_enabled() and not cal.stop_requested:
        if loop_timer.tick():
            thermal.report()
        drv.service_watchdog()
        position_read = drv.read_position()
        position = position_read if position_read is not None else last_position
        last_position = position
        drv.update_enabled(position <= geo["soft_zero"])
        now = time.time()
        rope_speed = estimator.update(now, position_read)

        pos_real_mm = (swing_length / denom) * (position - geo["pole_zero"]) if denom else 0.0
        pos_mm = max(0.0, min(float(swing_start_mm) + max(0.0, min(pos_real_mm, swing_length)), float(MAX_TRAVEL_MM)))
        idx = max(0, min(int(round(pos_mm)), len(f_push) - 1))
        pulling = rope_speed > PULL_DETECT_M_S
        torque_pct, speed_rpm = cal.command(pulling, f_push[idx] / 100.0 if pulling else 0.0)
        drv.update_torque(max(0.0, min(torque_pct, s.max_torque_pct)))
        if speed_rpm != last_speed_rpm:
            drv.set_speed(speed_rpm)
            last_speed_rpm = speed_rpm
        if position_read is not None:
            cal.add(now, (geo["abs_zero"] - position_read) * m_per_count)

        if now - last_thermal_check >= THERMAL_CHECK_INTERVAL_S:
            last_thermal_check = now
            thermal.update(drv.read_motor_overload_pct(), drv.read_brake_resistor_pct())

        st = cal.step
        title = st.title if st is not None else "fertig"
        if title != last_step_title:
            last_step_title = title
            print(f"🧪 Schritt: {title} (Drehmoment Rückzug/Grundzug {cal.command(False, 0)[0]:.0f}/"
                  f"{cal.command(True, 0)[0]:.0f} %, Drehzahlgrenze {cal.command(False, 0)[1]:.0f} rpm)")
            if st is None and cal.result:
                r = cal.result["recommended"]
                print(f"🧪 Ergebnis: Grundzug {r['pull_pct']:.0f} %, Rückzug {r['recovery_pct']:.0f} %, "
                      f"Drehzahlgrenze {r['speed_rpm']:.0f} rpm | Masse {cal.mass_kg:.2f} kg, "
                      f"Reibung {cal.friction_n:.1f} N, nötiger Rückzug {cal.required_recovery_pct} %")

    if not cal.stop_requested:
        log("Antrieb aus (Sicherheitsschalter) – Kalibrierung beendet.")
    save_calibration_report(cal)


def save_calibration_report(cal: RopeCalibration):
    """Messwerte der Kalibrierung als JSON in logs/ ablegen (für spätere Auswertung)."""
    try:
        logs = PROJECT_DIR / "logs"
        logs.mkdir(exist_ok=True)
        path = logs / f"seilzug_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        path.write_text(json.dumps(cal.report(), indent=1, ensure_ascii=False, default=float), encoding="utf-8")
        print(f"🧪 Messwerte gespeichert: {path}")
    except Exception as e:
        print(f"⚠️ Messwerte der Kalibrierung nicht gespeichert: {e}")


def calibration_thread():
    global calibration_exit
    calibration_exit = Event()
    try:
        wait_for_page()
        run_calibration(drive)
    except Exception:
        traceback.print_exc()
        calibration_status["message"] = "❌ Fehler in der Kalibrierung – Antrieb wurde abgeschaltet"
    finally:
        drive.shutdown()
        calibration_status["finished"] = True
    calibration_exit.wait()
    if browser_alive["gone"]:
        print("🛑 x-ski beendet.", flush=True)
        os._exit(0)
    restart_launcher()


def restart_launcher():
    """Zurück ins Startmenü: dieser Prozess wird durch launcher.py ersetzt (gleiches Log, Port 5000 wird frei)."""
    argv = [sys.executable, "-u", str(SCRIPT_DIR / "launcher.py"), "--no-browser", "--host", known_args.host]
    if known_args.config_path:
        argv += ["--config", known_args.config_path]
    print("🏠 Zurück zum Startmenü", flush=True)
    time.sleep(0.5)   # Antwort an die Webseite noch ausliefern
    os.chdir(SCRIPT_DIR)
    os.closerange(3, 4096)
    os.execv(argv[0], argv)


def strava_title(skier_mode: bool) -> str:
    """Titel für Strava, z.B. «x-ski Indoor – Sertig Classic 21k (km 8.1–20.3)»."""
    route = route_state.route
    if skier_mode and route is not None:
        name = route.name.replace("_", " ")
        s0, s1 = route_state.section_start_m, route_state.section_end_m
        if s0 > 0 or s1 < route.length_m - 1:
            name += f" (km {s0 / 1000:.1f}–{s1 / 1000:.1f})"
        return f"x-ski Indoor – {name}"
    return "x-ski Indoor – Intervall" if ACTIVE_CONTROLLER_NAME == "iic" else "x-ski Indoor – Belastungsprofil"


def strava_description(session: TrainingSession) -> str:
    samples = session.fit.samples
    dur = samples[-1].t - samples[0].t if len(samples) > 1 else 0
    powers = [x.power for x in samples if x.power]
    hrs = [x.heart_rate for x in samples if x.heart_rate]
    lines = ["Double-Poling-Ergometer x-ski (Indoor).",
             f"{samples[-1].distance_m / 1000:.2f} km virtuell in {int(dur // 60)}:{int(dur % 60):02d} min"
             + (f" · Ø {sum(powers) / len(powers):.0f} W am Seil" if powers else "")
             + (f" · Ø {sum(hrs) / len(hrs):.0f} bpm" if hrs else "")]
    tech = session.technique_seconds
    if tech and sum(tech.values()) > 0:
        total = sum(tech.values())
        lines.append(f"Technik: Double Poling {tech.get('dp', 0) / total:.0%}, Diagonal {tech.get('diagonal', 0) / total:.0%}")
    return "\n".join(lines)


def finish_session(session: TrainingSession):
    """TCX schreiben und E-Mail senden. Fehler werden gemeldet, aber nicht weitergereicht."""
    s = settings
    attachments = []
    TRAININGS_DIR.mkdir(parents=True, exist_ok=True)

    fit_ok = False
    if session.fit.samples:
        fit_path = TRAININGS_DIR / f"skiErg_{session.file_stamp}.fit"
        try:
            session.fit.write(str(fit_path))
            attachments.append(fit_path)
            fit_ok = True
            print(f"💾 FIT-Datei gespeichert als: {fit_path} ({len(session.fit.samples)} s, {len(session.fit.laps)} Runden)")
        except Exception as e:
            print(f"❌ FIT-Export fehlgeschlagen: {e}")
            scope.log_message(f"❌ FIT-Export fehlgeschlagen: {e}")

    if session.records:
        tcx_path = TRAININGS_DIR / f"skiErg_{session.file_stamp}.tcx"
        try:
            TRAININGS_DIR.mkdir(parents=True, exist_ok=True)
            write_tcx(session.records, filename=str(tcx_path), sport_note="SkiErg Intervalltraining")
            attachments.append(tcx_path)
            note = ("Anbei die FIT-Datei (für Strava: wird als Skilanglauf erkannt) und die TCX-Datei als Reserve."
                    if fit_ok else "Anbei die TCX-Datei.")
        except Exception as e:
            print(f"❌ TCX-Export fehlgeschlagen: {e}")
            scope.log_message(f"❌ TCX-Export fehlgeschlagen: {e}")
            note = "Die TCX-Datei konnte leider nicht erstellt werden."
    else:
        scope.log_message("ℹ️ Keine Trainingsdaten – TCX wird nicht erzeugt.")
        print("Hinweis: Keine records vorhanden – TCX-Erzeugung übersprungen.")
        note = "Es wurden keine Zyklen aufgezeichnet, daher keine TCX-Datei."

    strava_line = ""
    strava_ok = False
    if fit_ok and s.strava_auto_upload and not s.strava_athlete_id:
        strava_line = "Strava: Dieses Profil ist nicht mit Strava verbunden (Profil → Mit Strava verbinden)."
        print(f"⚠️ {strava_line}")
    elif fit_ok and s.strava_auto_upload:
        try:
            result = strava_client.upload_activity(fit_path, name=session.title, athlete_id=s.strava_athlete_id,
                                                   description=strava_description(session),
                                                   sport_type="NordicSki", trainer=True,
                                                   external_id=f"x-ski-{session.file_stamp}")
            if result.get("duplicate"):
                strava_line = f"Strava: Diese Einheit war bereits hochgeladen. {result.get('url') or ''}".strip()
                strava_ok = True
            elif result.get("url"):
                strava_line = f"Strava: {result['url']}"
                strava_ok = True
            else:
                strava_line = "Strava: Upload angenommen, wird noch verarbeitet."
            print(f"🟧 {strava_line}")
            scope.log_message(f"🟧 {strava_line}")
        except Exception as e:
            strava_line = f"Strava-Upload fehlgeschlagen: {e}"
            print(f"❌ {strava_line}")
            scope.log_message(f"❌ {strava_line}")

    if strava_ok:
        # Training ist sicher bei Strava – die E-Mail ist nur die Reserve, wenn der Upload nicht klappt
        print("📧 Keine E-Mail: Das Training ist bereits bei Strava.")
        return

    if not s.email:
        print("Hinweis: Keine E-Mail-Adresse konfiguriert – es wird keine E-Mail gesendet.")
        return

    body_text = "\n".join([
        f"Hallo {s.firstname},",
        "",
        "dein Training wurde beendet.",
        note,
        *([strava_line] if strava_line else []),
        f"Verein: {s.club}",
        f"Geburtsdatum: {'.'.join(reversed(s.birthdate.split('-'))) if s.birthdate.count('-') == 2 else s.birthdate}",
    ]) + "\n"

    try:
        send_training_email(
            to_address=s.email,
            subject=f"X-Ski Training abgeschlossen – {s.firstname} {s.lastname}",
            body=body_text,
            attachments=attachments
        )
    except Exception as e:
        print(f"❌ E-Mail-Versand fehlgeschlagen: {e}")
        scope.log_message(f"❌ E-Mail-Versand fehlgeschlagen: {e}")




@app.route("/api/alive")
def api_alive():
    return jsonify({"ok": True})


@app.route("/api/session", methods=["GET"])
def api_session():
    started = session_state["started_at"]
    return jsonify({"started": started is not None, "short_s": SHORT_SESSION_S, "mode": MODE,
                    "elapsed_s": round(session_active_elapsed()), "paused": session_state["paused"],
                    "paused_s": round(time.time() - session_state["paused_since"]) if session_state["paused"] else 0,
                    "resume_in_s": round(max(0.0, session_state["resume_at"] - time.time()), 1)
                    if session_state["resume_at"] else None})


@app.route("/api/session/pause", methods=["POST"])
def api_session_pause():
    """Pause/Weiter: Antrieb aus, Uhr angehalten, Strecke und Aufzeichnung stehen; im Intervall
    bleibt auch der Ablauf stehen."""
    st = session_state
    if st["started_at"] is None:
        return jsonify({"ok": False, "message": "Das Training hat noch nicht begonnen."}), 409
    want = bool((request.get_json(silent=True) or {}).get("paused", not st["paused"]))
    now = time.time()
    with session_lock:
        if want and not st["paused"]:
            st.update(paused=True, paused_since=now, resume_at=None)
            started_pause = True
        elif want and st["resume_at"]:
            st["resume_at"] = None          # Countdown abgebrochen – Pause geht weiter
            started_pause = False
        elif not want and st["paused"] and not st["resume_at"]:
            st["resume_at"] = now + RESUME_COUNTDOWN_S
            started_pause = False
            print(f"▶️ Weiter in {RESUME_COUNTDOWN_S:.0f} s – Antrieb wird danach freigegeben")
        else:
            started_pause = False
    if started_pause:
        if hasattr(active_ic, "pause"):
            active_ic.pause()
        print(f"⏸ Pause bei {session_active_elapsed(now) / 60:.1f} min – Antrieb aus")
        scope.log_message("Pause – Antrieb aus, Uhr angehalten")
    return jsonify({"ok": True, "paused": st["paused"], "elapsed_s": round(session_active_elapsed(now))})


@app.route("/api/session/end", methods=["POST"])
def api_session_end():
    """Training beenden (wie Stop), mit Entscheid «speichern» bzw. «verwerfen». Danach geht x-ski
    zurück ins Startmenü; der Antrieb wird vorher vollständig abgeschaltet."""
    data = request.get_json(silent=True) or {}
    session_state["save"] = bool(data.get("save", True))
    request_training_stop()
    return jsonify({"ok": True, "save": session_state["save"]})


def request_training_stop():
    """Trainingsschleife beenden (Belastungsprofil und Intervall: beide prüfen stop_requested)."""
    active_ic.stop()
    active_ic.stop_requested = True


# ---------------------- Browser geschlossen -> x-ski beenden ----------------------
browser_alive = {"until": time.monotonic() + BROWSER_TIMEOUT_S, "gone": False}


@app.before_request
def browser_seen():
    grace = STRAVA_CONNECT_GRACE_S if request.path == "/strava/connect" else BROWSER_TIMEOUT_S
    browser_alive["until"] = max(browser_alive["until"], time.monotonic() + grace)


def watch_browser():
    """Kein Lebenszeichen mehr vom Browser: Training wie mit Stop beenden (ab 5 min speichern, kürzere
    verwerfen – fragen geht ohne Browser nicht), Antrieb abschalten und x-ski ganz beenden."""
    while time.monotonic() <= browser_alive["until"]:
        time.sleep(5)
    browser_alive["gone"] = True
    print("🛑 Browser geschlossen (kein Lebenszeichen) – Training wird beendet und x-ski geschlossen.", flush=True)
    if MODE == "calib":
        if calibration is not None:
            calibration.stop_requested = True
        if calibration_exit is not None:
            calibration_exit.set()
    else:
        if session_state["save"] is None:
            session_state["save"] = session_active_elapsed() >= SHORT_SESSION_S
        request_training_stop()
    # Falls der Ablauf hängt (z.B. wartet noch auf den Sicherheitsschalter): spätestens nach 5 min hart beenden
    # (Speichern und Strava-Upload brauchen bis ~1 min)
    time.sleep(300)
    print("🛑 x-ski wird beendet (Training hat nicht rechtzeitig gestoppt).", flush=True)
    try:
        drive.shutdown()
    finally:
        os._exit(0)


def training_thread():
    session = None
    try:
        wait_for_page()
        session = run_training(drive)
    except Exception:
        traceback.print_exc()
        try:
            scope.log_message("❌ Fehler im Trainingsablauf – Antrieb wurde abgeschaltet")
        except Exception:
            pass
    finally:
        # Antrieb in jedem Fall abschalten – auch bei Fehlern oder Stopp über das Webinterface
        drive.shutdown()

    if session is not None and session.stopped_by_user:
        try:
            if session_state["save"] is False:
                print("🗑️ Training wird nicht gespeichert " + ("(kürzer als 5 min, Browser geschlossen)."
                                                              if browser_alive["gone"] else "(auf Wunsch verworfen)."))
            else:
                finish_session(session)
        finally:
            # Antrieb ist aus – zurück ins Startmenü, dort ist ein komplett neuer Start möglich.
            # War der Browser zu, wird x-ski ganz beendet.
            if browser_alive["gone"]:
                print("🛑 x-ski beendet.", flush=True)
                os._exit(0)
            restart_launcher()


if __name__ == "__main__":
    drive = DriveM751(
        host=settings.drive_host,
        port=settings.drive_port,
        unit_id=settings.drive_unit_id,
        max_torque_pct=settings.max_torque_pct,
    )
    scope = Scope(
        max_hr_bpm=settings.max_hr_bpm,
        ftp_w=settings.ftp_w,
        training_targets=settings.training_targets
    )

    t = Thread(target=calibration_thread if MODE == "calib" else training_thread, name="training-thread", daemon=True)
    t.start()
    Thread(target=watch_browser, name="browser-watch", daemon=True).start()

    app.run(host=known_args.host, debug=False)
