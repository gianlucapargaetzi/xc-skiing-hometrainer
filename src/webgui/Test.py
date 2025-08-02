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

# --- Konfiguration laden
with open("x-ski.json", "r") as f:
    config = json.load(f)

pulli_diameter = config["hardware"]["pulli_diameter"]
rope_diameter = config["hardware"]["rope_diameter"]
top_position = config["hardware"]["top_position"]
pole_length = config["hardware"]["pole_length"]
swing_length = config["hardware"]["swing_length"]

swing_start_max_torque_pml = config["swing_torque"]["swing_start_max_torque_pml"]
swing_end_max_torque_pml = config["swing_torque"]["swing_end_max_torque_pml"]

dist_par_rev = round((pulli_diameter + rope_diameter) * 3.14159)

min_torque_calib_pct = config["control"]["min_torque_calib_pct"]
min_speed_calib = config["control"]["min_speed_calib"]
min_torque_pct = config["control"]["min_torque_pct"]
CurrentLimit = config["control"]["CurrentLimit"]
pull_speed = config["control"]["pull_speed"]

weight_kg = config["user"]["weight_kg"]
mu = config["user"]["mu"]
s_s = config["user"]["s_s"]
slope_percent = config["user"]["slope_percent"]

hr_sensor_address = config["hr_sensor"]["address"]

drive_host =  config["drive"]["host"]
drive_port =  config["drive"]["port"]
drive_unitid =  config["drive"]["unit_id"]

# BLE Heart Rate Constants
HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

page_loaded = False
page_lock = Lock()
heart_rate = 0
hr_lock = Lock()
records = []

# BLEPowerServer importieren (wird vorausgesetzt, dass es separat vorhanden ist)
from Utils.ble_power_meter_module import BLEPowerServer

ble_server = BLEPowerServer()
t_ble = Thread(target=ble_server.start, daemon=True)
t_ble.start()

def hr_measurement_handler(sender, data):
    global heart_rate
    if len(data) >= 2:
        value = data[1]
        with hr_lock:
            heart_rate = value

async def connect_heart_rate_sensor():

    KNOWN_MODELS = {
        "INW4J": "Polar Verity Sense",
        "H10": "Polar H10",
        # ggf. weitere hinzufügen
    }

    MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
    
    #address = "A0:9E:1A:45:11:09" #Polar H10 45110924 (A0:9E:1A:45:11:09)
    address = "24:AC:AC:03:F5:B4" #Polar Sense 03F5B433 (24:AC:AC:03:F5:B4)
    print(f"🔗 Versuche Verbindung mit Herzsensor unter {address}...")

    try:
        client = BleakClient(address)
        await client.connect()

        model_number = await client.read_gatt_char(MODEL_NUMBER_UUID)
        model_code = model_number.decode("utf-8").strip()
        friendly_name = KNOWN_MODELS.get(model_code, f"Unbekanntes Modell ({model_code})")
        print(f"📦 Modell erkannt: {friendly_name}")

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

records = []

def moving_average_filter(data, n):
    kernel = np.ones(n) / n
    return np.convolve(data, kernel, mode='valid')

def uint16_to_int16(uint16):
    if uint16 >= 2**15:
        return uint16 - 2**16
    return uint16

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
    client1.write_single_register(404, limit * 10)

def writeTorque(torque):
    client1.write_single_register(407, torque * 100)

def writeSpeed(speed):
    client1.write_single_register(117, speed * 10)

def DriveEnable(driveenable):
    client1.write_single_register(614, driveenable)

def writeForwardDirection(direction):
    client1.write_single_register(629, direction)

def EnableDisableForwardLimit(flag):
    client1.write_single_register(1235, flag)

def saveForwardLimitSwitchPosition():
    client1.write_single_register(1209, 0)
    sleep(0.1)
    client1.write_single_register(1209, 1)

def driveHealthy():
    sw = client1.read_holding_registers(1000, 1)[0]
    return sw == 1 if sw is not None else False

def driveRunning():
    sw = client1.read_holding_registers(1001, 1)[0]
    return sw == 1

def readHardwareEnabled():
    sw = client1.read_holding_registers(628, 1)[0]
    return sw == 1

def readNormalisedPosition():
    p12 = client1.read_holding_registers(327, 2)
    return utils.word_list_to_long(p12)[0]

