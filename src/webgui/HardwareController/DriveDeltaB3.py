# HardwareController/DriveDeltaB3.py – EtherCAT-Zugriff auf Delta ASDA-B3A-E (ein oder zwei Motoren)
#
# Stand: vorbereitet nach dem Benutzerhandbuch ASDA-B3 (Kap. 12 «EtherCAT Mode»), an der Hardware noch
# NICHT getestet. Die Klasse hat dieselben Methoden wie DriveM751, damit die Regelschleife in x-ski.py
# unverändert bleibt:
#   - Drehmoment in «x-ski-Prozent»: 100 % = Bezugsdrehmoment (simulation.motor_rated_torque_nm) als
#     Summe über alle Seile. Bei zwei Motoren bekommt jeder die Hälfte. Grundzug, Rückzug und Stosskraft
#     fühlen sich damit gleich an wie mit dem Nidec-Antrieb.
#   - Position in 65536 Schritten pro Umdrehung, Rückzug (Seil läuft ein) zählt aufwärts.
#   - Drehzahl in rpm, Rückzug positiv; Leistung in W, beim Ziehen negativ.
# Bei zwei Motoren sieht die Regelschleife den Mittelwert beider Seile (Double Poling). Eine getrennte
# Regelung pro Arm (echter Diagonalschritt) baut später darauf auf – die Werte pro Achse stehen in axis_values().

import struct
import threading
import time
from typing import List, Optional, Sequence

MODE_CST = 10                    # OD 6060h: Cyclic Synchronous Torque
RX_FORMAT = "<Hhb"               # 6040h Controlword, 6071h Solldrehmoment [0.1 %], 6060h Betriebsart
TX_FORMAT = "<HiihHb"            # 6041h Statusword, 6064h Position, 606Ch Drehzahl [0.1 rpm],
#                                  6077h Istdrehmoment [0.1 %], 603Fh Fehlercode, 6061h Betriebsart
RX_MAPPING = ((0x6040, 16), (0x6071, 16), (0x6060, 8))
TX_MAPPING = ((0x6041, 16), (0x6064, 32), (0x606C, 32), (0x6077, 16), (0x603F, 16), (0x6061, 8))
OD_ALARM = 0x2001                # P0.001: aktueller Alarm (AL-Nummer, z. B. 0x500 = STO)
STO_ALARMS = (0x500, 0x501, 0x502)

SW_FAULT = 0x0008
CW_SHUTDOWN, CW_SWITCH_ON, CW_ENABLE, CW_FAULT_RESET = 0x06, 0x07, 0x0F, 0x80


def controlword_for(statusword: int, want_enabled: bool, reset_fault: bool) -> int:
    """CiA-402-Zustandsautomat: nächstes Controlword aus dem Statusword."""
    if statusword & SW_FAULT:
        return CW_FAULT_RESET if reset_fault else 0
    if not want_enabled:
        return CW_SHUTDOWN                       # Endstufe aus, Motor frei
    state = statusword & 0x6F
    if state == 0x21:                            # Ready to switch on
        return CW_SWITCH_ON
    if state in (0x23, 0x27):                    # Switched on / Operation enabled
        return CW_ENABLE
    return CW_SHUTDOWN                           # Switch on disabled -> Shutdown


