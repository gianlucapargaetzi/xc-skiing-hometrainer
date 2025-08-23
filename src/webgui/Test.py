# Test.py mit Konfigurationsdatei-Unterstützung

import serial
import os
import sys
import time
import json
import asyncio
import numpy as np
from datetime import datetime
from time import sleep
from threading import Lock, Thread
import webbrowser

from flask import Flask, jsonify
from pyModbusTCP.client import ModbusClient
from pyModbusTCP import utils
from bleak import BleakClient

from BasicWebGUI import Backend
from IntensityController.IntervallIntensityController import IntervallIntensityController
from IntensityController.SimpleIntensityController import SimpleIntensityController
from ValueHandler.Scope import Scope
from Utils.CustomLogger import Logger
from Utils.double_poling_distance import distance_per_cycle_dynamic, distance_per_cycle
from Utils.tcx_export import write_tcx
from Utils.email_utils import send_training_email
from Utils.ble_power_meter_module import BLEPowerServer

# --- Konfiguration laden (robust) ---
from pathlib import Path
import argparse

# 1) Defaults (bitte bei Bedarf anpassen)
DEFAULT_CONFIG = {
    "hardware": {
        "pulli_diameter": 110.0,   # mm
        "rope_diameter": 4.0,      # mm
        "top_position": 1400.0,    # mm
        "pole_length": 1250.0,     # mm
        "swing_length": 800.0      # mm
    },
    "swing_torque": {
        "swing_start_max_torque_pml": 180,  # mm Seilweg bis max. Drehmoment
        "swing_end_max_torque_pml": 420
    },
    "control": {
        "min_torque_calib_pct": 5,
        "min_speed_calib": 20,     # 2.0 U/s = 20 (x10)
        "min_torque_pct": 8,
        "CurrentLimit": 6,         # A
        "pull_speed": 50           # 5.0 U/s = 50 (x10)
    },
    "user": {
        "weight_kg": 75.0,
        "mu": 0.020,
        "s_s": 1.10,
        "slope_percent": 0.0,
        "firstname": "x-ski",
        "lastname": "Demo",
        "birthdate": "2000-01-01",
        "club": "x-ski.ch",
        "email": "x-ski@schnaepsli.parmai.ch"
        },
    "hr_sensor": {
        # Polar H10 Beispiel: "A0:9E:1A:45:11:09"
        # Polar Verity Sense Beispiel: "24:AC:AC:03:F5:B4"
        "address": "24:AC:AC:03:F5:B4"
    },
    "drive": {
        "host": "127.0.0.1",
        "port": 502,
        "unit_id": 1
    }
}

