# HardwareController/DriveM751.py – Modbus-TCP-Zugriff auf den Nidec Digitax HD M751

import time
from typing import Optional

from pyModbusTCP import utils
from pyModbusTCP.client import ModbusClient

# Register (Modbus-Adresse) gemäss M751-Parameterliste
REG_SPEED_REF = 117
REG_ACTUAL_SPEED = 301
REG_POSITION = 327          # 2 Register (32 bit)
REG_CURRENT_LIMIT = 404
REG_TORQUE_REF = 407
REG_LOAD = 419
REG_POWER = 502
REG_DRIVE_ENABLE = 614
REG_FORWARD_DIRECTION = 629
REG_HARDWARE_ENABLE = 628
REG_WATCHDOG_TOGGLE = 641      # Pr 06.042 Steuerwort, Bit 14 = Watchdog
REG_WATCHDOG_ENABLE = 642      # Pr 06.043 Steuerwort-Freigabe
WATCHDOG_BIT = 16384           # Bit 14
REG_DRIVE_HEALTHY = 1000
REG_DRIVE_RUNNING = 1001
REG_DRIVE_RESET = 1032
REG_SAVE_FORWARD_LIMIT = 1209
REG_FORWARD_LIMIT_ENABLE = 1235
REG_THERMAL_PROTECTION_MODE = 415  # Pr 04.016 Thermischer Schutzmodus
REG_MOTOR_OVERLOAD = 418       # Pr 04.019 Motor-Überlastakkumulator [0.1 %]
REG_BRAKE_RESISTOR_LOAD = 1038  # Pr 10.039 Bremsenergie-Akkumulator [0.1 %]


def uint16_to_int16(uint16: int) -> int:
    if uint16 >= 2**15:
        return uint16 - 2**16
    return uint16