class EthercatBus:
    """Dünne Hülle um pysoem: Slaves suchen, PDO-Zuordnung setzen, zyklisch Daten tauschen."""

    def __init__(self, interface: str, axes: int, dc_sync: bool, cycle_s: float):
        self.interface, self.axes, self.dc_sync, self.cycle_s = interface, axes, dc_sync, cycle_s
        self._master = None
        self._soem = None

    def open(self):
        try:
            import pysoem
        except ImportError as e:
            raise RuntimeError("Für den Delta-Antrieb fehlt das Paket pysoem (pip install pysoem).") from e
        self._soem = pysoem
        master = pysoem.Master()
        try:
            master.open(self.interface)
        except Exception as e:
            raise RuntimeError(f"EtherCAT: Schnittstelle {self.interface} lässt sich nicht öffnen ({e}). "
                               "Python braucht dafür das Recht CAP_NET_RAW (siehe README).") from e
        found = master.config_init()
        if found < self.axes:
            master.close()
            raise RuntimeError(f"EtherCAT: {found} Antrieb(e) an {self.interface} gefunden, eingestellt sind {self.axes}.")
        self._master = master
        for slave in master.slaves[:self.axes]:
            slave.config_func = self._configure_pdo
        master.config_map()
        if self.dc_sync:
            master.config_dc()
            for slave in master.slaves[:self.axes]:
                slave.dc_sync(True, int(self.cycle_s * 1e9))
        if master.state_check(pysoem.SAFEOP_STATE, 2_000_000) != pysoem.SAFEOP_STATE:
            raise RuntimeError("EtherCAT: Antriebe erreichen SAFE-OP nicht (PDO-Zuordnung prüfen).")
        master.state = pysoem.OP_STATE
        master.write_state()
        for _ in range(200):                      # OP braucht laufende Prozessdaten
            master.send_processdata()
            master.receive_processdata(2000)
            if master.state_check(pysoem.OP_STATE, 5000) == pysoem.OP_STATE:
                return
        raise RuntimeError("EtherCAT: Antriebe erreichen OP nicht.")

    def _configure_pdo(self, slave_pos: int):
        """Im Zustand PRE-OP: eine eigene, kurze PDO-Zuordnung in 1600h/1A00h (Handbuch 12.2.4.2)."""
        slave = self._master.slaves[slave_pos]
        u8, u16, u32 = (lambda v: struct.pack("<B", v)), (lambda v: struct.pack("<H", v)), (lambda v: struct.pack("<I", v))
        slave.sdo_write(0x1C12, 0, u8(0))
        slave.sdo_write(0x1C13, 0, u8(0))
        for index, mapping in ((0x1600, RX_MAPPING), (0x1A00, TX_MAPPING)):
            slave.sdo_write(index, 0, u8(0))
            for sub, (obj, bits) in enumerate(mapping, start=1):
                slave.sdo_write(index, sub, u32(obj << 16 | bits))
            slave.sdo_write(index, 0, u8(len(mapping)))
        slave.sdo_write(0x1C12, 1, u16(0x1600))
        slave.sdo_write(0x1C13, 1, u16(0x1A00))
        slave.sdo_write(0x1C12, 0, u8(1))
        slave.sdo_write(0x1C13, 0, u8(1))
        slave.sdo_write(0x6060, 0, struct.pack("<b", MODE_CST))

    def exchange(self, outputs: Sequence[bytes]) -> Optional[List[bytes]]:
        """Einen Zyklus Prozessdaten tauschen; None, wenn nicht alle Antriebe geantwortet haben."""
        master = self._master
        for slave, data in zip(master.slaves, outputs):
            slave.output = data
        master.send_processdata()
        wkc = master.receive_processdata(2000)
        if wkc < master.expected_wkc:
            return None
        return [bytes(slave.input) for slave in master.slaves[:self.axes]]

    def read_alarm(self, axis: int) -> Optional[int]:
        try:
            return struct.unpack("<H", self._master.slaves[axis].sdo_read(OD_ALARM, 0)[:2])[0]
        except Exception:
            return None

    def close(self):
        if self._master is None:
            return
        try:
            self._master.state = self._soem.INIT_STATE
            self._master.write_state()
        finally:
            self._master.close()
            self._master = None


