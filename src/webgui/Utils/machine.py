# Utils/machine.py – Einstellungen der Maschine (gelten für alle Profile), z. B. welcher Antrieb eingebaut ist

import json
import os
from pathlib import Path

# Standardwerte des Abschnitts «drive», die nicht im Profil stehen
DRIVE_DEFAULTS = {
    "type": "m751",                 # "m751" = Nidec Digitax HD M751 (Modbus TCP), "delta_b3" = Delta ASDA-B3A-E (EtherCAT)
    "axes": 1,                      # delta_b3: 1 Motor oder 2 Motoren (links/rechts)
    "interface": "eth0",            # delta_b3: Netzwerkanschluss für EtherCAT
    "motor_rated_torque_nm": 1.27,  # delta_b3: Nenndrehmoment eines Motors (ECM-B3M-C20604: 1.27 Nm)
    "motor_max_torque_pct": 300.0,  # delta_b3: Grenze pro Motor in % des Nennmoments (Motor kann 350 %)
    "counts_per_rev": 16777216,     # delta_b3: Positionseinheiten pro Umdrehung (E-Getriebe 1:1)
    "direction_1": 1,               # delta_b3: Drehrichtung Motor 1 (1 oder -1)
    "direction_2": 1,               # delta_b3: Drehrichtung Motor 2 (gleich eingebaut wie Motor 1)
    "sto_wired": False,             # delta_b3: Sicherheitsschalter an CN10 angeschlossen
    "cycle_ms": 10.0,               # delta_b3: Takt von EtherCAT und Regelschleife
    "dc_sync": False,               # delta_b3: Distributed Clocks (nur falls der Antrieb es verlangt)
}
DRIVE_TYPES = {"m751": "Nidec Digitax HD M751 (1 Motor)", "delta_b3": "Delta ASDA-B3A-E (EtherCAT)"}


def machine_path() -> Path:
    return Path(os.environ.get("X_SKI_MACHINE_FILE") or Path(__file__).resolve().parents[1] / "maschine.json")


# Abschnitte, die für die Maschine gelten (alle Profile) und in maschine.json stehen
MACHINE_SECTIONS = ("drive", "hardware")


def load_section(section: str) -> dict:
    """Maschinenweite Werte eines Abschnitts aus maschine.json (leer, wenn die Datei fehlt)."""
    try:
        return dict(json.loads(machine_path().read_text(encoding="utf-8")).get(section) or {})
    except (OSError, ValueError):
        return {}


def load_drive() -> dict:
    return load_section("drive")


def save_drive(values: dict) -> None:
    save_section("drive", values)


def save_section(section: str, values: dict) -> None:
    path = machine_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault(section, {}).update(values)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def hardware_config(profile_hardware: dict) -> dict:
    """Abschnitt «hardware» (Trommel, Seil, Montagehöhe …): Profil, darüber maschine.json."""
    return {**(profile_hardware or {}), **load_section("hardware")}


def section_config(section: str, profile_values: dict) -> dict:
    if section == "drive":
        return drive_config(profile_values)
    if section == "hardware":
        return hardware_config(profile_values)
    return dict(profile_values or {})


def drive_config(profile_drive: dict) -> dict:
    """Abschnitt «drive»: Standardwerte, darüber das Profil (Adresse des M751), darüber maschine.json."""
    return {**DRIVE_DEFAULTS, **(profile_drive or {}), **load_drive()}