class DriveM751:
    # Gecachte Werte werden spätestens nach dieser Zeit erneut geschrieben,
    # damit ein verlorener Schreibzugriff nicht dauerhaft wirkt.
    RESEND_INTERVAL_S = 0.5
    # Pr 06.042 Bit 14 muss spätestens alle 1 s von 0 auf 1 wechseln (sonst Fehler 30 "Watchdog").
    # Ein Schreibzugriff pro Halbperiode -> steigende Flanke alle 2 × 50 ms = 100 ms (10-fache Reserve).
    WATCHDOG_HALF_PERIOD_S = 0.05

    def __init__(self, host: str, port: int, unit_id: int, max_torque_pct: float):
        self._client = ModbusClient(host=host, port=port, unit_id=unit_id, auto_open=True)
        self.max_torque_pct = float(max_torque_pct)

        self._last_enable: Optional[int] = None
        self._last_enable_t = 0.0
        self._last_torque_raw: Optional[int] = None
        self._last_torque_t = 0.0

        self._watchdog_bit_high = True   # nächster Schreibzugriff setzt 0, danach 1 -> Flanke
        self._watchdog_t = 0.0

    # ---------------------- Low level ----------------------
    def _write(self, addr: int, value: int):
        return self._client.write_single_register(addr, int(value))

    def _read1(self, addr: int) -> Optional[int]:
        vals = self._client.read_holding_registers(addr, 1)
        return vals[0] if vals else None

    def _read_flag(self, addr: int) -> bool:
        v = self._read1(addr)
        return v == 1 if v is not None else False

    # ---------------------- Schreiben ----------------------
    def reset(self):
        self._write(REG_DRIVE_RESET, 1)
        self._write(REG_DRIVE_RESET, 0)
        self._write(REG_DRIVE_RESET, 1)

    def set_watchdog_enabled(self, enabled: bool):
        self._write(REG_WATCHDOG_ENABLE, int(enabled))

    def toggle_watchdog(self):
        self._write(REG_WATCHDOG_TOGGLE, 0)
        self._write(REG_WATCHDOG_TOGGLE, WATCHDOG_BIT)

    def service_watchdog(self):
        """In jedem Regelzyklus aufrufen: schreibt höchstens alle WATCHDOG_HALF_PERIOD_S
        abwechselnd 0 bzw. Bit 14 (statt zwei Schreibzugriffen in jedem Zyklus)."""
        now = time.monotonic()
        if now - self._watchdog_t < self.WATCHDOG_HALF_PERIOD_S:
            return
        self._watchdog_bit_high = not self._watchdog_bit_high
        self._write(REG_WATCHDOG_TOGGLE, WATCHDOG_BIT if self._watchdog_bit_high else 0)
        self._watchdog_t = now

    def set_current_limit(self, limit: float):
        self._write(REG_CURRENT_LIMIT, int(limit * 10))

    def _torque_raw(self, torque_pct: float) -> int:
        torque_pct = max(0.0, min(float(torque_pct), self.max_torque_pct))
        return int(torque_pct * 100)

    def set_torque(self, torque_pct: float):
        raw = self._torque_raw(torque_pct)
        self._write(REG_TORQUE_REF, raw)
        self._last_torque_raw = raw
        self._last_torque_t = time.monotonic()

    def update_torque(self, torque_pct: float):
        """Wie set_torque, schreibt aber nur bei Änderung bzw. nach RESEND_INTERVAL_S."""
        raw = self._torque_raw(torque_pct)
        now = time.monotonic()
        if raw != self._last_torque_raw or now - self._last_torque_t >= self.RESEND_INTERVAL_S:
            self._write(REG_TORQUE_REF, raw)
            self._last_torque_raw = raw
            self._last_torque_t = now

    THERMAL_MODE_MOTOR_LIMIT = 1  # 0 = Abschalten (Motor Too Hot), 1 = Strom begrenzen statt abschalten

    def set_thermal_protection_mode(self, mode: int) -> Optional[int]:
        """Pr 04.016 setzen (nur flüchtig, nicht im Drive gespeichert) und zur Kontrolle zurücklesen."""
        self._write(REG_THERMAL_PROTECTION_MODE, int(mode))
        return self._read1(REG_THERMAL_PROTECTION_MODE)

    def set_speed(self, speed: float):
        self._write(REG_SPEED_REF, int(speed * 10))

    def set_enabled(self, enabled: bool):
        value = int(enabled)
        self._write(REG_DRIVE_ENABLE, value)
        self._last_enable = value
        self._last_enable_t = time.monotonic()

    def update_enabled(self, enabled: bool):
        """Wie set_enabled, schreibt aber nur bei Änderung bzw. nach RESEND_INTERVAL_S."""
        value = int(enabled)
        now = time.monotonic()
        if value != self._last_enable or now - self._last_enable_t >= self.RESEND_INTERVAL_S:
            self._write(REG_DRIVE_ENABLE, value)
            self._last_enable = value
            self._last_enable_t = now

    def set_forward_direction(self, direction: int):
        self._write(REG_FORWARD_DIRECTION, int(direction))

    def set_forward_limit_enabled(self, enabled: bool):
        self._write(REG_FORWARD_LIMIT_ENABLE, int(enabled))

    def save_forward_limit_position(self):
        self._write(REG_SAVE_FORWARD_LIMIT, 0)
        time.sleep(0.1)
        self._write(REG_SAVE_FORWARD_LIMIT, 1)

    # ---------------------- Lesen ----------------------
    def is_healthy(self) -> bool:
        return self._read_flag(REG_DRIVE_HEALTHY)

    def is_running(self) -> bool:
        return self._read_flag(REG_DRIVE_RUNNING)

    def hardware_enabled(self) -> bool:
        """False, wenn der Sicherheitsschalter (STO) ausgelöst ist oder der Drive nicht antwortet."""
        return self._read_flag(REG_HARDWARE_ENABLE)

    def read_position(self) -> Optional[int]:
        """Encoderposition (65536 Inkremente pro Umdrehung) oder None bei einem Lesefehler."""
        p12 = self._client.read_holding_registers(REG_POSITION, 2)
        if not p12:
            return None
        long_vals = utils.word_list_to_long(p12)
        return long_vals[0] if long_vals else None

    def read_speed(self) -> float:
        v = self._read1(REG_ACTUAL_SPEED)
        return uint16_to_int16(v) / 10 if v is not None else 0.0

    def read_load(self) -> float:
        v = self._read1(REG_LOAD)
        return uint16_to_int16(v) / 10 if v is not None else 0.0

    def read_motor_overload_pct(self) -> Optional[float]:
        """Thermische Auslastung des Motors laut Drive (100 % = Schutzgrenze)."""
        v = self._read1(REG_MOTOR_OVERLOAD)
        return v / 10.0 if v is not None else None

    def read_brake_resistor_pct(self) -> Optional[float]:
        """Thermische Auslastung des Bremswiderstands laut Drive (100 % = Schutzgrenze)."""
        v = self._read1(REG_BRAKE_RESISTOR_LOAD)
        return v / 10.0 if v is not None else None

    def read_power(self) -> int:
        v = self._read1(REG_POWER)
        return uint16_to_int16(v) if v is not None else 0

    # ---------------------- Abläufe ----------------------
    def wait_until_ready(self):
        print("Warte auf Drive-Start ...")
        while not self.is_healthy():
            print("Drive nicht bereit", end="\r")
            self.reset()
            time.sleep(0.2)
        print("Drive bereit.")

    def wait_for_sto_off(self):
        print("Warte auf STO-Auslösung ...")
        while self.hardware_enabled():
            print("Bitte STO lösen", end="\r")
            time.sleep(0.1)
        print("STO ist aus.")

    def wait_for_sto_on(self):
        print("Warte auf STO-Einschaltung ...")
        while not self.hardware_enabled():
            print("Bitte STO drücken", end="\r")
            time.sleep(0.1)
        print("STO ist eingeschaltet.")

    def calibrate_end_position(self, current_limit, calib_torque_pct, calib_speed):
        print("Kalibriere Endposition ...")
        time.sleep(1)
        self.set_enabled(True)
        self.set_forward_direction(1)
        self.set_current_limit(current_limit)
        self.set_torque(calib_torque_pct)
        self.set_speed(calib_speed)
        time.sleep(0.5)
        while self.read_speed() > 0:
            time.sleep(0.01)
        self.set_enabled(False)
        self.set_forward_direction(0)
        self.save_forward_limit_position()
        self.set_forward_limit_enabled(True)
        print("Kalibrierung abgeschlossen.")

    def shutdown(self):
        """Antrieb in sicheren Zustand bringen. Jeder Schritt wird einzeln versucht,
        damit ein Kommunikationsfehler die übrigen Schritte nicht verhindert."""
        steps = (
            ("Drive Disable", lambda: self.set_enabled(False)),
            ("Speed 0", lambda: self.set_speed(0)),
            ("Torque 0", lambda: self.set_torque(0)),
            ("Watchdog aus", lambda: self.set_watchdog_enabled(False)),
        )
        for name, step in steps:
            try:
                step()
            except Exception as e:
                print(f"❌ Abschalten: '{name}' fehlgeschlagen: {e}")
