# Utils/profile_page.py – Formular für das Userprofil (statt JSON-Editor), für Startmenü und x-ski

import json
import os
import re
from typing import Callable, Optional

from flask import Blueprint, jsonify, redirect, render_template, request

from Utils import machine, strava_client

from Utils.settings import Settings

MACHINE_GROUP = "Maschine"
FEEL_GROUP = "Fahrgefühl (Fortgeschritten)"
SENSOR_GROUP = "Sensoren und Verbindungen"

# (Abschnitt, Schlüssel, Bezeichnung, Typ, min, max, Schritt, Einheit, Hilfetext, Gruppe)
PROFILE_FIELDS = [
    ("user", "firstname", "Vorname", "text", None, None, None, "", "", "Athlet"),
    ("user", "lastname", "Nachname", "text", None, None, None, "", "", "Athlet"),
    ("user", "birthdate", "Geburtsdatum", "date", None, None, None, "", "", "Athlet"),
    ("user", "club", "Verein", "text", None, None, None, "", "", "Athlet"),
    ("user", "email", "E-Mail für die Trainingsdatei", "email", None, None, None, "",
     "Die Trainingsdatei (FIT) wird an diese Adresse geschickt, wenn der Strava-Upload nicht klappt oder aus ist.", "Athlet"),
    ("user", "weight_kg", "Körpergewicht", "number", 30, 150, 0.5, "kg", "", "Athlet"),
    ("user", "max_hr_bpm", "Maximaler Puls", "number", 100, 230, 1, "bpm", "Grundlage der Pulszonen.", "Athlet"),
    ("user", "ftp_w", "FTP", "number", 50, 500, 1, "W", "Grundlage der Leistungszonen.", "Athlet"),

    ("control", "simple_initial_power_pct", "Startwert Belastungsprofil", "number", 5, 180, 5, "%",
     "Intensität beim Start im Modus «Belastungsprofil». In der Streckensimulation startet es immer bei 100 (Strecke wie sie ist).",
     "Training"),
    ("control", "recovery_torque_pct", "Rückzugskraft", "number", 5, 60, 1, "%",
     "Zieht das Seil nach dem Stoss zurück und hält es gespannt. 10 % ≈ 11 N, 20 % ≈ 22 N. Tiefer = sanfter, "
     "aber langsamer. Standard 30 %. Die Kalibrierung schlägt höchstens 40 % vor.",
     "Training"),
    ("control", "pull_speed", "Rückzugs-Geschwindigkeit", "number", 500, 3000, 100, "rpm",
     "Höchste Drehzahl beim Zurückholen. 3000 rpm ≈ 8 m/s Seilgeschwindigkeit.", "Training"),
    ("control", "min_torque_pct", "Grundzug beim Stoss", "number", 2, 60, 1, "%",
     "Widerstand, gegen den du immer ziehst – auch bergab. 20 % ≈ 22 N.", "Training"),
    ("control", "end_pull_torque_pct", "Gegenkraft am Zugende", "number", 0, 40, 1, "%",
     "Im letzten Drittel des Zugs steigt der Grundzug bis auf diesen Wert, damit das Seil beim Abbremsen der "
     "Hände gespannt bleibt. Wirkt nur, wenn die Stosskraft dort kleiner ist. 15 % ≈ 16 N.", "Training"),
    ("strava", "auto_upload", "Nach dem Training automatisch zu Strava hochladen", "checkbox", None, None, None, "",
     "Als Skilanglauf mit Titel und Beschreibung (ohne Indoor-Markierung, damit Strava Karte und Höhenmeter zeigt). Dafür muss x-ski unten mit Strava verbunden sein.", "Strava"),
    ("chat", "enabled", "Start und Ende der Streckensimulation im Tracking-Chat melden", "checkbox", None, None, None, "",
     "Beim ersten Zug geht «Training gestartet. Folge mir unter: …» mit dem Live-Link raus, am Schluss «Training beendet.». "
     "Der Absender ist dein Name.", "Live-Tracking"),
    ("user", "mu", "Gleitreibung Ski", "number", 0.01, 0.1, 0.001, "",
     "Kleiner = besser gleitender Ski. Gemessen auf deinen GPS-Läufen mit Wachsski: 0.037.", "Ski & Technik"),
    ("simulation", "equipment_kg", "Ausrüstung", "number", 0, 20, 0.5, "kg",
     "Ski, Stöcke und Kleidung – kommt zum Körpergewicht dazu.", "Ski & Technik"),
    ("simulation", "downhill_feel_floor", "Widerstand bergab", "number", 0, 1, 0.05, "",
     "Wie viel Widerstand bergab mindestens bleibt, als Anteil der Gleitreibung in der Ebene. Wirkt nur bergab "
     "(flach und bergauf nicht). 0.5 = halb so viel wie flach, 1 = gleich viel. Standard 0.5.", "Ski & Technik"),
    ("user", "diagonal_from_slope_percent", "Wechsel auf Diagonal ab", "number", 1, 20, 0.5, "%",
     "Technik «Auto»: ab dieser Steigung Diagonalschritt.", "Ski & Technik"),
    ("user", "diagonal_hysteresis_percent", "Zurück auf Double Poling", "number", 0, 5, 0.5, "% darunter",
     "Erst wenn die Steigung um so viel tiefer ist, wird wieder auf Double Poling gewechselt.", "Ski & Technik"),

    # Fahrgefühl der Streckensimulation (abgestimmt mit GPS-Läufen – nur in kleinen Schritten ändern)
    ("simulation", "power_scale", "Tempo-Faktor", "number", 1.0, 4.0, 0.05, "",
     "Wie schnell deine Seilleistung den virtuellen Skifahrer macht. Höher = schneller bei gleicher Kraft. "
     "Abgestimmt mit Sertig Classic: 2.6.", FEEL_GROUP),
    ("simulation", "feel_mu", "Reibung fürs Kraftgefühl", "number", 0.005, 0.05, 0.001, "",
     "Gleitreibung, aus der die Kraft am Seil berechnet wird (getrennt von der Ski-Gleitreibung fürs Tempo). "
     "Höher = schwerer ziehen überall. Standard 0.02.", FEEL_GROUP),
    ("simulation", "diagonal_power_factor", "Vortrieb im Diagonalschritt", "number", 0.5, 1.5, 0.05, "",
     "Wirkung des Beinabstosses: 1 = gleich viel Vortrieb pro Watt wie Double Poling. Standard 0.9.", FEEL_GROUP),
    ("simulation", "diagonal_arm_share", "Armanteil im Diagonalschritt", "number", 0.2, 0.8, 0.05, "",
     "Anteil der Kraft, den die Arme im Diagonalschritt tragen (Seilzug wird entsprechend leichter). Standard 0.4.",
     FEEL_GROUP),
    ("simulation", "cda_m2", "Luftwiderstand (CdA)", "number", 0.2, 0.8, 0.01, "m²",
     "Stirnfläche × Luftwiderstandsbeiwert. Höher = mehr Bremswirkung bei hohem Tempo. Standard 0.45.", FEEL_GROUP),
    ("simulation", "air_density_kg_m3", "Luftdichte", "number", 0.8, 1.3, 0.01, "kg/m³",
     "1.0 entspricht etwa 1800 m ü. M., 1.2 dem Meeresspiegel. Standard 1.0.", FEEL_GROUP),
    ("simulation", "route_slope_factor", "Steigungen verstärken", "number", 0.5, 1.5, 0.05, "",
     "Multipliziert alle Steigungen und Gefälle der Strecke. 1 = wie im GPX.", FEEL_GROUP),
    ("simulation", "max_force_step_n", "Kraftänderung pro Stoss", "number", 5, 60, 1, "N",
     "Wie stark sich die Stosskraft von einem Stoss zum nächsten ändern darf. Kleiner = sanftere Übergänge. "
     "Standard 30 N.", FEEL_GROUP),

    # Sensoren und Verbindungen
    ("ant_hr_sensor", "enabled", "Pulsgurt (ANT+) verwenden", "checkbox", None, None, None, "", "", SENSOR_GROUP),
    ("ant_hr_sensor", "device_id", "Nummer des Pulsgurts", "number", 0, 65535, 1, "",
     "ANT+-Nummer des Gurts. 0 = den ersten gefundenen Gurt nehmen.", SENSOR_GROUP),
    ("mywhoosh_ble", "enabled", "Als Rudergerät für MyWhoosh anbieten (Bluetooth)", "checkbox", None, None, None, "",
     "Wirkt nach einem Neustart von x-ski.", SENSOR_GROUP),
    ("traccar", "enabled", "Position an Traccar senden (Streckensimulation)", "checkbox", None, None, None, "", "",
     SENSOR_GROUP),
    ("traccar", "device_id", "Traccar-Gerät", "text", None, None, None, "", "Name des Geräts, wie in Traccar angelegt.",
     SENSOR_GROUP),
    ("traccar", "interval_s", "Traccar-Takt", "number", 1, 60, 1, "s", "Alle so viele Sekunden eine Position.",
     SENSOR_GROUP),

]

