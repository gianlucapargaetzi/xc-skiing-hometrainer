import math


def distance_per_stroke(power_w, cadence_spm, mass=75.0, mu=0.02) -> float:
    """
    Einfache Distanzabschätzung pro Zug auf Basis von:
    - Leistung [W]
    - Kadenz [spm]
    - Masse [kg]
    - Reibkoeffizient [-]
    """
    if power_w is None or power_w <= 0:
        return 0.0

    if cadence_spm is None or cadence_spm <= 0:
        return 0.0

    if mass <= 0 or mu <= 0:
        return 0.0

    g = 9.81
    cadence_hz = float(cadence_spm) / 60.0
    stroke_time_s = 1.0 / cadence_hz

    work_j = float(power_w) * stroke_time_s
    friction_force_n = float(mu) * float(mass) * g

    if friction_force_n <= 0:
        return 0.0

    distance_m = work_j / friction_force_n
    return max(distance_m, 0.0)


def distance_per_stroke_dynamic(
    power_w,
    mass=75.0,
    mu=0.02,
    cadence_spm=48.0,
    T_s=0.3,
    s_s=1.1,
    slope_percent=0.0,
    k=3.6
) -> float:
    """
    Erweiterte Distanzabschätzung pro Zug.

    Aktuell konservativ umgesetzt:
    - Leistung
    - Reibung
    - Steigung

    T_s, s_s und k bleiben vorerst als Platzhalter für spätere Verfeinerungen erhalten.
    """
    if power_w is None or power_w <= 0:
        return 0.0

    if cadence_spm is None or cadence_spm <= 0:
        return 0.0

    if mass <= 0 or mu < 0:
        return 0.0

    g = 9.81
    cadence_hz = float(cadence_spm) / 60.0
    cycle_time_s = 1.0 / cadence_hz

    if cycle_time_s <= 0:
        return 0.0

    work_j = float(power_w) * cycle_time_s

    theta_rad = math.atan(float(slope_percent) / 100.0)
    friction_force_n = float(mu) * float(mass) * g
    slope_force_n = float(mass) * g * math.sin(theta_rad)
    total_resisting_force_n = friction_force_n + slope_force_n

    if total_resisting_force_n <= 0:
        return 0.0

    distance_m = work_j / total_resisting_force_n
    return max(distance_m, 0.0)