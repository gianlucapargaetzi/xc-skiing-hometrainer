
import math


def distance_per_cycle(P, sequence_freq, mass=75, mu=0.02)->float:
    g = 9.81
    
    cadence_hz = sequence_freq / 60.0
    T = 1/cadence_hz

    W = P*T

    F = mu * mass * g

    ds = W/F
    return ds

def distance_per_cycle_dynamic(P, mass=75.0, mu=0.02, cadence_rpm=48.0,
                                T_s=0.3, s_s=1.1, slope_percent=0.0, k=3.6):
    """
    Realistisch kalibrierte Distanzberechnung pro Doppelstock-Zyklus.
    """
    # g = 9.81
    # if cadence_rpm > 0:
    #     cadence_hz = cadence_rpm / 60.0
    #     T = 1.0 / cadence_hz
    # else:
    #     T = T_s

    # if T == 0:
    #     return 0


    # T_g = T - T_s
    # E = P * T

    # F_reib = mu * mass * g
    # theta_rad = math.atan(slope_percent / 100.0)
    # F_slope = mass * g * math.sin(theta_rad)
    # F_total = F_reib + F_slope

    # E_s = E * (T_s / T)
    # F_eff = k * E_s / s_s   # Skalierter Schub

    # a_s = (F_eff - F_total) / mass
    # v_s = a_s * T_s

    # a_g = -F_total / mass
    # s_g = v_s * T_g + 0.5 * a_g * T_g**2

    # return max(s_s + s_g, 0)