# Maschinendaten (gelten für alle Profile, maschine.json): eigene, passwortgeschützte Seite «Maschine»
# (Utils/machine_page.py), nicht im Profil-Formular.
MACHINE_FIELDS = [
    # Abschnitte «hardware» und «drive»: gelten für die Maschine, nicht für das Profil (maschine.json, siehe Utils/machine.py)
    ("hardware", "pulli_diameter", "Durchmesser der Seiltrommel", "number", 20, 120, 0.5, "mm",
     "Gilt für alle Profile. Bestimmt Kraft und Seilweg – nach dem Wechsel der Pullis anpassen.", MACHINE_GROUP),
    ("hardware", "rope_diameter", "Seildurchmesser", "number", 1, 8, 0.1, "mm", "Gilt für alle Profile.",
     MACHINE_GROUP),
    ("drive", "host", "Adresse des Nidec-Antriebs", "text", None, None, None, "", "Nur Nidec M751 (Modbus TCP).",
     MACHINE_GROUP),
    ("drive", "type", "Antrieb", "select", None, None, None, "",
     "Gilt für alle Profile und wirkt beim nächsten Trainingsstart. Der Delta-Antrieb ist vorbereitet, "
     "aber an der Maschine noch nicht erprobt.", MACHINE_GROUP),
    ("drive", "axes", "Anzahl Motoren", "select", None, None, None, "",
     "Nur Delta. Mit zwei Motoren hat jede Seite ihr eigenes Seil; beide bekommen dieselbe Kraft "
     "(je die Hälfte), die Anzeige zeigt den Mittelwert.", MACHINE_GROUP),
    ("drive", "interface", "Netzwerkanschluss für EtherCAT", "text", None, None, None, "",
     "Nur Delta. Die Delta-Antriebe haben keine IP-Adresse: sie hängen in einer Kette am Netzwerkanschluss des Pi "
     "(Pi → Antrieb 1 IN, Antrieb 1 OUT → Antrieb 2 IN). Standard eth0.", MACHINE_GROUP),
    ("drive", "direction_1", "Drehrichtung Motor 1", "select", None, None, None, "",
     "Nur Delta. Motor 1 ist der Antrieb, der direkt am Pi hängt. Umkehren, wenn der Motor das Seil beim "
     "Kalibrieren abwickelt statt aufwickelt.", MACHINE_GROUP),
    ("drive", "direction_2", "Drehrichtung Motor 2", "select", None, None, None, "",
     "Nur Delta. Motor 2 ist der zweite Antrieb in der Kette.", MACHINE_GROUP),
    ("drive", "left_motor", "Linkes Seil hängt an", "select", None, None, None, "",
     "Nur Delta mit 2 Motoren. Bei jedem Start fordert x-ski auf, das LINKE Seil herauszuziehen, und meldet, "
     "welcher Motor sich bewegt hat. Passt es nicht, hier umstellen oder die Netzwerkkabel tauschen.", MACHINE_GROUP),
    ("drive", "sto_wired", "Sicherheitsschalter (STO) am Delta-Antrieb angeschlossen", "checkbox", None, None, None, "",
     "Aus = Brücke ab Werk im Stecker CN10: nur für den Test auf dem Tisch ohne Seil.", MACHINE_GROUP),
]