def readSpeed():
    return uint16_to_int16(client1.read_holding_registers(301, 1)[0]) / 10

def readLoad():
    return uint16_to_int16(client1.read_holding_registers(419, 1)[0]) / 10

def readPower():
    return uint16_to_int16(client1.read_holding_registers(502, 1)[0])

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

if __name__ == '__main__':
    
    app = Backend(__name__)

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
        zero_power_duration = 0


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

        scope.log_message("Bitte Sicherheitsschalter lösen")
        wait_for_sto_OFF()
        scope.log_message("Bitte Seil 50 cm herausziehen, dann STO drücken.")
        print("Bitte Seil 50 cm herausziehen, dann STO drücken.")
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

        scope.log_message("Bitte Sicherheitsschalter lösen")
        wait_for_sto_OFF()
        scope.log_message("Bitte Seil ca. 50cm herausziehen. Zum Starten des Trainings festhalten und Sicherheitsschalter drücken.")
        
        wait_for_sto_ON()
        scope.log_message("✅ Training gestartet")

        print("Starte Training ...")

        EnableDisableForwardLimit(1)
        writeForwardDirection(1)
        writeTorque(min_torque_pct)
        writeSpeed(pull_speed)
        EnableDisableWatchDog(1)
        DriveEnable(1)

        actual_dir = old_dir = True
        sequence_start_time = sequence_end_time = int(datetime.now().timestamp() * 1000)
        sequence_freq = 0
        torque_scale_factor = 0
        act_torque_pct = min_torque_pct
        ic_torque = 0
        speed = 0
        max_speed = 0
        act_power = 0
        power = 0
        mean_power = 0

        #GP
        act_power_array=[]


        threshold = 10

        current_time = datetime.now()
        formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"x-ski_{formatted_time}.txt"

        running = True
        start_time = None

        total_distance= 0  # Gesamtsitanz

        while running:
            toggleWatchDog()
            ic_torque = ic.getIntensity()
            actual_position = readNormalisedPosition()
            speed = readSpeed()
            power = readPower()


            # Negative Leistung ist Zug / Positiv Wickeln
                       # Negative Leistung ist Zug / Positiv Wickeln
            if power < 0:
                act_power = abs(power)
                act_power_array.append(act_power)
                # Wenn vorher keine Nullleistungsphase lief, starte sie
                if zero_power_start_time is not None:
                    zero_power_duration += time.time() - zero_power_start_time
                    zero_power_start_time = None
            else:
                act_power = 0
                act_power_array.append(act_power)
                
                # Wenn gerade neu in eine Nullleistungsphase gewechselt wird
                if zero_power_start_time is None:
                    zero_power_start_time = time.time()


            with hr_lock:
                current_hr = heart_rate


            pos_rel_zero = (100 / (end_swing_position - abs_zero_position)) * (actual_position - abs_zero_position)
            pos_rel_pole = (1000 / (end_swing_position - pole_zero_position)) * (actual_position - pole_zero_position)

            if pos_rel_pole >= 0 and round(pos_rel_pole) < len(f_push):
                torque_scale_factor = f_push[round(pos_rel_pole)]
            else:
                torque_scale_factor = 0

            act_torque_pct = round(min_torque_pct + ((ic_torque * torque_scale_factor / 100)))
            writeTorque(act_torque_pct)

            # Aktuelle Werte für Scope in Array abfüllen
            arr = np.array([pos_rel_zero, speed, act_torque_pct, act_power, current_hr, sequence_freq])
                
            scope.evaluateValue(arr)

            actual_dir = speed > -0

            if old_dir and not actual_dir:
                # Neuer Zug beginnt
                sequence_end_time = sequence_start_time
                current_time = datetime.now()
                sequence_time_stamp = current_time.timestamp()
                sequence_start_time = int(sequence_time_stamp * 1000)
                sequence_freq = round(60000 / (sequence_start_time - sequence_end_time))

                # Mittelwert berechnen
                # mean_power = np.mean(act_power_values)
                mean_power = np.mean(act_power_array)
                if np.isnan(mean_power):
                    mean_power=0

                # Kadenz
                if sequence_freq > 200 or sequence_freq <= 0:
                    sequence_freq = 0

                if sequence_freq > 0 and mean_power > 0:
                    # Gesamtdistanz
                    # distance= distance_per_cycle_dynamic(
                    #     P=mean_power,
                    #     mass=weight_kg,
                    #     mu=mu,
                    #     cadence_rpm=sequence_freq,     # jetzt in U/min
                    #     T_s=zero_power_duration ,
                    #     s_s=s_s,
                    #     slope_percent=slope_percent,   # z. B. 5 % Steigung
                    #     k=3.6 # Skalierungsfaktor gemäss chatgbt für 100W/1Hz/75kg
                    # )

                    distance = distance_per_cycle(mean_power, sequence_freq)

                    print(1/sequence_freq, zero_power_duration, s_s)
                    total_distance= total_distance+distance

                    # Ausgabe über Bluetooth
                    #ble_server.set_power(mean_power)        # Leistung Mittelwert per BLE senden
                    #ble_server.set_cadence(sequence_freq)   # Kadenz per BLE sendev

                    # Ausgabe in Dateien
                    scope.set_summary_values(current_hr, mean_power, sequence_freq,distance,total_distance)

                    record = {
                        "timestamp": current_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+"Z",
                        "sequence_freq": round(sequence_freq/2),    # Strava verdoppelt diesen wert wieder
                        "power": mean_power,
                        "heart_rate": current_hr,
                        "torque": act_torque_pct,
                        "distance": total_distance
                    }
                    records.append(record)
                
                old_dir = actual_dir
                # Nullleistungszeit zurücksetzen für nächsten Zyklus
                zero_power_duration = 0
                act_power_array = []

            elif not old_dir and actual_dir:
                old_dir = actual_dir

            if not ic.active:
                scope.log_message("⛔ Training wurde gestoppt")
                print("Training wurde über Webinterface gestoppt.")

                tcx_filename = f"skiErg_{formatted_time}.tcx"
                write_tcx(records, filename=tcx_filename, sport_note="SkiErg Intervalltraining")
                        
                send_training_email(
                    to_address="juerg.pargaetzi@parmail.ch",
                    subject="X-Ski Training abgeschlossen",
                    body="Anbei findest du die Dateien des letzten Trainings.",
                    attachments=[tcx_filename]
                )
                        
                os._exit(0)
                break
            else:
                scope.log_message("✅ Training läuft")


            #enabled = readHardwareEnabled()

            #if not enabled:
            #    if start_time is None:
            #        start_time = time.time()  # Startzeit merken
            #        scope.log_message("❌ Training pausiert. Zum erneuten Start innert 10s die Sicherheitsschalter drücken")
            #        print("Warten auf Aktivierung")
            #    elif time.time() - start_time > threshold:
            #        scope.log_message("✅ Training beendet")

            #        print(f"❌ Hardware ist seit über {threshold} Sekunden deaktiviert!")
            #        # Hier kannst du z. B. abbrechen oder reagieren:
            #        running = False;
                    # TCX Datei schreiben
            #        tcx_filename = f"skiErg_{formatted_time}.tcx"
            #        write_tcx(records, filename=tcx_filename, sport_note="SkiErg Intervalltraining")
                        
            #        #Strava Upload
            #        # Tokens laden
            #        ##tokens = load_tokens()

            #        # Token ggf. erneuern
            #        ##if time.time() > tokens.get("expires_at", 0):
            #        ##    tokens = refresh_access_token(tokens)

            #        ##access_token = tokens["access_token"]

            #        # Datei hochladen
            #        ##result = upload_tcx(access_token, tcx_filename)
            #        ##print("📄 Upload-Info:", result)

            #        # Mailversand nach Trainingsende
            #        send_training_email(
            #            to_address="juerg.pargaetzi@parmail.ch",
            #            subject="X-Ski Training abgeschlossen",
            #            body="Anbei findest du die Dateien des letzten Trainings.",
            #            attachments=[tcx_filename]
            #a        )
                        
            #        os._exit(0)
            #        break
            #else:
            #    start_time = None  # Reset wenn wieder aktiv                    
            #    scope.log_message("✅ Training läuft")
                    
        DriveEnable(0)
        writeSpeed(0)
        writeTorque(0)
        EnableDisableWatchDog(0)

    t = Thread(target=thread)
    t.start()
    app.run(host="0.0.0.0", debug=False)