class DriveDeltaB3:
    COUNTS_PER_REV = 65536           # Auflösung nach aussen (wie DriveM751)
    APP_WATCHDOG_S = 1.0             # ohne service_watchdog() so lange -> Drehmoment 0, Endstufe aus
    BUS_LOST_CYCLES = 20             # so viele Zyklen ohne Antwort -> Antrieb gilt als ausgefallen
    SPEED_TAPER = 0.1                # Drehmoment fällt von 100 % auf 0 zwischen Grenze und Grenze × 1.1
    STOP_SPEED_RPM = 3.0             # Endlage: Achse steht, wenn sie so langsam ist ...
    STOP_HOLD_S = 0.3                # ... und zwar so lange
    HOMING_TIMEOUT_S = 30.0
    POSITION_BASE = 10_000_000       # Position der Endlage nach der Kalibrierung (wie beim M751 weit im Positiven)

    def __init__(self, *, axes: int, interface: str, max_torque_pct: float, reference_torque_nm: float,
                 motor_rated_torque_nm: float, motor_max_torque_pct: float, counts_per_rev: int,
                 directions: Sequence[int], sto_wired: bool, cycle_ms: float, dc_sync: bool = False, bus=None):
        if axes not in (1, 2):
            raise ValueError("Delta-Antrieb: 1 oder 2 Achsen.")
        if reference_torque_nm <= 0 or motor_rated_torque_nm <= 0:
            raise ValueError("Delta-Antrieb: Bezugsdrehmoment und Motor-Nenndrehmoment müssen grösser als 0 sein.")
        self.axes = axes
        self.max_torque_pct = float(max_torque_pct)
        self.sto_wired = bool(sto_wired)
        self.cycle_s = max(0.002, float(cycle_ms) / 1000.0)
        self._directions = [1 if int(d) >= 0 else -1 for d in (list(directions) + [1, 1])[:axes]]
        # x-ski-Prozent -> Rohwert 6071h (0.1 % des Motor-Nenndrehmoments) pro Achse
        self._raw_per_pct = reference_torque_nm / axes / motor_rated_torque_nm * 10.0
        self._raw_limit = int(motor_max_torque_pct * 10)
        self._motor_nm = motor_rated_torque_nm
        self._reference_nm = reference_torque_nm
        self._count_scale = self.COUNTS_PER_REV / float(counts_per_rev)
        self._bus = bus or EthercatBus(interface, axes, dc_sync, self.cycle_s)

        self._lock = threading.Lock()
        self._fresh = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._want_enabled = False
        self._reset_fault = False
        self._torque_pct = 0.0
        self._speed_limit_rpm = 0.0
        self._watchdog_enabled = False
        self._watchdog_t = time.monotonic()
        self._watchdog_tripped = False
        self._missed = 0
        self._bus_ok = False
        zero = [0] * axes
        self._status, self._raw_pos, self._alarm = list(zero), list(zero), [None] * axes
        self._rpm, self._torque_nm = [0.0] * axes, [0.0] * axes
        self._home = [0.0] * axes                # Position der Endlage pro Achse (65536er-Schritte)

    # ---------------------- Zyklus (eigener Thread) ----------------------
    def _start(self):
        if self._thread is not None:
            return
        self._bus.open()
        self._running, self._bus_ok = True, True
        self._thread = threading.Thread(target=self._cycle_loop, name="ethercat-cycle", daemon=True)
        self._thread.start()

    def _cycle_loop(self):
        next_t = time.monotonic()
        while self._running:
            self._cycle()
            next_t += self.cycle_s
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()        # Zyklus überzogen: nicht aufholen

    def _axis_raw_torque(self, axis: int, enabled: bool) -> int:
        """Solldrehmoment der Achse: nur bei freigegebener Endstufe, mit Drehzahlgrenze beim Rückzug."""
        if not enabled or (self._status[axis] & 0x6F) != 0x27:
            return 0
        limit = self._speed_limit_rpm
        if limit <= 0:
            return 0
        over = self._rpm[axis] - limit           # Rückzug ist positiv; beim Ziehen (negativ) keine Begrenzung
        factor = max(0.0, 1.0 - over / (limit * self.SPEED_TAPER)) if over > 0 else 1.0
        raw = int(round(self._torque_pct * self._raw_per_pct * factor))
        return self._directions[axis] * max(0, min(raw, self._raw_limit))

    def _cycle(self):
        now = time.monotonic()
        with self._lock:
            if self._watchdog_enabled and now - self._watchdog_t > self.APP_WATCHDOG_S and not self._watchdog_tripped:
                self._watchdog_tripped = True
                print("❌ Antrieb: Regelschleife antwortet nicht – Drehmoment 0, Endstufe aus")
            enabled = self._want_enabled and not self._watchdog_tripped
            outputs = [struct.pack(RX_FORMAT, controlword_for(self._status[a], enabled, self._reset_fault),
                                   self._axis_raw_torque(a, enabled), MODE_CST) for a in range(self.axes)]
        try:
            inputs = self._bus.exchange(outputs)
        except Exception as e:
            inputs = None
            if self._bus_ok:
                print(f"❌ EtherCAT: {e}")
        if inputs is None:
            self._missed += 1
            if self._missed >= self.BUS_LOST_CYCLES and self._bus_ok:
                self._bus_ok = False
                print("❌ EtherCAT: keine Antwort der Antriebe")
            self._fresh.set()
            return
        self._missed = 0
        new_faults = []
        with self._lock:
            self._bus_ok = True
            for a, data in enumerate(inputs):
                status, pos, speed, torque, _error, _mode = struct.unpack(TX_FORMAT, data[:struct.calcsize(TX_FORMAT)])
                if status & SW_FAULT and not self._status[a] & SW_FAULT:
                    new_faults.append(a)
                if not status & SW_FAULT:
                    self._alarm[a] = None
                self._status[a], self._raw_pos[a] = status, pos
                self._rpm[a] = self._directions[a] * speed / 10.0
                self._torque_nm[a] = self._directions[a] * torque / 1000.0 * self._motor_nm
        for a in new_faults:                      # Alarmnummer einmal pro Störung holen (Mailbox, langsam)
            alarm = self._bus.read_alarm(a)
            self._alarm[a] = alarm
            name = "STO (Sicherheitsschalter)" if alarm in STO_ALARMS else "Störung"
            print(f"⚠️ Antrieb {a + 1}: {name}, Alarm {'?' if alarm is None else f'AL{alarm:03X}'}")
        self._fresh.set()

    # ---------------------- Schreiben ----------------------
    def reset(self):
        with self._lock:
            self._watchdog_t = time.monotonic()
            self._watchdog_tripped = False
        self._reset_fault = True
        time.sleep(4 * self.cycle_s)
        self._reset_fault = False
        time.sleep(4 * self.cycle_s)

    def set_watchdog_enabled(self, enabled: bool):
        with self._lock:
            self._watchdog_t = time.monotonic()
            self._watchdog_tripped = False
            self._watchdog_enabled = bool(enabled)

    def service_watchdog(self):
        self._watchdog_t = time.monotonic()

    toggle_watchdog = service_watchdog

    def set_torque(self, torque_pct: float):
        self._torque_pct = max(0.0, min(float(torque_pct), self.max_torque_pct))

    update_torque = set_torque

    def set_speed(self, speed: float):
        """Höchste Drehzahl beim Rückzug [rpm]; 0 = kein Drehmoment."""
        self._speed_limit_rpm = max(0.0, float(speed))

    def set_enabled(self, enabled: bool):
        self._want_enabled = bool(enabled)

    update_enabled = set_enabled

    # Beim M751 nötig, beim Delta ohne Entsprechung: Drehrichtung und Grenzen stehen in der Konfiguration,
    # die Endlage merkt sich die Software (calibrate_end_position).
    def set_current_limit(self, limit: float): pass
    def set_forward_direction(self, direction: int): pass
    def set_forward_limit_enabled(self, enabled: bool): pass
    def save_forward_limit_position(self): pass

    def configure_protection(self) -> str:
        return (f"🌡️ Motorschutz: Überlastschutz des Delta-Antriebs, Drehmoment pro Motor auf "
                f"{self._raw_limit / 10:.0f} % des Nennmoments begrenzt")

    # ---------------------- Lesen ----------------------
    def _faulted(self) -> bool:
        return any(s & SW_FAULT for s in self._status)

    def is_healthy(self) -> bool:
        return self._bus_ok and not self._faulted() and not self._watchdog_tripped

    def is_running(self) -> bool:
        return self._bus_ok and all((s & 0x6F) == 0x27 for s in self._status)

    def hardware_enabled(self) -> bool:
        """False bei STO (Sicherheitsschalter) oder Ausfall des EtherCAT – dann endet das Training.
        Andere Störungen meldet drive_fault(); x-ski pausiert und lässt sie quittieren."""
        return self._bus_ok and not any(a in STO_ALARMS for a in self._alarm)

    WATCHDOG_FAULT = -1          # Code für «Regelschleife hat ausgesetzt»

    def drive_fault(self) -> Optional[int]:
        if self._watchdog_tripped:
            return self.WATCHDOG_FAULT
        for a in range(self.axes):
            if self._status[a] & SW_FAULT:
                return self._alarm[a] if self._alarm[a] is not None else 0
        return None

    def fault_text(self, code: int) -> str:
        if code == self.WATCHDOG_FAULT:
            return f"Watchdog – die Regelschleife hat länger als {self.APP_WATCHDOG_S:.0f} s nicht geantwortet"
        return f"Alarm AL{code:03X} (siehe Handbuch ASDA-B3, Kap. 13)" if code else "Störung des Antriebs"

    def _axis_positions(self) -> List[float]:
        return [self._directions[a] * self._raw_pos[a] * self._count_scale - self._home[a] for a in range(self.axes)]

    def read_position(self) -> Optional[int]:
        """Mittlere Seilposition aller Achsen. Wartet auf den nächsten EtherCAT-Zyklus – das gibt der
        Regelschleife ihren Takt (beim M751 tun das die Modbus-Anfragen)."""
        self._fresh.clear()
        if not self._fresh.wait(0.2) or not self._bus_ok:
            return None
        with self._lock:
            return self.POSITION_BASE + int(round(sum(self._axis_positions()) / self.axes))

    def read_speed(self) -> float:
        return sum(self._rpm) / self.axes

    def read_load(self) -> float:
        """Istdrehmoment in x-ski-Prozent (Summe aller Achsen)."""
        return sum(self._torque_nm) / self._reference_nm * 100.0

    def read_power(self) -> int:
        """Mechanische Leistung aller Achsen [W]; beim Ziehen negativ (wie beim M751)."""
        with self._lock:
            return int(round(sum(t * rpm * 0.104720 for t, rpm in zip(self._torque_nm, self._rpm))))

    def read_motor_overload_pct(self) -> Optional[float]:
        return None                               # noch nicht ausgelesen (Monitorvariable des Antriebs)

    def read_brake_resistor_pct(self) -> Optional[float]:
        return None

    def axis_values(self) -> List[dict]:
        """Werte pro Achse (für Anzeige/Seitenvergleich und die spätere Regelung pro Arm)."""
        with self._lock:
            pos = self._axis_positions()
            return [{"position": pos[a], "rpm": self._rpm[a], "torque_nm": self._torque_nm[a],
                     "statusword": self._status[a], "alarm": self._alarm[a]} for a in range(self.axes)]

    def wait_for_moved_axis(self, min_revs: float = 1.0, timeout_s: float = 60.0) -> Optional[int]:
        """Wartet, bis ein Seil von Hand herausgezogen wird (Endstufe aus), und gibt die Achse zurück (0 = Motor 1),
        die sich um mindestens min_revs Umdrehungen bewegt hat – bei beiden gleichzeitig die mit dem grösseren Weg.
        None nach timeout_s ohne Bewegung."""
        with self._lock:
            start = self._axis_positions()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(0.05)
            with self._lock:
                moved = [abs(p - s0) for p, s0 in zip(self._axis_positions(), start)]
            best = max(range(self.axes), key=lambda a: moved[a])
            if moved[best] >= min_revs * self.COUNTS_PER_REV:
                return best
        return None

    # ---------------------- Abläufe ----------------------
    def wait_until_ready(self):
        print(f"Warte auf Delta-Antrieb ({self.axes} Achse(n), EtherCAT) ...")
        self._start()
        while not self.is_healthy():
            print("Drive nicht bereit", end="\r")
            self.reset()
            time.sleep(0.2)
        print("Drive bereit.")

    def wait_for_sto_off(self):
        if not self.sto_wired:
            print("STO nicht verdrahtet (drive.sto_wired = false) – Schritt übersprungen, 5 s Zeit für das Seil.")
            time.sleep(5)
            return
        print("Warte auf STO-Auslösung ...")
        while self.hardware_enabled():
            time.sleep(0.1)
        print("STO ist aus.")

    def wait_for_sto_on(self):
        if not self.sto_wired:
            return
        print("Warte auf STO-Einschaltung ...")
        while not self.hardware_enabled():
            self.reset()                          # der Antrieb bleibt nach STO in Störung, bis quittiert wird
            time.sleep(0.2)
        print("STO ist eingeschaltet.")

    def calibrate_end_position(self, current_limit, calib_torque_pct, calib_speed):
        """Jede Achse zieht ihr Seil langsam bis zum oberen Anschlag; dort wird ihre Endlage gemerkt."""
        print("Kalibriere Endposition ...")
        time.sleep(1)
        self.set_speed(calib_speed)
        self.set_torque(calib_torque_pct)
        self.set_enabled(True)
        time.sleep(0.5)
        still_since = [None] * self.axes
        deadline = time.monotonic() + self.HOMING_TIMEOUT_S
        try:
            while True:
                now = time.monotonic()
                with self._lock:
                    rpm = list(self._rpm)
                for a in range(self.axes):
                    still_since[a] = (still_since[a] or now) if abs(rpm[a]) < self.STOP_SPEED_RPM else None
                if all(t is not None and now - t >= self.STOP_HOLD_S for t in still_since):
                    break
                if not self.hardware_enabled():
                    raise RuntimeError("Antrieb während der Kalibrierung ausgefallen (STO oder Störung).")
                if now > deadline:
                    raise RuntimeError("Endlage nicht erreicht (Zeit abgelaufen). Wickelt ein Motor das Seil ab statt auf, "
                                       "in den Einstellungen seine Drehrichtung umkehren.")
                time.sleep(0.01)
            with self._lock:
                self._home = [self._directions[a] * self._raw_pos[a] * self._count_scale for a in range(self.axes)]
        finally:
            self.set_enabled(False)
            self.set_torque(0)
        print("Kalibrierung abgeschlossen.")

    def shutdown(self):
        """Antrieb in sicheren Zustand bringen: Drehmoment 0, Endstufe aus, EtherCAT schliessen."""
        self._want_enabled = False
        self._torque_pct = 0.0
        self._watchdog_enabled = False
        if self._thread is None:
            return
        time.sleep(10 * self.cycle_s)             # ein paar Zyklen, damit «Endstufe aus» ankommt
        self._running = False
        self._thread.join(timeout=1.0)
        self._thread = None
        try:
            self._bus.close()
        except Exception as e:
            print(f"❌ Abschalten: EtherCAT schliessen fehlgeschlagen: {e}")
