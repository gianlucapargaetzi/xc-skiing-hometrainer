# Utils/force_profile.py – positionsabhängige Bremskurve (Double Poling)

import numpy as np

# Formparameter für realistischeren Double-Poling-Verlauf
SHAPE_A = 0.8
SHAPE_B = 1.35


def moving_average_filter(data, n):
    if n <= 1:
        return data
    kernel = np.ones(n) / n
    return np.convolve(data, kernel, mode="same")


def build_force_profile_absolute(
    total_length_mm,
    swing_start_mm,
    swing_end_mm,
    min_torque_value=0.0,
    max_torque_value=100.0,
    smooth_window=1,
):
    """
    Double-Poling-ähnliche Bremskurve, Index = Position in mm:
    - vor swing_start_mm: min_torque_value
    - ab swing_start_mm: steiler Aufbau
    - Peak früh bis mittig
    - breiter, kontrollierter Abfall
    - bei swing_end_mm: zurück auf min_torque_value
    """
    total_length_mm = max(int(total_length_mm), 1)
    swing_start_mm = int(max(0, min(swing_start_mm, total_length_mm - 1)))
    swing_end_mm = int(max(swing_start_mm + 1, min(swing_end_mm, total_length_mm)))

    f_push = np.full(total_length_mm + 1, float(min_torque_value), dtype=float)

    x = np.arange(total_length_mm + 1, dtype=float)
    u = (x - swing_start_mm) / float(swing_end_mm - swing_start_mm)

    mask = (u >= 0.0) & (u <= 1.0)
    shape = np.zeros_like(x, dtype=float)
    shape[mask] = (u[mask] ** SHAPE_A) * ((1.0 - u[mask]) ** SHAPE_B)

    shape_max = shape.max() if shape.max() > 0 else 1.0
    shape /= shape_max

    f_push[mask] = min_torque_value + (max_torque_value - min_torque_value) * shape[mask]
    f_push = np.clip(f_push, min_torque_value, max_torque_value)

    if smooth_window and smooth_window > 1:
        f_push = moving_average_filter(f_push, min(int(smooth_window), len(f_push)))
        f_push = np.clip(f_push, min_torque_value, max_torque_value)

    return f_push


def target_torque_pct(profile_value, min_torque_pct, intensity_pct, max_torque_pct):
    """Soll-Drehmoment [%] für einen Profilwert (0..100) bei gegebener Intensität."""
    target = min_torque_pct + (intensity_pct * profile_value / 100.0)
    return np.clip(target, min_torque_pct, max_torque_pct)


def build_target_torque_curve_absolute(
    total_length_mm,
    swing_start_mm,
    swing_end_mm,
    min_torque_pct_value,
    current_intensity_value,
    max_torque_limit_value,
    smooth_window=1,
):
    base_profile = build_force_profile_absolute(
        total_length_mm=total_length_mm,
        swing_start_mm=swing_start_mm,
        swing_end_mm=swing_end_mm,
        min_torque_value=0.0,
        max_torque_value=100.0,
        smooth_window=smooth_window,
    )
    return target_torque_pct(base_profile, min_torque_pct_value, current_intensity_value, max_torque_limit_value)
