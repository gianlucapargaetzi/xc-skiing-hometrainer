# Test.py – x-ski WebGUI + Training + Konfig-Management mit ConfigManager & BLEManager

import os
import sys
import time
import json
import asyncio
import numpy as np
from pathlib import Path
from datetime import datetime
from time import sleep
from threading import Lock, Thread

import webbrowser
import serial  # falls benötigt
from flask import Flask, jsonify, render_template, request, abort, redirect, url_for
from pyModbusTCP.client import ModbusClient
from pyModbusTCP import utils

from BasicWebGUI import Backend
from IntensityController.IntervallIntensityController import IntervallIntensityController
from IntensityController.SimpleIntensityController import SimpleIntensityController
from ValueHandler.Scope import Scope
from Utils.CustomLogger import Logger
from Utils.double_poling_distance import distance_per_cycle_dynamic, distance_per_cycle
from Utils.tcx_export import write_tcx
from Utils.email_utils import send_training_email

# Konfigurations- & BLE-Manager
from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.ble_manager import BLEManager

# --------------------------- Pfade & Globals ---------------------------
SCRIPT_DIR = Path(__file__).resolve().parent

# --------------------------- CLI: --config optional --------------------
import argparse
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--config", dest="config_path", default=None)
known_args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]

# --------------------------- Config laden ------------------------------
cfg_manager = ConfigManager(
    script_dir=SCRIPT_DIR,
    active_filename="x-ski.json",
    config_dirname="configs",
    default_config=DEFAULT_CONFIG,
    env_var="X_SKI_CONFIG",
)
config, config_path = cfg_manager.load_from_candidates(cli_path=known_args.config_path)

# --------------------------- Globals aus Config ------------------------

def apply_config_globals():
    global pulli_diameter, rope_diameter, top_position, pole_length, swing_length
    global swing_start_max_torque_pml, swing_end_max_torque_pml, dist_par_rev
    global min_torque_calib_pct, min_speed_calib, min_torque_pct, CurrentLimit, pull_speed
    global weight_kg, mu, s_s, slope_percent
    global hr_sensor_address
    global drive_host, drive_port, drive_unitid
    global user_firstname, user_lastname, user_birthdate, user_club, user_email

    pulli_diameter = config["hardware"]["pulli_diameter"]
    rope_diameter  = config["hardware"]["rope_diameter"]
    top_position   = config["hardware"]["top_position"]
    pole_length    = config["hardware"]["pole_length"]
    swing_length   = config["hardware"]["swing_length"]

    swing_start_max_torque_pml = config["swing_torque"]["swing_start_max_torque_pml"]
    swing_end_max_torque_pml   = config["swing_torque"]["swing_end_max_torque_pml"]

    dist_par_rev = round((pulli_diameter + rope_diameter) * 3.14159)

    min_torque_calib_pct = config["control"]["min_torque_calib_pct"]
    min_speed_calib      = config["control"]["min_speed_calib"]
    min_torque_pct       = config["control"]["min_torque_pct"]
    CurrentLimit         = config["control"]["CurrentLimit"]
    pull_speed           = config["control"]["pull_speed"]

    weight_kg     = config["user"]["weight_kg"]
    mu            = config["user"]["mu"]
    s_s           = config["user"]["s_s"]
    slope_percent = config["user"]["slope_percent"]

    user_firstname = config["user"].get("firstname", "")
    user_lastname  = config["user"].get("lastname", "")
    user_birthdate = config["user"].get("birthdate", "")
    user_club      = config["user"].get("club", "")
    user_email     = config["user"].get("email", "")

    hr_sensor_address = config["hr_sensor"]["address"]

    drive_host   = config["drive"]["host"]
    drive_port   = config["drive"]["port"]
    drive_unitid = config["drive"]["unit_id"]

apply_config_globals()

# --------------------------- State (Page Ready) ------------------------
page_loaded = False
page_lock = Lock()

# --------------------------- BLE Manager -------------------------------
# Startet BLE Power Server und HR-Listener in eigenen Threads
ble_manager = BLEManager(hr_sensor_address)

# --------------------------- Modbus Helpers ----------------------------

def uint16_to_int16(uint16):
    if uint16 >= 2**15:
        return uint16 - 2**16
    return uint16

def moving_average_filter(data, n):
    kernel = np.ones(n) / n
    return np.convolve(data, kernel, mode='valid')

def _read1(addr):
    vals = client1.read_holding_registers(addr, 1)
    return vals[0] if vals else None

def DriveReset():
    client1.write_single_register(1032, 1)
    client1.write_single_register(1032, 0)
    client1.write_single_register(1032, 1)

