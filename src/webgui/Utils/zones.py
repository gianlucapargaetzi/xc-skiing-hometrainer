# Utils/zones.py – Zuordnung von Herzfrequenz / Kadenz zu Trainingszonen (z1..z5)

from typing import Optional

ZONE_KEYS = ("z1", "z2", "z3", "z4", "z5")


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_hr_zone_key(hr_value, training_targets) -> Optional[str]:
    """Höchste Zone, deren low_bpm erreicht ist; None unterhalb von z1 oder ohne Zonen."""
    hr_zones = (training_targets or {}).get("hr_zones", {})
    hr_value = _to_float(hr_value)
    if not hr_zones or hr_value is None:
        return None

    for key in reversed(ZONE_KEYS):
        low = hr_zones.get(key, {}).get("low_bpm")
        if low is not None and hr_value >= low:
            return key
    return None


def get_spm_zone_key(cadence_spm, training_targets) -> Optional[str]:
    """Niedrigste Zone, deren high_spm nicht überschritten ist; darüber z5."""
    spm_zones = (training_targets or {}).get("skierg_spm_zones", {})
    cadence_spm = _to_float(cadence_spm)
    if not spm_zones or cadence_spm is None:
        return None

    for key in ZONE_KEYS[:-1]:
        high = spm_zones.get(key, {}).get("high_spm")
        if high is not None and cadence_spm <= high:
            return key
    return "z5"


def get_reference_zone_key(current_hr, cadence_spm, training_targets) -> Optional[str]:
    zone_key = get_hr_zone_key(current_hr, training_targets)
    if zone_key:
        return zone_key
    return get_spm_zone_key(cadence_spm, training_targets)