# Auswahlfelder: (Wert, Anzeige)
FIELD_OPTIONS = {
    "drive.type": list(machine.DRIVE_TYPES.items()),
    "drive.axes": [(1, "1 Motor"), (2, "2 Motoren (links / rechts)")],
    "drive.direction_1": [(1, "normal"), (-1, "umgekehrt")],
    "drive.direction_2": [(1, "normal"), (-1, "umgekehrt")],
    "drive.left_motor": [(1, "Motor 1 (direkt am Pi)"), (2, "Motor 2")],
}


def _field_meta(fields=None):
    return [dict(section=s, key=k, label=lb, type=t, min=mn, max=mx, step=st, unit=u, help=h, group=g,
                 options=[{"value": v, "label": text} for v, text in FIELD_OPTIONS.get(f"{s}.{k}", [])])
            for s, k, lb, t, mn, mx, st, u, h, g in (PROFILE_FIELDS if fields is None else fields)]


def _parse(field, raw):
    section, key, label, ftype, mn, mx, _, _, _, _ = field
    if ftype == "checkbox":
        return raw in (True, "true", "1", 1, "on")
    if ftype == "select":
        for value, _text in FIELD_OPTIONS[f"{section}.{key}"]:
            if str(raw) == str(value):
                return value
        raise ValueError(f"{label}: ungültige Auswahl.")
    if ftype != "number":
        return str(raw or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label}: bitte eine Zahl eingeben.")
    if (mn is not None and value < mn) or (mx is not None and value > mx):
        raise ValueError(f"{label}: erlaubt sind {mn} bis {mx}.")
    return int(value) if key in ("max_hr_bpm", "ftp_w", "device_id") else value


