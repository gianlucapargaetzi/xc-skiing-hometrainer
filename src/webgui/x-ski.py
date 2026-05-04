# x-ski.py – x-ski WebGUI + Training + Konfig-Management mit ConfigManager & BLEManager

import os
import sys
import time
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
from time import sleep
from threading import Lock, Thread

import webbrowser
from flask import jsonify, render_template, request
from pyModbusTCP.client import ModbusClient
from pyModbusTCP import utils

from BasicWebGUI import Backend
from IntensityController.IntervallIntensityController import IntervallIntensityController
from IntensityController.SimpleIntensityController import SimpleIntensityController
from ValueHandler.Scope import Scope
from Utils.double_poling_distance import distance_per_stroke
from Utils.tcx_export import write_tcx
from Utils.email_utils import send_training_email
from Utils.config_manager import ConfigManager, DEFAULT_CONFIG
from Utils.ble_manager import BLEManager
from Utils.ant_hr_manager import ANTHRManager


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = SCRIPT_DIR / "templates"

# Korrigiert: top_position = 2100 mm muss innerhalb des darstellbaren / validierbaren Bereichs liegen
MAX_TRAVEL_MM = 2500
current_gui_intensity = 60.0

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--config", dest="config_path", default=None)
parser.add_argument("--controller", choices=["sic", "iic"], default="sic")
parser.add_argument("--no-browser", dest="no_browser", action="store_true")
known_args, remaining = parser.parse_known_args()
sys.argv = [sys.argv[0], *remaining]

cfg_manager = ConfigManager(
    script_dir=SCRIPT_DIR,
    active_filename="x-ski.json",
    config_dirname="configs",
    default_config=DEFAULT_CONFIG,
    env_var="X_SKI_CONFIG",
)
config, config_path = cfg_manager.load_from_candidates(cli_path=known_args.config_path)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def resolve_template_name(*candidates: str) -> str:
    for name in candidates:
        if (TEMPLATES_DIR / name).exists():
            return name
    return candidates[0]


def get_hr_zone_key(hr_value, training_targets):
    hr_zones = (training_targets or {}).get("hr_zones", {})
    if not hr_zones:
        return None

    try:
        hr_value = float(hr_value)
    except (TypeError, ValueError):
        return None

    z5_low = hr_zones.get("z5", {}).get("low_bpm")
    z4_low = hr_zones.get("z4", {}).get("low_bpm")
    z3_low = hr_zones.get("z3", {}).get("low_bpm")
    z2_low = hr_zones.get("z2", {}).get("low_bpm")
    z1_low = hr_zones.get("z1", {}).get("low_bpm")

    if z5_low is not None and hr_value >= z5_low:
        return "z5"
    if z4_low is not None and hr_value >= z4_low:
        return "z4"
    if z3_low is not None and hr_value >= z3_low:
        return "z3"
    if z2_low is not None and hr_value >= z2_low:
        return "z2"
    if z1_low is not None and hr_value >= z1_low:
        return "z1"

    return None


def get_spm_zone_key(cadence_spm, training_targets):
    spm_zones = (training_targets or {}).get("skierg_spm_zones", {})
    if not spm_zones:
        return None

    try:
        cadence_spm = float(cadence_spm)
    except (TypeError, ValueError):
        return None

    z1_high = spm_zones.get("z1", {}).get("high_spm")
    z2_high = spm_zones.get("z2", {}).get("high_spm")
    z3_high = spm_zones.get("z3", {}).get("high_spm")
    z4_high = spm_zones.get("z4", {}).get("high_spm")

    if z1_high is not None and cadence_spm <= z1_high:
        return "z1"
    if z2_high is not None and cadence_spm <= z2_high:
        return "z2"
    if z3_high is not None and cadence_spm <= z3_high:
        return "z3"
    if z4_high is not None and cadence_spm <= z4_high:
        return "z4"
    return "z5"


def get_reference_zone_key(current_hr, cadence_spm, training_targets):
    zone_key = get_hr_zone_key(current_hr, training_targets)
    if zone_key:
        return zone_key
    return get_spm_zone_key(cadence_spm, training_targets)


def calculate_push_phase_energy_j(
    positions_mm,
    power_values,
    timestamps_s,
    swing_start_mm,
    swing_end_mm
):
    if not positions_mm or not power_values or not timestamps_s:
        return 0.0

    if not (len(positions_mm) == len(power_values) == len(timestamps_s)):
        return 0.0

    energy_j = 0.0

    for i in range(1, len(positions_mm)):
        try:
            x0 = float(positions_mm[i - 1])
            x1 = float(positions_mm[i])
            p0 = float(power_values[i - 1])
            p1 = float(power_values[i])
            t0 = float(timestamps_s[i - 1])
            t1 = float(timestamps_s[i])
        except (TypeError, ValueError):
            continue

        dt = t1 - t0
        if dt <= 0 or dt > 0.25:
            continue

        x_mid = 0.5 * (x0 + x1)
        if not (swing_start_mm <= x_mid <= swing_end_mm):
            continue

        p0_active = abs(p0) if p0 < 0 else 0.0
        p1_active = abs(p1) if p1 < 0 else 0.0
        p_avg = 0.5 * (p0_active + p1_active)

        energy_j += p_avg * dt

    return max(0.0, energy_j)