def deep_update(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base

# 2) CLI: --config optional erlauben
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--config", dest="config_path", default=None)
known_args, remaining = parser.parse_known_args()
# restliche Args für spätere Parser lassen (z.B. "sic"/"iic")
sys.argv = [sys.argv[0], *remaining]

# 3) Kandidaten-Suchpfade (in Reihenfolge)
SCRIPT_DIR = Path(__file__).resolve().parent
env_cfg = os.getenv("X_SKI_CONFIG")
candidates = [
    Path(known_args.config_path) if known_args.config_path else None,
    Path(env_cfg) if env_cfg else None,
    SCRIPT_DIR / "x-ski.json",
    SCRIPT_DIR / "configs" / "x-ski.json",
    Path.cwd() / "x-ski.json",
]

config = json.loads(json.dumps(DEFAULT_CONFIG))  # tiefe Kopie
found_path = None
for p in candidates:
    if p and p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            deep_update(config, user_cfg)
            found_path = p
            print(f"✅ Konfiguration geladen aus: {p}")
            break
        except Exception as e:
            print(f"⚠️ Konnte {p} nicht laden: {e}")

if not found_path:
    # Optional: Beispiel-Datei schreiben, damit man weiß, wo man editieren kann
    example = SCRIPT_DIR / "x-ski.example.json"
    try:
        with open(example, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"ℹ️ Keine x-ski.json gefunden. Beispiel geschrieben nach: {example}")
        print("   Du kannst diese Datei kopieren/umbenennen und anpassen.")
    except Exception as e:
        print(f"⚠️ Konnte Beispiel-Config nicht schreiben: {e}")

# 4) Variablen aus config ableiten (wie gehabt)
pulli_diameter = config["hardware"]["pulli_diameter"]
rope_diameter = config["hardware"]["rope_diameter"]
top_position = config["hardware"]["top_position"]
pole_length = config["hardware"]["pole_length"]
swing_length = config["hardware"]["swing_length"]

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

drive_host    = config["drive"]["host"]
drive_port    = config["drive"]["port"]
drive_unitid  = config["drive"]["unit_id"]

# BLE Heart Rate Constants
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"

page_loaded = False
page_lock = Lock()
heart_rate = 0
hr_lock = Lock()
records = []

ble_server = BLEPowerServer()
t_ble = Thread(target=ble_server.start, daemon=True)
t_ble.start()

def hr_measurement_handler(sender, data: bytearray):
    """Robustes Parsen: unterstützt 8- und 16-bit Herzfrequenzwerte."""
    global heart_rate
    if not data:
        return
    flags = data[0]
    hr_16bit = flags & 0x01
    if hr_16bit and len(data) >= 3:
        value = int.from_bytes(data[1:3], byteorder="little")
    elif len(data) >= 2:
        value = data[1]
    else:
        return
    with hr_lock:
        heart_rate = int(value)

async def connect_heart_rate_sensor():
    KNOWN_MODELS = {
        "INW4J": "Polar Verity Sense",
        "H10": "Polar H10",
        # ggf. weitere hinzufügen
    }

    address = hr_sensor_address  # aus der geladenen Config verwenden
    print(f"🔗 Versuche Verbindung mit Herzsensor unter {address}...")

    try:
        client = BleakClient(address)
        await client.connect()

        try:
            model_number = await client.read_gatt_char(MODEL_NUMBER_UUID)
            model_code = model_number.decode("utf-8", errors="ignore").strip()
            friendly_name = KNOWN_MODELS.get(model_code, f"Unbekanntes Modell ({model_code})")
            print(f"📦 Modell erkannt: {friendly_name}")
        except Exception as e:
            print(f"ℹ️ Modellnummer konnte nicht gelesen werden: {e}")

        await client.start_notify(HR_MEASUREMENT_CHAR_UUID, hr_measurement_handler)
        print("📡 Herzfrequenzübertragung aktiv")
        while True:
            await asyncio.sleep(1)
    except Exception as e:
        print(f"❌ Verbindung fehlgeschlagen: {e}")

def start_hr_ble():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(connect_heart_rate_sensor())

t_hr = Thread(target=start_hr_ble, daemon=True)
t_hr.start()

sleep(5)

MIN_VALUE = 10
MAX_VALUE = 100
STEP = 5

def moving_average_filter(data, n):
    kernel = np.ones(n) / n
    return np.convolve(data, kernel, mode='valid')

def uint16_to_int16(uint16):
    if uint16 >= 2**15:
        return uint16 - 2**16
    return uint16

# ----------------------- Modbus Helper (robust) -----------------------

def _read1(addr):
    vals = client1.read_holding_registers(addr, 1)
    return vals[0] if vals else None

def DriveReset():
    client1.write_single_register(1032, 1)
    client1.write_single_register(1032, 0)
    client1.write_single_register(1032, 1)

def EnableDisableWatchDog(watchdog):
    client1.write_single_register(642, watchdog)

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

# ----------------------- Main -----------------------

if __name__ == '__main__':
    app = Backend(__name__)


    @app.route("/api/user", methods=["GET"])
    def api_user():
        u = config.get("user", {})
        return jsonify({
            "firstname": u.get("firstname", ""),
            "lastname":  u.get("lastname", ""),
            "birthdate": u.get("birthdate", ""),
            "club":      u.get("club", "")
        })

    @app.route("/page_ready", methods=["POST"])
    def page_ready():
        global page_loaded
        with page_lock:
            page_loaded = True
        return jsonify({"status": "ok"})

    client1 = ModbusClient(host=drive_host, port=drive_port, unit_id=drive_unitid, auto_open=True)
    scope = Scope()

    def thread():
        global page_loaded

        zero_power_start_time = None
        zero_power_duration = 0.0

        # Controller-Auswahl (CLI: "sic" oder "iic")
        if len(sys.argv) > 1:
            controller = sys.argv[1]
        else:
            controller = "sic"

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

        scope.log_message("Seil herausziehen und Sicherheitsschalter auslösen")
        wait_for_sto_OFF()
        EnableDisableForwardLimit(0)
        wait_for_sto_ON()
        scope.log_message("Bitte langsam zum oberem Anschlag führen")

        calibrate_end_position()

        pole_offset = round((top_position - pole_length) / dist_par_rev * 65536)
        abs_zero_position = readNormalisedPosition()
        pole_zero_position = abs_zero_position - pole_offset
        start_max_torque_position = pole_zero_position - round(swing_start_max_torque_pml / dist_par_rev * 65536)
        end_max_torque_position = pole_zero_position - round(swing_end_max_torque_pml / dist_par_rev * 65536)
        end_swing_position = pole_zero_position - round(swing_length / dist_par_rev * 65536)

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
        max_speed = 0.0
        act_power = 0
        power = 0
        mean_power = 0.0

        act_power_array = []

        threshold = 10

        current_time = datetime.now()
        formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"x-ski_{formatted_time}.txt"

        running = True
        start_time = None

        total_distance = 0.0  # Gesamtdistanz

        while running:
            toggleWatchDog()
            ic_torque = ic.getIntensity()
            actual_position = readNormalisedPosition()
            speed = readSpeed()
            power = readPower()

            # Negative Leistung ist Zug / Positiv Wickeln
            if power < 0:
                act_power = abs(power)
                act_power_array.append(act_power)
                # Nullleistungsphase ggf. beenden
                if zero_power_start_time is not None:
                    zero_power_duration += time.time() - zero_power_start_time
                    zero_power_start_time = None
            else:
                act_power = 0
                act_power_array.append(act_power)
                # Nullleistungsphase starten
                if zero_power_start_time is None:
                    zero_power_start_time = time.time()

            with hr_lock:
                current_hr = heart_rate

            pos_rel_zero = (100 / (end_swing_position - abs_zero_position)) * (actual_position - abs_zero_position) if (end_swing_position - abs_zero_position) != 0 else 0
            pos_rel_pole = (1000 / (end_swing_position - pole_zero_position)) * (actual_position - pole_zero_position) if (end_swing_position - pole_zero_position) != 0 else 0

            if pos_rel_pole >= 0 and round(pos_rel_pole) < len(f_push):
                torque_scale_factor = f_push[round(pos_rel_pole)]
            else:
                torque_scale_factor = 0

            act_torque_pct = round(min_torque_pct + ((ic_torque * torque_scale_factor / 100)))
            writeTorque(act_torque_pct)

            # Aktuelle Werte für Scope in Array abfüllen
            arr = np.array([pos_rel_zero, speed, act_torque_pct, act_power, current_hr, sequence_freq])
            scope.evaluateValue(arr)

            actual_dir = speed > 0

            if old_dir and not actual_dir:
                # Neuer Zug beginnt -> Zyklusende erkannt
                prev_start = sequence_start_time
                current_time = datetime.now()
                sequence_time_stamp = current_time.timestamp()
                sequence_start_time = int(sequence_time_stamp * 1000)
                delta = sequence_start_time - prev_start
                sequence_freq = round(60000 / delta) if delta > 0 else 0

                # Mittelwert berechnen
                mean_power = float(np.mean(act_power_array)) if len(act_power_array) else 0.0
                if np.isnan(mean_power):
                    mean_power = 0.0

                # Kadenz filtern
                if sequence_freq > 200 or sequence_freq <= 0:
                    sequence_freq = 0

                if sequence_freq > 0 and mean_power > 0:
                    # Distanz pro Zyklus (aktuell simple Methode)
                    # Alternative (komplexer, mit Params): distance_per_cycle_dynamic(...)
                    distance = distance_per_cycle(mean_power, sequence_freq)

                    print(1/sequence_freq if sequence_freq else 0, zero_power_duration, s_s)
                    total_distance += distance

                    # Ausgabe an WebGUI
                    scope.set_summary_values(current_hr, mean_power, sequence_freq, distance, total_distance)

                    record = {
                        "timestamp": current_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + "Z",
                        "sequence_freq": round(sequence_freq / 2),  # Strava verdoppelt diesen Wert wieder
                        "power": mean_power,
                        "heart_rate": current_hr,
                        "torque": act_torque_pct,
                        "distance": total_distance
                    }
                    records.append(record)

                # Reset für nächsten Zyklus
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
                    # TCX nur erzeugen, wenn es mindestens einen Trackpoint gibt
                    write_tcx(records, filename=tcx_filename, sport_note="SkiErg Intervalltraining")
                    attachments = [tcx_filename]

                    send_training_email(
                        to_address=user_email or "fallback@example.com",
                        subject=f"X-Ski Training abgeschlossen – {user_firstname} {user_lastname}",
                        body=(
                            f"Hallo {user_firstname},\n\n"
                            "anbei findest du die Dateien deines letzten Trainings.\n\n"
                            f"Verein: {user_club}\n"
                            f"Geburtsdatum: {user_birthdate}\n"
                        ),
                    attachments=attachments
                    )

                else:
                    # Kein Cycle erkannt → Hinweis ins Log und keine Anlage
                    scope.log_message("ℹ️ Keine Trainingsdaten (keine Züge erkannt) – TCX wird nicht erzeugt.")
                    print("Hinweis: Keine records vorhanden – TCX-Erzeugung übersprungen.")

                os._exit(0)
                break
            else:
                scope.log_message("✅ Training läuft")

        DriveEnable(0)
        writeSpeed(0)
        writeTorque(0)
        EnableDisableWatchDog(0)

    t = Thread(target=thread)
    t.start()
    app.run(host="0.0.0.0", debug=False)