TEMPLATE_FILE = "x-ski.default.json"  # Vorlage für neue Profile


def profile_label(file_name: str, person: str) -> str:
    """Anzeigename: «Jürg Pargätzi (aktuell)» aus x-ski.aktuell.json."""
    stem = file_name[:-5] if file_name.endswith(".json") else file_name
    stem = stem[len("x-ski."):] if stem.startswith("x-ski.") else stem
    if person:
        return f"{person} ({stem})"
    return stem


def read_active_config(cfg_manager) -> dict:
    path = cfg_manager.ACTIVE_CONFIG_PATH
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(json.dumps(cfg_manager.DEFAULT_CONFIG))


def write_active_config(cfg_manager, raw_cfg: dict):
    """Aktive Konfiguration schreiben; die gleiche Datei in configs/ (das geladene Profil) mitführen."""
    mirror = cfg_manager.list_files().get("active")
    text = json.dumps(raw_cfg, indent=2, ensure_ascii=False) + "\n"
    tmp = cfg_manager.ACTIVE_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, cfg_manager.ACTIVE_CONFIG_PATH)
    if mirror:
        (cfg_manager.CONFIG_DIR / mirror).write_text(text, encoding="utf-8")
    return mirror


def update_active_profile(cfg_manager, updates: dict):
    """Einzelne Werte ins aktive Profil schreiben, z.B. {"control": {"recovery_torque_pct": 12}}.
    Die ganze Konfiguration wird vorher geprüft (ValueError bei ungültigen Werten)."""
    raw_cfg = read_active_config(cfg_manager)
    for section, values in updates.items():
        raw_cfg.setdefault(section, {}).update(values)
    merged = json.loads(json.dumps(cfg_manager.DEFAULT_CONFIG))
    cfg_manager.deep_update(merged, raw_cfg)
    Settings.from_config(merged, {}).validate_geometry()
    return write_active_config(cfg_manager, raw_cfg)