def calculate_reference_push_energy_j(reference_zone_key, training_targets):
    if not reference_zone_key:
        return 0.0, None, None

    combined = (training_targets or {}).get("combined_zones", {})
    zone = combined.get(reference_zone_key, {})
    if not zone:
        return 0.0, None, None

    spm_cfg = zone.get("spm", {})
    xski_cfg = zone.get("xski_power", {})

    ref_spm = spm_cfg.get("target_spm")
    ref_power_w = xski_cfg.get("high_w")

    if ref_power_w is None:
        ref_power_w = xski_cfg.get("low_w")

    try:
        ref_spm = float(ref_spm)
        ref_power_w = float(ref_power_w)
    except (TypeError, ValueError):
        return 0.0, None, None

    if ref_spm <= 0 or ref_power_w <= 0:
        return 0.0, None, None

    ref_cycle_duration_s = 60.0 / ref_spm
    ref_energy_j = ref_power_w * ref_cycle_duration_s
    return float(ref_energy_j), ref_spm, ref_power_w


def calculate_push_phase_utilization_pct(actual_energy_j, reference_energy_j):
    try:
        actual_energy_j = float(actual_energy_j)
        reference_energy_j = float(reference_energy_j)
    except (TypeError, ValueError):
        return 0.0

    if reference_energy_j <= 0:
        return 0.0

    return 100.0 * (actual_energy_j / reference_energy_j)


def apply_config_globals():
    global pulli_diameter, rope_diameter, top_position, pole_length, swing_length
    global swing_start_max_torque_pml, swing_end_max_torque_pml, dist_par_rev
    global min_torque_calib_pct, min_speed_calib, min_torque_pct, CurrentLimit, pull_speed
    global weight_kg, mu, s_s, slope_percent
    global drive_host, drive_port, drive_unitid
    global user_firstname, user_lastname, user_birthdate, user_club, user_email
    global max_torque_pct, simple_initial_power_pct
    global max_hr_bpm, ftp_w
    global training_targets
    global mywhoosh_ble_enabled, mywhoosh_ble_name, mywhoosh_ble_adapter
    global ant_hr_enabled, ant_hr_device_id

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
    max_torque_pct = config["control"].get("max_torque_pct", 150)
    simple_initial_power_pct = safe_float(
        config["control"].get("simple_initial_power_pct", 50),
        50.0
    )

    weight_kg = config["user"]["weight_kg"]
    mu = config["user"]["mu"]
    s_s = config["user"]["s_s"]
    slope_percent = config["user"]["slope_percent"]

    user_firstname = config["user"].get("firstname", "")
    user_lastname = config["user"].get("lastname", "")
    user_birthdate = config["user"].get("birthdate", "")
    user_club = config["user"].get("club", "")
    user_email = config["user"].get("email", "")

    max_hr_bpm = safe_float(config["user"].get("max_hr_bpm", 0), 0.0)
    ftp_w = safe_float(config["user"].get("ftp_w", 0), 0.0)

    training_targets = cfg_manager.get_training_targets()

    drive_host = config["drive"]["host"]
    drive_port = config["drive"]["port"]
    drive_unitid = config["drive"]["unit_id"]

    mywhoosh_ble_cfg = config.get("mywhoosh_ble", {})
    mywhoosh_ble_enabled = bool(mywhoosh_ble_cfg.get("enabled", True))
    mywhoosh_ble_name = mywhoosh_ble_cfg.get("device_name", "x-ski FTMS")
    mywhoosh_ble_adapter = mywhoosh_ble_cfg.get("adapter", "hci0")

    ant_hr_cfg = config.get("ant_hr_sensor", {})
    ant_hr_enabled = bool(ant_hr_cfg.get("enabled", True))
    ant_hr_device_id = int(ant_hr_cfg.get("device_id", 0) or 0)