def EnableDisableWatchDog(watchdog):
    client1.write_single_register(642, int(watchdog))

def toggleWatchDog():
    client1.write_single_register(641, 0)
    client1.write_single_register(641, 16384)

def writeMotorCurrentLimit(limit):
    client1.write_single_register(404, int(limit * 10))

def writeTorque(torque):
    client1.write_single_register(407, int(torque * 100))

def writeSpeed(speed):
    client1.write_single_register(117, int(speed * 10))

def DriveEnable(driveenable):
    client1.write_single_register(614, int(driveenable))

def writeForwardDirection(direction):
    client1.write_single_register(629, int(direction))

def EnableDisableForwardLimit(flag):
    client1.write_single_register(1235, int(flag))

def saveForwardLimitSwitchPosition():
    client1.write_single_register(1209, 0)
    sleep(0.1)
    client1.write_single_register(1209, 1)

def driveHealthy():
    v = _read1(1000)
    return v == 1 if v is not None else False

def driveRunning():
    v = _read1(1001)
    return v == 1 if v is not None else False

def readHardwareEnabled():
    v = _read1(628)
    return v == 1 if v is not None else False

def readNormalisedPosition():
    p12 = client1.read_holding_registers(327, 2)
    if not p12:
        return 0
    long_vals = utils.word_list_to_long(p12)
    return long_vals[0] if long_vals else 0

def readSpeed():
    v = _read1(301)
    if v is None:
        return 0.0
    return uint16_to_int16(v) / 10

def readLoad():
    v = _read1(419)
    if v is None:
        return 0.0
    return uint16_to_int16(v) / 10

def readPower():
    v = _read1(502)
    if v is None:
        return 0
    return uint16_to_int16(v)

def wait_for_drive():
    print("Warte auf Drive-Start ...")
    while not driveHealthy():
        print("Drive nicht bereit", end="\r")
        DriveReset()
    print("Drive bereit.")

def wait_for_sto_OFF():
    print("Warte auf STO-Auslösung ...")
    while readHardwareEnabled():
        print("Bitte STO lösen", end="\r")
    print("STO ist aus.")

def wait_for_sto_ON():
    print("Warte auf STO-Einschaltung ...")
    while not readHardwareEnabled():
        print("Bitte STO drücken", end="\r")
    print("STO ist eingeschaltet.")

def calibrate_end_position():
    print("Kalibriere Endposition ...")
    sleep(1)
    DriveEnable(1)
    writeForwardDirection(1)
    writeMotorCurrentLimit(CurrentLimit)
    writeTorque(min_torque_calib_pct)
    writeSpeed(min_speed_calib)
    sleep(0.5)
    while readSpeed() > 0:
        pass
    DriveEnable(0)
    writeForwardDirection(0)
    saveForwardLimitSwitchPosition()
    EnableDisableForwardLimit(1)
    print("Kalibrierung abgeschlossen.")

# --------------------------- Flask App & Routen ------------------------
app = Backend(__name__)

# Header-Fragment (serverseitig gefüllt)
@app.route("/header")
def header():
    active = request.args.get("active", "")
    u = config.get("user", {})
    return render_template("partials/header.html", user=u, active=active)

# User-API
@app.route("/api/user", methods=["GET"])
def api_user():
    u = config.get("user", {})
    return jsonify({
        "firstname": u.get("firstname", ""),
        "lastname":  u.get("lastname", ""),
        "birthdate": u.get("birthdate", ""),
        "club":      u.get("club", ""),
        "email":     u.get("email", "")
    })

# Konfig-Seite
@app.route("/config")
def config_page():
    return render_template("config.html", user=config.get("user", {}), active="config")

# Konfig-Management APIs (per ConfigManager)
@app.route("/api/config/list", methods=["GET"])
def api_config_list():
    return jsonify(cfg_manager.list_files())

@app.route("/api/config/get", methods=["GET"])
def api_config_get():
    name = request.args.get("name", "")
    try:
        return jsonify(cfg_manager.get(name))
    except ValueError as e:
        return abort(400, str(e))
    except FileNotFoundError as e:
        return abort(404, str(e))

@app.route("/api/config/save", methods=["POST"])
def api_config_save():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    content = data.get("content")
    if not isinstance(content, str) or not content:
        return abort(400, "Kein Inhalt")
    try:
        return jsonify(cfg_manager.save(name, content))
    except ValueError as e:
        return abort(400, str(e))

