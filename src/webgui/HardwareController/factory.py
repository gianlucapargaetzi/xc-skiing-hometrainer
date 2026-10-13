# HardwareController/factory.py – den eingestellten Antrieb erzeugen (Einstellung drive.type)


def create_drive(settings):
    """Antrieb laut Einstellungen. Beide Klassen bieten der Regelschleife dieselben Methoden:
    Drehmoment in % des Bezugsdrehmoments, Position in 65536 Schritten pro Umdrehung, Drehzahl in rpm."""
    if settings.drive_type == "delta_b3":
        from HardwareController.DriveDeltaB3 import DriveDeltaB3
        return DriveDeltaB3(
            axes=settings.drive_axes,
            interface=settings.drive_interface,
            max_torque_pct=settings.max_torque_pct,
            reference_torque_nm=settings.motor_rated_torque_nm,
            motor_rated_torque_nm=settings.drive_motor_rated_torque_nm,
            motor_max_torque_pct=settings.drive_motor_max_torque_pct,
            counts_per_rev=settings.drive_counts_per_rev,
            directions=settings.drive_directions,
            sto_wired=settings.drive_sto_wired,
            cycle_ms=settings.drive_cycle_ms,
            dc_sync=settings.drive_dc_sync,
        )
    if settings.drive_type != "m751":
        raise ValueError(f"Unbekannter Antrieb «{settings.drive_type}» (erlaubt: m751, delta_b3).")
    from HardwareController.DriveM751 import DriveM751
    return DriveM751(host=settings.drive_host, port=settings.drive_port, unit_id=settings.drive_unit_id,
                     max_torque_pct=settings.max_torque_pct)