def validate_geometry():
    swing_start_mm = top_position - pole_length
    swing_end_mm = swing_start_mm + swing_length

    errors = []

    if top_position > MAX_TRAVEL_MM:
        errors.append(f"top_position ({top_position}) darf nicht größer als {MAX_TRAVEL_MM} sein.")

    if swing_start_mm < 0:
        errors.append(
            f"top_position - pole_length = {swing_start_mm} ist kleiner als 0. "
            "Die Stocklänge ist größer als die Montagehöhe."
        )

    if swing_end_mm > MAX_TRAVEL_MM:
        errors.append(
            f"top_position - pole_length + swing_length = {swing_end_mm} ist größer als {MAX_TRAVEL_MM}. "
            "Wichtig: Höhe minus Stocklänge plus Schwunglänge muss kleiner oder gleich MAX_TRAVEL_MM sein."
        )

    if swing_start_max_torque_pml < 0:
        errors.append("swing_start_max_torque_pml darf nicht negativ sein.")

    if swing_end_max_torque_pml < 0:
        errors.append("swing_end_max_torque_pml darf nicht negativ sein.")

    if swing_start_max_torque_pml > swing_length:
        errors.append("swing_start_max_torque_pml darf nicht größer als swing_length sein.")

    if swing_end_max_torque_pml > swing_length:
        errors.append("swing_end_max_torque_pml darf nicht größer als swing_length sein.")

    if swing_start_max_torque_pml > swing_end_max_torque_pml:
        errors.append("swing_start_max_torque_pml darf nicht größer als swing_end_max_torque_pml sein.")

    if errors:
        raise ValueError("\n".join(errors))


def create_ble_manager():
    return BLEManager(
        enable_ftms=mywhoosh_ble_enabled,
        ftms_device_name=mywhoosh_ble_name,
        ftms_adapter=mywhoosh_ble_adapter,
    )


def create_ant_hr_manager():
    return ANTHRManager(
        device_id=ant_hr_device_id,
        enabled=ant_hr_enabled,
    )