def create_profile_blueprint(cfg_manager, on_saved: Optional[Callable[[], None]] = None,
                             allow_remote: bool = False, hr_manager: Optional[Callable] = None,
                             edit_lock: Optional[Callable[[], Optional[str]]] = None) -> Blueprint:
    """hr_manager: Funktion -> ANTHRManager (oder None) für Pulsgurt-Status und «Pulsgurt suchen».
    edit_lock: Funktion -> Text, wenn das Profil gerade nicht geändert werden darf (Training läuft)."""
    bp = Blueprint("profile", __name__)

    def lock_reason() -> Optional[str]:
        return edit_lock() if edit_lock is not None else None

    # ---------------------- Pulsgurt ----------------------
    @bp.route("/api/hr", methods=["GET"])
    def hr_status():
        mgr = hr_manager() if hr_manager is not None else None
        if mgr is None:
            return jsonify({"available": False, "enabled": False})
        return jsonify({"available": True, **mgr.status()})

    @bp.route("/api/hr/search", methods=["POST"])
    def hr_search():
        denied = local_only()
        if denied:
            return denied
        mgr = hr_manager() if hr_manager is not None else None
        if mgr is None or not mgr.enabled:
            return jsonify({"ok": False, "message": "Pulsgurt ist im Profil ausgeschaltet."}), 409
        mgr.research()
        return jsonify({"ok": True})

    def read_active() -> dict:
        return read_active_config(cfg_manager)

    def write_active(raw_cfg: dict):
        return write_active_config(cfg_manager, raw_cfg)

    def profile_athlete_id():
        return (read_active().get("strava") or {}).get("athlete_id")

    @bp.route("/profil")
    def profile_page():
        return render_template("profil.html")

    # ---------------------- Strava verbinden ----------------------
    @bp.route("/api/strava", methods=["GET"])
    def strava_status():
        try:
            st = strava_client.status(profile_athlete_id())
            st["configured"] = True
        except strava_client.StravaError as e:
            st = {"connected": False, "configured": False, "message": str(e)}
        return jsonify(st)

    @bp.route("/strava/connect")
    def strava_connect():
        denied = local_only()
        if denied:
            return denied
        try:
            return redirect(strava_client.authorize_url(request.host_url.rstrip("/") + "/strava/callback"))
        except strava_client.StravaError as e:
            return render_template("strava_result.html", ok=False, message=str(e))

    @bp.route("/strava/callback")
    def strava_callback():
        if request.args.get("error"):
            return render_template("strava_result.html", ok=False,
                                   message="Der Zugriff wurde bei Strava nicht erlaubt.")
        try:
            tokens = strava_client.exchange_code(request.args.get("code", ""), request.args.get("scope", ""))
        except strava_client.StravaError as e:
            return render_template("strava_result.html", ok=False, message=str(e))
        athlete = tokens.get("athlete") or {}
        raw = read_active()
        raw.setdefault("strava", {}).update(
            athlete_id=athlete.get("id"),
            athlete_name=f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip())
        write_active(raw)
        if on_saved is not None:
            notify_saved()
        print(f"🔗 Strava verbunden: {athlete.get('firstname', '')} {athlete.get('lastname', '')} "
              f"(Konto {athlete.get('id')}) – im geladenen Profil gespeichert")
        return render_template("strava_result.html", ok=True,
                               message=f"x-ski ist mit dem Strava-Konto von {athlete.get('firstname', '')} "
                                       f"{athlete.get('lastname', '')} verbunden.")

    @bp.route("/api/profile", methods=["GET"])
    def get_profile():
        cfg = json.loads(json.dumps(cfg_manager.DEFAULT_CONFIG))
        cfg_manager.deep_update(cfg, read_active())
        for section in machine.MACHINE_SECTIONS:
            cfg[section] = machine.section_config(section, cfg.get(section))
        values = {f"{s}.{k}": cfg.get(s, {}).get(k) for s, k, *_ in PROFILE_FIELDS}
        return jsonify({"fields": _field_meta(), "values": values, "locked": lock_reason()})

    def local_only():
        from Utils.access import can_control
        if not can_control(allow_remote):
            return jsonify({"ok": False, "message": "Profile kann nur das Steuergerät ändern."}), 403
        return None

    def notify_saved() -> str:
        if on_saved is None:
            return ""
        try:
            on_saved()
            return ""
        except Exception as e:
            return f" (nicht übernommen: {e})"

    # ---------------------- Profile (Dateien in configs/) ----------------------
    @bp.route("/api/profiles", methods=["GET"])
    def list_profiles():
        listing = cfg_manager.list_files()
        profiles = []
        for name in listing["files"]:
            try:
                cfg = json.loads((cfg_manager.CONFIG_DIR / name).read_text(encoding="utf-8"))
                user = cfg.get("user", {})
                person = f"{user.get('firstname', '')} {user.get('lastname', '')}".strip()
                strava = bool((cfg.get("strava") or {}).get("athlete_id"))
            except Exception:
                person, strava = "", False
            profiles.append({"file": name, "person": person, "label": profile_label(name, person), "strava": strava})
        return jsonify({"profiles": profiles, "active": listing["active"]})

    @bp.route("/api/profiles/activate", methods=["POST"])
    def activate_profile():
        denied = local_only()
        if denied:
            return denied
        name = str((request.get_json(silent=True) or {}).get("file", ""))
        try:
            cfg_manager.activate(name)
        except (ValueError, FileNotFoundError) as e:
            return jsonify({"ok": False, "message": str(e)}), 400
        note = notify_saved()
        print(f"👤 Profil geladen: {name}{note}")
        return jsonify({"ok": True, "active": name, "message": f"Profil geladen{note}."})

    @bp.route("/api/profiles/new", methods=["POST"])
    def new_profile():
        denied = local_only()
        if denied:
            return denied
        title = str((request.get_json(silent=True) or {}).get("name", "")).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower().replace("ä", "ae").replace("ö", "oe")
                      .replace("ü", "ue").replace("ß", "ss")).strip("-")
        if not slug:
            return jsonify({"ok": False, "message": "Bitte einen Namen eingeben."}), 400
        name = f"x-ski.{slug}.json"
        if (cfg_manager.CONFIG_DIR / name).exists():
            return jsonify({"ok": False, "message": f"Profil «{title}» gibt es schon."}), 400
        # Ausgangspunkt ist die Vorlage (x-ski.default.json) mit allen Maschinen- und Simulationswerten;
        # die Personendaten sind leer, der eingegebene Name wird zum Vornamen.
        template_path = cfg_manager.CONFIG_DIR / TEMPLATE_FILE
        base = json.loads(template_path.read_text(encoding="utf-8")) if template_path.exists() \
            else json.loads(json.dumps(cfg_manager.DEFAULT_CONFIG))
        user = base.setdefault("user", {})
        user.update(firstname=title, lastname="", birthdate="", club="", email="")
        base["strava"] = {"auto_upload": False}   # jedes Profil verbindet sein eigenes Strava-Konto
        cfg_manager.save(name, json.dumps(base, indent=2, ensure_ascii=False) + "\n")
        cfg_manager.activate(name)
        note = notify_saved()
        print(f"👤 Neues Profil: {name}{note}")
        return jsonify({"ok": True, "active": name, "edit": True,
                        "message": f"Profil «{title}» angelegt{note} – bitte Angaben ergänzen."})

    @bp.route("/api/profile", methods=["POST"])
    def save_profile():
        denied = local_only()
        if denied:
            return denied
        reason = lock_reason()
        if reason:
            return jsonify({"ok": False, "message": reason}), 409
        data = request.get_json(silent=True) or {}
        values = data.get("values", {})
        try:
            raw_cfg = read_active()
            for field in PROFILE_FIELDS:
                section, key = field[0], field[1]
                ident = f"{section}.{key}"
                if ident in values:
                    raw_cfg.setdefault(section, {})[key] = _parse(field, values[ident])

            # Gesamte Konfiguration prüfen, bevor etwas geschrieben wird
            merged = json.loads(json.dumps(cfg_manager.DEFAULT_CONFIG))
            cfg_manager.deep_update(merged, raw_cfg)
            Settings.from_config(merged, {}).validate_geometry()
        except ValueError as e:
            return jsonify({"ok": False, "message": str(e)}), 400

        # Ist die aktive Datei gleich einer Datei im Ordner configs/, wird diese mitgeführt,
        # damit die Konfigurationsseite und «Aktivieren» denselben Stand haben.
        mirror = write_active(raw_cfg)

        message = "Profil gespeichert." + notify_saved()
        print(f"👤 {message}")
        return jsonify({"ok": True, "message": message, "mirrored": mirror})

    return bp