@app.route("/api/config/activate", methods=["POST"])
def api_config_activate():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    try:
        return jsonify(cfg_manager.activate(name))
    except ValueError as e:
        return abort(400, str(e))
    except FileNotFoundError as e:
        return abort(404, str(e))

@app.route("/api/config/reload", methods=["POST"])
def api_config_reload():
    try:
        resp = cfg_manager.reload_active()
        global config
        config = cfg_manager.config
        apply_config_globals()
        return jsonify(resp)
    except FileNotFoundError as e:
        return abort(404, str(e))
    except ValueError as e:
        return abort(400, str(e))

# Dashboard + Root
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/")
def root_redirect():
    return redirect(url_for("dashboard"))

# Signal aus Frontend: Seite bereit
@app.route("/page_ready", methods=["POST"])
def page_ready():
    global page_loaded
    with page_lock:
        page_loaded = True
    return jsonify({"status": "ok"})

# --------------------------- Training Thread ---------------------------

def training_thread():
    global page_loaded

    records = []
    zero_power_start_time = None
    zero_power_duration = 0.0

    # Controller anhand CLI-Arg ("sic" oder "iic")
    controller = sys.argv[1] if len(sys.argv) > 1 else "sic"
    if controller == "iic":
        ic = IntervallIntensityController()
        webbrowser.open("http://localhost:5000/iic")
    else:
        ic = SimpleIntensityController()
        webbrowser.open("http://localhost:5000/sic")

    print("🔁 Warte auf WebGUI-Start ...")
    while not page_loaded:
        time.sleep(0.1)
    print("✅ WebGUI geladen – starte Log")

    scope.log_message("❌ Warte bis Drive bereit")
    sleep(2)

    s = np.linspace(0, 2000, 2000)
    f_push = np.zeros_like(s)
    f_pull = np.zeros_like(s)
    f_push[:swing_start_max_torque_pml] = (1 / swing_start_max_torque_pml * s[:swing_start_max_torque_pml]) * 100
    f_push[swing_start_max_torque_pml:swing_end_max_torque_pml] = 100
    f_push[swing_end_max_torque_pml:] = (-1 / swing_end_max_torque_pml * s[swing_end_max_torque_pml:] + 2) * 100
    f_push[f_push < 0] = 0
    f_pull[:] = f_push[:] * 0.5
    f_push = moving_average_filter(f_push, 100)

    wait_for_drive()
    DriveEnable(0)
    writeTorque(0)
    writeSpeed(0)
    writeForwardDirection(0)
    EnableDisableWatchDog(0)
    writeMotorCurrentLimit(CurrentLimit)

    scope.log_message("Bitte Seil 50 cm herausziehen, dann Sicherheitsschalter auslösen")
    wait_for_sto_OFF()
    EnableDisableForwardLimit(0)
    wait_for_sto_ON()
    scope.log_message("Bitte langsam zum oberem Anschlag führen")

    calibrate_end_position()

    pole_offset = round((top_position - pole_length) / dist_par_rev * 65536)
    zero_offset = round((50) / dist_par_rev * 65536) # Sicherheitssichtung wirk 50mm vom Top entfernt.
    abs_zero_position = readNormalisedPosition()
    pole_zero_position = abs_zero_position - pole_offset
    soft_zero_position = abs_zero_position - zero_offset
    start_max_torque_position = pole_zero_position - round(swing_start_max_torque_pml / dist_par_rev * 65536)
    end_max_torque_position   = pole_zero_position - round(swing_end_max_torque_pml  / dist_par_rev * 65536)
    end_swing_position        = pole_zero_position - round(swing_length             / dist_par_rev * 65536)

    wait_for_sto_ON()
    scope.log_message("✅ Training gestartet")

    EnableDisableForwardLimit(1)
    writeForwardDirection(1)
    writeTorque(min_torque_pct)
    writeSpeed(pull_speed)
    EnableDisableWatchDog(1)
    DriveEnable(1)

    actual_dir = True
    old_dir = True
    sequence_start_time = sequence_end_time = int(datetime.now().timestamp() * 1000)
    sequence_freq = 0
    torque_scale_factor = 0
    act_torque_pct = min_torque_pct
    ic_torque = 0
    speed = 0.0
    act_power = 0
    power = 0
    mean_power = 0.0

    act_power_array = []

    current_time = datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")

    total_distance = 0.0  # Gesamtdistanz

    running = True
    while running:
        toggleWatchDog()
        ic_torque = ic.getIntensity()
        actual_position = readNormalisedPosition()

        # Software Sicherheitsschaltung / Drehmoment wird 50mm vom Top entfernt abgeschaltet
        if actual_position <= soft_zero_position:
            DriveEnable(1)
        else:
            DriveEnable(0)

        speed = readSpeed()
        power = readPower()

        # Negative Leistung ist Zug / Positiv Wickeln
        if power < 0:
            act_power = abs(power)
            act_power_array.append(act_power)
            if zero_power_start_time is not None:
                zero_power_duration += time.time() - zero_power_start_time
                zero_power_start_time = None
        else:
            act_power = 0
            act_power_array.append(act_power)
            if zero_power_start_time is None:
                zero_power_start_time = time.time()

        current_hr = ble_manager.get_heart_rate()

        denom1 = (end_swing_position - abs_zero_position)
        denom2 = (end_swing_position - pole_zero_position)
        pos_rel_zero = (100  / denom1) * (actual_position - abs_zero_position) if denom1 else 0
        pos_rel_pole = (1000 / denom2) * (actual_position - pole_zero_position) if denom2 else 0

        if pos_rel_pole >= 0 and round(pos_rel_pole) < len(f_push):
            torque_scale_factor = f_push[round(pos_rel_pole)]
        else:
            torque_scale_factor = 0

        act_torque_pct = round(min_torque_pct + ((ic_torque * torque_scale_factor / 100)))
        writeTorque(act_torque_pct)

        # Werte an Scope
        arr = np.array([pos_rel_zero, speed, act_torque_pct, act_power, current_hr, sequence_freq])
        scope.evaluateValue(arr)


        actual_dir = speed > 0

        if old_dir and not actual_dir:
            prev_start = sequence_start_time
            current_time = datetime.now()
            sequence_time_stamp = current_time.timestamp()
            sequence_start_time = int(sequence_time_stamp * 1000)
            delta = sequence_start_time - prev_start
            sequence_freq = round(60000 / delta) if delta > 0 else 0

            mean_power = float(np.mean(act_power_array)) if len(act_power_array) else 0.0
            if np.isnan(mean_power):
                mean_power = 0.0

            if sequence_freq > 200 or sequence_freq <= 0:
                sequence_freq = 0

            if sequence_freq > 0 and mean_power > 0:
                # Distanz (einfache Variante)
                distance = distance_per_cycle(mean_power, sequence_freq)
                total_distance += distance

                scope.set_summary_values(current_hr, mean_power, sequence_freq, distance, total_distance)

                record = {
                    "timestamp": current_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+"Z",
                    "sequence_freq": round(sequence_freq/2),   # Strava verdoppelt wieder
                    "power": mean_power,
                    "heart_rate": current_hr,
                    "torque": act_torque_pct,
                    "distance": total_distance
                }
                records.append(record)

            old_dir = actual_dir
            zero_power_duration = 0.0
            act_power_array = []

        elif not old_dir and actual_dir:
            old_dir = actual_dir

        if not ic.active:
            scope.log_message("⛔ Training wurde gestoppt")
            print("Training wurde über Webinterface gestoppt.")

            tcx_filename = f"skiErg_{formatted_time}.tcx"
            attachments = []
            if records:
                write_tcx(records, filename=tcx_filename, sport_note="SkiErg Intervalltraining")
                attachments = [tcx_filename]
            else:
                scope.log_message("ℹ️ Keine Trainingsdaten – TCX wird nicht erzeugt.")
                print("Hinweis: Keine records vorhanden – TCX-Erzeugung übersprungen.")

            # Mail-Body sicher zusammensetzen
            lines = [
                f"Hallo {user_firstname},",
                "",
                "dein Training wurde beendet.",
                "Anbei die TCX-Datei." if attachments else "Es wurden keine Zyklen aufgezeichnet, daher keine TCX-Datei.",
                f"Verein: {user_club}",
                f"Geburtsdatum: {user_birthdate}"
            ]
            body_text = "\n".join(lines) + "\n"

            send_training_email(
                to_address=user_email or "fallback@example.com",
                subject=f"X-Ski Training abgeschlossen – {user_firstname} {user_lastname}",
                body=body_text,
                attachments=attachments
            )

            os._exit(0)
            break
        else:
            scope.log_message("✅ Training läuft")

    DriveEnable(0)
    writeSpeed(0)
    writeTorque(0)
    EnableDisableWatchDog(0)

# --------------------------- main --------------------------------------
if __name__ == '__main__':
    client1 = ModbusClient(host=drive_host, port=drive_port, unit_id=drive_unitid, auto_open=True)
    scope = Scope()

    # Training in separatem Thread
    t = Thread(target=training_thread, name="training-thread", daemon=True)
    t.start()

    # Flask starten
    app.run(host="0.0.0.0", debug=False)