def apply_runtime_reload():
    global config, config_path, ble_manager, ant_hr_manager, scope

    old_ant_hr_enabled = globals().get("ant_hr_enabled", None)
    old_ant_hr_device_id = globals().get("ant_hr_device_id", None)
    old_ftms_enabled = globals().get("mywhoosh_ble_enabled", None)
    old_ftms_name = globals().get("mywhoosh_ble_name", None)
    old_ftms_adapter = globals().get("mywhoosh_ble_adapter", None)

    result = cfg_manager.reload_active()
    config = cfg_manager.config
    config_path = cfg_manager.ACTIVE_CONFIG_PATH

    apply_config_globals()
    validate_geometry()

    ant_config_changed = (
        old_ant_hr_enabled != ant_hr_enabled
        or old_ant_hr_device_id != ant_hr_device_id
    )

    ftms_config_changed = (
        old_ftms_enabled != mywhoosh_ble_enabled
        or old_ftms_name != mywhoosh_ble_name
        or old_ftms_adapter != mywhoosh_ble_adapter
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
        scope.max_hr_bpm = max_hr_bpm
        scope.ftp_w = ftp_w
        scope.training_targets = training_targets

    if isinstance(active_ic, SimpleIntensityController) and hasattr(active_ic, "set_init_value"):
        active_ic.set_init_value(simple_initial_power_pct, apply_now=False)

    print("Konfiguration neu geladen.")
    print(f"Max HR: {max_hr_bpm}")
    print(f"FTP: {ftp_w}")
    print(f"SIC Initial Power: {simple_initial_power_pct}")
    print(f"Training targets: {training_targets}")
    print(f"MyWhoosh BLE enabled: {mywhoosh_ble_enabled}")
    print(f"MyWhoosh BLE name: {mywhoosh_ble_name}")
    print(f"MyWhoosh BLE adapter: {mywhoosh_ble_adapter}")
    print(f"ANT HR enabled: {ant_hr_enabled}")
    print(f"ANT HR device_id: {ant_hr_device_id}")

    return result


apply_config_globals()
validate_geometry()

page_loaded = False
page_lock = Lock()

ble_manager = create_ble_manager()
ant_hr_manager = create_ant_hr_manager()
scope = None
client1 = None


def uint16_to_int16(uint16):
    if uint16 >= 2**15:
        return uint16 - 2**16
    return uint16


def moving_average_filter(data, n):
    if n <= 1:
        return data
    kernel = np.ones(n) / n
    return np.convolve(data, kernel, mode="same")


def safe_mean(values):
    if not values:
        return 0.0
    value = float(np.mean(values))
    if np.isnan(value):
        return 0.0
    return value


def calculate_swing_efficiency_pct(cycle_duration_ms, zero_power_duration_s):
    if cycle_duration_ms is None or cycle_duration_ms <= 0:
        return 0.0

    cycle_duration_s = float(cycle_duration_ms) / 1000.0
    if cycle_duration_s <= 0:
        return 0.0

    zero_power_duration_s = max(0.0, min(float(zero_power_duration_s), cycle_duration_s))
    efficiency_pct = 100.0 * (1.0 - (zero_power_duration_s / cycle_duration_s))
    return max(0.0, min(efficiency_pct, 100.0))


def calculate_torque_power_index(mean_power_w, mean_target_torque_pct):
    if mean_target_torque_pct is None or mean_target_torque_pct <= 0:
        return 0.0
    return float(mean_power_w) / float(mean_target_torque_pct)


def build_force_profile_absolute(
    total_length_mm,
    swing_start_mm,
    max_torque_start_mm,
    max_torque_end_mm,
    swing_end_mm,
    min_torque_value=0.0,
    max_torque_value=100.0,
    smooth_window=1,
):
    """
    Double-Poling-ähnliche Bremskurve:
    - vor swing_start_mm: 0
    - ab swing_start_mm: steiler Aufbau
    - Peak früh bis mittig
    - breiter, kontrollierter Abfall
    - bei swing_end_mm: zurück auf 0

    Die alten Parameter max_torque_start_mm / max_torque_end_mm bleiben in der Signatur,
    werden hier aber nicht mehr zur Plateau-Bildung verwendet. So bleibt die restliche
    Codebasis kompatibel.
    """
    total_length_mm = max(int(total_length_mm), 1)
    swing_start_mm = int(max(0, min(swing_start_mm, total_length_mm - 1)))
    swing_end_mm = int(max(swing_start_mm + 1, min(swing_end_mm, total_length_mm)))

    f_push = np.full(total_length_mm + 1, float(min_torque_value), dtype=float)

    # Formparameter für realistischeren Double-Poling-Verlauf
    a = 0.8
    b = 1.35

    x = np.arange(total_length_mm + 1, dtype=float)
    u = (x - swing_start_mm) / float(swing_end_mm - swing_start_mm)

    mask = (u >= 0.0) & (u <= 1.0)
    shape = np.zeros_like(x, dtype=float)
    shape[mask] = (u[mask] ** a) * ((1.0 - u[mask]) ** b)

    shape_max = shape.max() if shape.max() > 0 else 1.0
    shape /= shape_max

    f_push[mask] = min_torque_value + (max_torque_value - min_torque_value) * shape[mask]
    f_push = np.clip(f_push, min_torque_value, max_torque_value)

    if smooth_window and smooth_window > 1:
        f_push = moving_average_filter(f_push, min(int(smooth_window), len(f_push)))
        f_push = np.clip(f_push, min_torque_value, max_torque_value)

    return f_push


def build_target_torque_curve_absolute(
    total_length_mm,
    swing_start_mm,
    max_torque_start_mm,
    max_torque_end_mm,
    swing_end_mm,
    min_torque_pct_value,
    current_intensity_value,
    max_torque_limit_value,
    smooth_window=1,
):
    base_profile = build_force_profile_absolute(
        total_length_mm=total_length_mm,
        swing_start_mm=swing_start_mm,
        max_torque_start_mm=max_torque_start_mm,
        max_torque_end_mm=max_torque_end_mm,
        swing_end_mm=swing_end_mm,
        min_torque_value=0.0,
        max_torque_value=100.0,
        smooth_window=smooth_window,
    )
    target = min_torque_pct_value + (current_intensity_value * (base_profile / 100.0))
    target = np.clip(target, min_torque_pct_value, max_torque_limit_value)
    return target


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
    torque = max(0, min(float(torque), float(max_torque_pct)))
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
        time.sleep(0.2)
    print("Drive bereit.")


def wait_for_sto_OFF():
    print("Warte auf STO-Auslösung ...")
    while readHardwareEnabled():
        print("Bitte STO lösen", end="\r")
        time.sleep(0.1)
    print("STO ist aus.")


def wait_for_sto_ON():
    print("Warte auf STO-Einschaltung ...")
    while not readHardwareEnabled():
        print("Bitte STO drücken", end="\r")
        time.sleep(0.1)
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
        time.sleep(0.01)
    DriveEnable(0)
    writeForwardDirection(0)
    saveForwardLimitSwitchPosition()
    EnableDisableForwardLimit(1)
    print("Kalibrierung abgeschlossen.")


app = Backend(__name__)

ACTIVE_CONTROLLER_NAME = known_args.controller

if ACTIVE_CONTROLLER_NAME == "iic":
    active_ic = IntervallIntensityController()
    START_PAGE = "http://localhost:5000/iic"
else:
    active_ic = SimpleIntensityController(init_value=simple_initial_power_pct)
    current_gui_intensity = float(active_ic.getIntensity())
    START_PAGE = "http://localhost:5000/sic"

print(f"Aktiver Controller: {ACTIVE_CONTROLLER_NAME}")


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

    status = {
        "controller_mode": ACTIVE_CONTROLLER_NAME,
        "interval_active": is_active,
        "interval_phase": _normalize_interval_phase(raw_phase, is_active),
        "current_interval": current_interval,
        "total_intervals": total_intervals,
    }

    return status


@app.route("/header")
def header():
    active = request.args.get("active", "")
    u = config.get("user", {})
    return render_template("partials/header.html", user=u, active=active)


@app.route("/config")
def config_page():
    return render_template("config.html")


@app.route("/sic")
def sic_page():
    return render_template("multi_view_sic.html")


@app.route("/simple")
def simple_page():
    return render_template("simple.html")


@app.route("/iic")
def iic_page():
    if ACTIVE_CONTROLLER_NAME != "iic":
        return (
            "Intervall-Controller ist nicht aktiv. "
            "Bitte x-ski.py mit --controller iic starten.",
            400,
        )
    return render_template("multi_view_iic.html")


@app.route("/interval")
def interval_page():
    if ACTIVE_CONTROLLER_NAME != "iic":
        return (
            "Intervall-Seite ist nur verfügbar, wenn der Intervall-Controller aktiv ist. "
            "Bitte x-ski.py mit --controller iic starten.",
            400,
        )
    return render_template("interval.html")


@app.route("/dashboard")
def dashboard_page():
    return render_template(resolve_template_name("Dashboard.html", "dashboard.html"))


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
    return jsonify(training_targets)


@app.route("/api/reload_config", methods=["POST"])
def api_reload_config():
    try:
        result = apply_runtime_reload()
        return jsonify({
            "ok": True,
            "message": "Konfiguration erfolgreich neu geladen",
            "config_source": str(config_path) if config_path else None,
            "max_hr_bpm": max_hr_bpm,
            "ftp_w": ftp_w,
            "simple_initial_power_pct": simple_initial_power_pct,
            "training_targets": training_targets,
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
    swing_start_mm = top_position - pole_length
    max_torque_start_mm = swing_start_mm + swing_start_max_torque_pml
    max_torque_end_mm = swing_start_mm + swing_end_max_torque_pml
    swing_end_mm = swing_start_mm + swing_length

    x = list(range(0, MAX_TRAVEL_MM + 1))
    target_torque_curve = build_target_torque_curve_absolute(
        total_length_mm=MAX_TRAVEL_MM,
        swing_start_mm=swing_start_mm,
        max_torque_start_mm=max_torque_start_mm,
        max_torque_end_mm=max_torque_end_mm,
        swing_end_mm=swing_end_mm,
        min_torque_pct_value=min_torque_pct,
        current_intensity_value=current_gui_intensity,
        max_torque_limit_value=max_torque_pct,
        smooth_window=1,
    )
    return jsonify({
        "max_travel_mm": MAX_TRAVEL_MM,
        "max_torque_pct": max_torque_pct,
        "max_hr_bpm": max_hr_bpm,
        "ftp_w": ftp_w,
        "simple_initial_power_pct": simple_initial_power_pct,
        "training_targets": training_targets,
        "controller_status": get_controller_status(),
        "markers": {
            "swing_start_mm": swing_start_mm,
            "max_torque_start_mm": max_torque_start_mm,
            "max_torque_end_mm": max_torque_end_mm,
            "swing_end_mm": swing_end_mm
        },
        "target_torque": {
            "x": x,
            "y": target_torque_curve.tolist()
        }
    })


def training_thread():
    global page_loaded
    global current_gui_intensity

    records = []
    zero_power_start_time = None
    zero_power_duration = 0.0

    ic = active_ic

    if known_args.no_browser:
        with page_lock:
            page_loaded = True
        print("Browser-Start deaktiviert (--no-browser).")
    else:
        webbrowser.open(START_PAGE)

    print("🔁 Warte auf WebGUI-Start ...")
    while not page_loaded:
        time.sleep(0.1)
    print("✅ WebGUI geladen – starte Log")

    scope.log_message("❌ Warte bis Drive bereit")
    sleep(2)

    swing_start_mm = int(top_position - pole_length)
    max_torque_start_mm = int(swing_start_mm + swing_start_max_torque_pml)
    max_torque_end_mm = int(swing_start_mm + swing_end_max_torque_pml)
    swing_end_mm = int(swing_start_mm + swing_length)

    print(f"Montagehöhe / Anzeigeachse: 0..{MAX_TRAVEL_MM} mm")
    print(f"Schwungbeginn: {swing_start_mm} mm")
    print(f"Max-Drehmoment Start (Legacy-Marker): {max_torque_start_mm} mm")
    print(f"Max-Drehmoment Ende (Legacy-Marker): {max_torque_end_mm} mm")
    print(f"Schwungende: {swing_end_mm} mm")
    print(f"Max torque limit: {max_torque_pct}")
    print(f"SIC Initial Power: {simple_initial_power_pct}")
    print(f"Max HR: {max_hr_bpm}")
    print(f"FTP: {ftp_w} W")
    print(f"Training targets: {training_targets}")
    print(f"MyWhoosh BLE enabled: {mywhoosh_ble_enabled}")
    print(f"MyWhoosh BLE name: {mywhoosh_ble_name}")
    print(f"MyWhoosh BLE adapter: {mywhoosh_ble_adapter}")
    print(f"ANT HR enabled: {ant_hr_enabled}")
    print(f"ANT HR device_id: {ant_hr_device_id}")

    f_push = build_force_profile_absolute(
        total_length_mm=MAX_TRAVEL_MM,
        swing_start_mm=swing_start_mm,
        max_torque_start_mm=max_torque_start_mm,
        max_torque_end_mm=max_torque_end_mm,
        swing_end_mm=swing_end_mm,
        min_torque_value=0.0,
        max_torque_value=100.0,
        smooth_window=1,
    )

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
    zero_offset = round(50 / dist_par_rev * 65536)
    abs_zero_position = readNormalisedPosition()
    pole_zero_position = abs_zero_position - pole_offset
    soft_zero_position = abs_zero_position - zero_offset
    end_swing_position = pole_zero_position - round(float(swing_length) / dist_par_rev * 65536)

    wait_for_sto_ON()
    scope.log_message("✅ System bereit")

    EnableDisableForwardLimit(1)
    writeForwardDirection(1)
    writeTorque(min_torque_pct)
    writeSpeed(pull_speed)
    EnableDisableWatchDog(1)
    DriveEnable(1)

    # Robuster für erste Züge
    PULL_START_SPEED_THRESHOLD = 5.0
    SPEED_DEADBAND = 2.0

    actual_dir = False
    old_dir = False
    cadence_cycle_start_time_ms = int(datetime.now().timestamp() * 1000)
    cadence_spm = 0
    act_torque_pct = min_torque_pct
    speed = 0.0
    act_power = 0
    mean_power = 0.0
    act_power_array = []
    act_torque_array = []
    cycle_pos_mm_array = []
    cycle_power_raw_array = []
    cycle_time_s_array = []

    current_time = datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")

    total_distance = 0.0
    running = True
    first_pull_detected = False

    session_started_at = None
    ftms_last_push_monotonic = 0.0
    ftms_stroke_count = 0
    ftms_avg_power_w = 0.0
    ftms_avg_pace_s500 = 0.0
    ftms_last_cadence_spm = 0.0
    ftms_last_pace_s500 = 0
    ftms_last_power_w = 0.0

    ble_manager.reset_rower_session()

    while running and readHardwareEnabled():
        toggleWatchDog()
        just_started_clock = False

        ic_torque = ic.getIntensity()
        current_gui_intensity = float(ic_torque)
        ic_torque = max(0, min(float(ic_torque), float(max_torque_pct)))

        actual_position = readNormalisedPosition()

        if actual_position <= soft_zero_position:
            DriveEnable(1)
        else:
            DriveEnable(0)

        speed = readSpeed()
        power = readPower()

        # Uhr / Session beim ersten echten Zug starten – unabhängig vom Vorzeichen
        if not first_pull_detected and abs(speed) > PULL_START_SPEED_THRESHOLD:
            first_pull_detected = True
            just_started_clock = True

            if session_started_at is None:
                session_started_at = time.time()

            if hasattr(ic, "active"):
                ic.active = True

            scope.log_message("✅ Training läuft – Uhr wurde automatisch mit dem ersten Zug gestartet")

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

        current_hr = ant_hr_manager.get_heart_rate()

        denom_real = (end_swing_position - pole_zero_position)
        if denom_real:
            pos_real_mm = (float(swing_length) / denom_real) * (actual_position - pole_zero_position)
        else:
            pos_real_mm = 0.0

        pos_real_mm = max(0.0, min(pos_real_mm, float(swing_length)))

        pos_mm = float(swing_start_mm) + pos_real_mm
        pos_mm = max(0.0, min(pos_mm, float(MAX_TRAVEL_MM)))

        idx = int(round(pos_mm))
        idx = max(0, min(idx, len(f_push) - 1))
        torque_scale_factor = f_push[idx]

        act_torque_pct = round(min_torque_pct + (ic_torque * torque_scale_factor / 100.0))
        act_torque_pct = max(0, min(act_torque_pct, max_torque_pct))
        writeTorque(act_torque_pct)
        act_torque_array.append(act_torque_pct)

        cycle_pos_mm_array.append(pos_mm)
        cycle_power_raw_array.append(power)
        cycle_time_s_array.append(time.time())

        arr = np.array([pos_mm, speed, act_torque_pct, act_power, current_hr, cadence_spm], dtype=float)
        scope.evaluateValue(arr)

        # Robuste Richtungsbestimmung mit Deadband
        if speed > SPEED_DEADBAND:
            actual_dir = True
        elif speed < -SPEED_DEADBAND:
            actual_dir = False
        else:
            actual_dir = old_dir

        if old_dir and not actual_dir:
            previous_cycle_start_time_ms = cadence_cycle_start_time_ms
            current_time = datetime.now()
            cycle_timestamp_s = current_time.timestamp()
            cadence_cycle_start_time_ms = int(cycle_timestamp_s * 1000)
            delta = cadence_cycle_start_time_ms - previous_cycle_start_time_ms
            cadence_spm = round(60000 / delta) if delta > 0 else 0

            mean_power = safe_mean(act_power_array)
            mean_target_torque_pct = safe_mean(act_torque_array)
            swing_efficiency_pct = calculate_swing_efficiency_pct(delta, zero_power_duration)
            torque_power_index = calculate_torque_power_index(mean_power, mean_target_torque_pct)

            if cadence_spm > 100 or cadence_spm <= 0:
                cadence_spm = 0

            reference_zone_key = get_reference_zone_key(current_hr, cadence_spm, training_targets)

            push_phase_energy_j = calculate_push_phase_energy_j(
                positions_mm=cycle_pos_mm_array,
                power_values=cycle_power_raw_array,
                timestamps_s=cycle_time_s_array,
                swing_start_mm=swing_start_mm,
                swing_end_mm=swing_end_mm
            )

            reference_push_energy_j, reference_spm, reference_power_w = calculate_reference_push_energy_j(
                reference_zone_key=reference_zone_key,
                training_targets=training_targets
            )

            push_phase_utilization_pct = calculate_push_phase_utilization_pct(
                actual_energy_j=push_phase_energy_j,
                reference_energy_j=reference_push_energy_j
            )

            if cadence_spm > 0:
                distance = distance_per_stroke(
                    mean_power,
                    cadence_spm,
                    mass=weight_kg,
                    mu=mu
                ) if mean_power > 0 else 0.0
                total_distance += distance

                cycle_duration_s = max(delta / 1000.0, 1e-3)
                speed_m_s = (distance / cycle_duration_s) if distance > 0 else 0.0
                pace_s500 = int(round(500.0 / speed_m_s)) if speed_m_s > 0 else 0

                ftms_stroke_count += 1
                ftms_last_cadence_spm = float(cadence_spm)
                ftms_last_pace_s500 = int(pace_s500)
                ftms_last_power_w = float(mean_power)

                if ftms_stroke_count == 1:
                    ftms_avg_power_w = float(mean_power)
                    ftms_avg_pace_s500 = float(pace_s500)
                else:
                    n = float(ftms_stroke_count)
                    ftms_avg_power_w = ((n - 1.0) * ftms_avg_power_w + float(mean_power)) / n
                    ftms_avg_pace_s500 = ((n - 1.0) * ftms_avg_pace_s500 + float(pace_s500)) / n

                if session_started_at is not None:
                    ble_manager.update_rower_metrics(
                        stroke_rate_spm=float(cadence_spm),
                        stroke_count=ftms_stroke_count,
                        total_distance_m=float(total_distance),
                        pace_s_per_500=int(pace_s500),
                        avg_pace_s_per_500=int(round(ftms_avg_pace_s500)),
                        power_w=int(round(mean_power)),
                        avg_power_w=int(round(ftms_avg_power_w)),
                        hr_bpm=int(current_hr) if current_hr else 0,
                        elapsed_s=int(max(0, time.time() - session_started_at)),
                        running=bool(getattr(ic, "active", False)),
                    )

                scope.set_summary_values(
                    current_hr,
                    mean_power,
                    cadence_spm,
                    distance,
                    total_distance,
                    swing_efficiency_pct=swing_efficiency_pct,
                    mean_target_torque_pct=mean_target_torque_pct,
                    torque_power_index=torque_power_index,
                    push_phase_energy_j=push_phase_energy_j,
                    reference_push_energy_j=reference_push_energy_j,
                    push_phase_utilization_pct=push_phase_utilization_pct,
                    reference_zone_key=reference_zone_key,
                    reference_spm=reference_spm,
                    reference_power_w=reference_power_w
                )

                record = {
                    "timestamp": current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                    "sequence_freq": round(cadence_spm / 2),
                    "cadence_spm": cadence_spm,
                    "power": mean_power,
                    "heart_rate": current_hr,
                    "torque": act_torque_pct,
                    "distance": total_distance,
                    "swing_efficiency_pct": round(swing_efficiency_pct, 1),
                    "mean_target_torque_pct": round(mean_target_torque_pct, 1),
                    "torque_power_index": round(torque_power_index, 3),
                    "push_phase_energy_j": round(push_phase_energy_j, 2),
                    "reference_push_energy_j": round(reference_push_energy_j, 2) if reference_push_energy_j else 0.0,
                    "push_phase_utilization_pct": round(push_phase_utilization_pct, 1),
                    "reference_zone_key": reference_zone_key,
                    "reference_spm": round(reference_spm, 1) if reference_spm else None,
                    "reference_power_w": round(reference_power_w, 1) if reference_power_w else None,
                }
                records.append(record)

            old_dir = actual_dir
            zero_power_duration = 0.0
            act_power_array = []
            act_torque_array = []
            cycle_pos_mm_array = []
            cycle_power_raw_array = []
            cycle_time_s_array = []

        elif not old_dir and actual_dir:
            old_dir = actual_dir

        if hasattr(ic, "stop_requested") and ic.stop_requested:
            scope.log_message("⛔ Training wurde gestoppt")
            print("Training wurde über Webinterface gestoppt.")

            if session_started_at is not None:
                ble_manager.update_rower_metrics(
                    stroke_rate_spm=0.0,
                    stroke_count=ftms_stroke_count,
                    total_distance_m=float(total_distance),
                    pace_s_per_500=int(ftms_last_pace_s500),
                    avg_pace_s_per_500=int(round(ftms_avg_pace_s500)) if ftms_stroke_count else 0,
                    power_w=0,
                    avg_power_w=int(round(ftms_avg_power_w)) if ftms_stroke_count else 0,
                    hr_bpm=int(current_hr) if current_hr else 0,
                    elapsed_s=int(max(0, time.time() - session_started_at)),
                    running=False,
                )

            tcx_filename = f"skiErg_{formatted_time}.tcx"
            attachments = []

            if records:
                write_tcx(records, filename=tcx_filename, sport_note="SkiErg Intervalltraining")
                attachments = [tcx_filename]
            else:
                scope.log_message("ℹ️ Keine Trainingsdaten – TCX wird nicht erzeugt.")
                print("Hinweis: Keine records vorhanden – TCX-Erzeugung übersprungen.")

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
            if getattr(ic, "active", False):
                if just_started_clock:
                    pass
                elif not first_pull_detected:
                    scope.log_message("✅ Training bereit – Uhr startet automatisch mit dem ersten Zug")
                else:
                    scope.log_message("✅ Training läuft")
            else:
                scope.log_message("⏳ Warte auf Trainingsstart")

        now_mono = time.monotonic()
        if session_started_at is not None and (now_mono - ftms_last_push_monotonic) >= 0.25:
            ble_manager.update_rower_metrics(
                stroke_rate_spm=float(ftms_last_cadence_spm),
                stroke_count=ftms_stroke_count,
                total_distance_m=float(total_distance),
                pace_s_per_500=int(ftms_last_pace_s500),
                avg_pace_s_per_500=int(round(ftms_avg_pace_s500)) if ftms_stroke_count else 0,
                power_w=int(round(act_power or ftms_last_power_w)),
                avg_power_w=int(round(ftms_avg_power_w)) if ftms_stroke_count else int(round(act_power)),
                hr_bpm=int(current_hr) if current_hr else 0,
                elapsed_s=int(max(0, time.time() - session_started_at)),
                running=bool(getattr(ic, "active", False)),
            )
            ftms_last_push_monotonic = now_mono

        time.sleep(0.01)

    print("Training gestoppt oder abgebrochen")

    if session_started_at is not None:
        ble_manager.update_rower_metrics(
            stroke_rate_spm=0.0,
            stroke_count=ftms_stroke_count,
            total_distance_m=float(total_distance),
            pace_s_per_500=int(ftms_last_pace_s500),
            avg_pace_s_per_500=int(round(ftms_avg_pace_s500)) if ftms_stroke_count else 0,
            power_w=0,
            avg_power_w=int(round(ftms_avg_power_w)) if ftms_stroke_count else 0,
            hr_bpm=0,
            elapsed_s=int(max(0, time.time() - session_started_at)),
            running=False,
        )

    DriveEnable(0)
    writeSpeed(0)
    writeTorque(0)
    EnableDisableWatchDog(0)


if __name__ == "__main__":
    client1 = ModbusClient(host=drive_host, port=drive_port, unit_id=drive_unitid, auto_open=True)
    scope = Scope(
        max_hr_bpm=max_hr_bpm,
        ftp_w=ftp_w,
        training_targets=training_targets
    )

    t = Thread(target=training_thread, name="training-thread", daemon=True)
    t.start()

    app.run(host="0.0.0.0", debug=False)