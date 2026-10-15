import json
import struct
import time

import pytest

from HardwareController import DriveDeltaB3 as D
from HardwareController.factory import create_drive
from Utils.settings import Settings
from Utils.config_manager import DEFAULT_CONFIG


class FakeBus:
    """Zwei (oder ein) simulierte Antriebe mit CiA-402-Zustandsautomat; die Motoren folgen dem Drehmoment."""

    def __init__(self, axes, directions=(1, -1), counts_per_rev=16777216):
        self.axes, self.dirs, self.cpr = axes, directions, counts_per_rev
        self.status = [0x0250] * axes            # Switch on disabled
        self.pos = [5_000_000 * (a + 1) for a in range(axes)]
        self.rpm = [0.0] * axes                  # Rückzug positiv (in Motorrichtung × dir)
        self.torque = [0] * axes
        self.hand_rpm = [None] * axes            # None = Seil frei, sonst von der Hand vorgegeben
        self.stop_at = [None] * axes             # oberer Anschlag (Rohposition × dir)
        self.alarm = [0] * axes
        self.opened = self.closed = False
        self.silent = False
        self.outputs = []

    def open(self): self.opened = True
    def close(self): self.closed = True
    def read_alarm(self, axis): return self.alarm[axis]

    def trip(self, axis, alarm):
        self.alarm[axis], self.status[axis] = alarm, 0x0218

    def exchange(self, outputs):
        if self.silent:
            return None
        self.outputs = [struct.unpack(D.RX_FORMAT, o) for o in outputs]
        inputs = []
        for a, (cw, torque, mode) in enumerate(self.outputs):
            assert mode == D.MODE_CST
            st = self.status[a]
            if st & 0x08:
                if cw & 0x80 and self.alarm[a] == 0:
                    st = 0x0250
            elif cw & 0x0F == 0x06:
                st = 0x0231
            elif cw & 0x0F == 0x07 and st & 0x6F in (0x21, 0x23, 0x27):
                st = 0x0233
            elif cw & 0x0F == 0x0F and st & 0x6F in (0x23, 0x27):
                st = 0x0237
            self.status[a] = st
            self.torque[a] = torque if st & 0x6F == 0x27 else 0
            pull_in = self.dirs[a] * self.torque[a]          # > 0: Motor zieht das Seil ein
            if self.hand_rpm[a] is not None:
                self.rpm[a] = self.hand_rpm[a]
            else:
                self.rpm[a] = 60.0 if pull_in > 0 else -60.0 if pull_in < 0 else 0.0
            new = self.dirs[a] * self.pos[a] + self.rpm[a] / 60 * 0.01 * self.cpr
            if self.stop_at[a] is not None and new >= self.stop_at[a]:
                new, self.rpm[a] = self.stop_at[a], 0.0
            self.pos[a] = int(self.dirs[a] * new)
            inputs.append(struct.pack(D.TX_FORMAT, st, self.pos[a], int(self.dirs[a] * self.rpm[a] * 10),
                                      self.torque[a], 0, D.MODE_CST))
        return inputs


def make(axes=2, bus=None, **kw):
    bus = bus or FakeBus(axes)
    args = dict(axes=axes, interface="eth0", max_torque_pct=250, reference_torque_nm=2.88,
                motor_rated_torque_nm=1.27, motor_max_torque_pct=300, counts_per_rev=16777216,
                directions=(1, -1), sto_wired=True, cycle_ms=2, bus=bus)
    args.update(kw)
    return D.DriveDeltaB3(**args), bus


def settle(drv, cycles=8):
    time.sleep(cycles * drv.cycle_s)


@pytest.fixture
def drive():
    made = []

    def factory(**kw):
        drv, bus = make(**kw)
        made.append(drv)
        drv.wait_until_ready()
        return drv, bus
    yield factory
    for drv in made:
        drv.shutdown()


def test_controlword_sequence():
    assert D.controlword_for(0x0250, True, False) == D.CW_SHUTDOWN
    assert D.controlword_for(0x0231, True, False) == D.CW_SWITCH_ON
    assert D.controlword_for(0x0233, True, False) == D.CW_ENABLE
    assert D.controlword_for(0x0237, True, False) == D.CW_ENABLE
    assert D.controlword_for(0x0237, False, False) == D.CW_SHUTDOWN       # Endstufe aus
    assert D.controlword_for(0x0218, True, False) == 0                    # Störung: nichts ohne Quittierung
    assert D.controlword_for(0x0218, True, True) == D.CW_FAULT_RESET


def test_torque_is_split_and_scaled_per_motor(drive):
    drv, bus = drive()
    drv.set_speed(3000)
    drv.set_enabled(True)
    drv.set_torque(100)                  # 100 % = 2.88 Nm für beide Seile -> 1.44 Nm pro Motor = 113.4 % von 1.27 Nm
    settle(drv)
    assert [o[1] for o in bus.outputs] == [1134, -1134]                   # Motor 2 dreht gespiegelt
    drv.set_torque(999)                  # begrenzt auf max_torque_pct 250 -> 283.5 % pro Motor
    settle(drv)
    assert bus.outputs[0][1] == 2835
    drv.max_torque_pct = 400
    drv.set_torque(400)                  # 453 % wären mehr als der Motor darf -> 300 %
    settle(drv)
    assert [o[1] for o in bus.outputs] == [3000, -3000]


def test_single_axis_gets_full_torque(drive):
    drv, bus = drive(axes=1)
    drv.set_speed(3000)
    drv.set_enabled(True)
    drv.set_torque(50)
    settle(drv)
    assert bus.outputs[0][1] == 1134


def test_no_torque_unless_enabled_and_speed_limit_set(drive):
    drv, bus = drive()
    drv.set_torque(50)
    drv.set_speed(3000)
    settle(drv)
    assert [o[1] for o in bus.outputs] == [0, 0]          # nicht freigegeben
    drv.set_enabled(True)
    drv.set_speed(0)
    settle(drv)
    assert [o[1] for o in bus.outputs] == [0, 0]          # Drehzahlgrenze 0


def test_speed_limit_tapers_torque_on_retraction(drive):
    drv, bus = drive()
    drv.set_speed(1000)
    drv.set_enabled(True)
    drv.set_torque(100)
    bus.hand_rpm = [1050.0, -2000.0]     # Achse 1 läuft 5 % zu schnell ein, Achse 2 wird gezogen
    settle(drv)
    assert bus.outputs[0][1] == pytest.approx(567, abs=2)                 # halbe Kraft
    assert bus.outputs[1][1] == -1134                                     # beim Ziehen keine Begrenzung
    bus.hand_rpm = [1200.0, -2000.0]
    settle(drv)
    assert bus.outputs[0][1] == 0


def test_position_speed_and_power_follow_m751_convention(drive):
    drv, bus = drive()
    p0 = drv.read_position()
    drv.set_speed(3000)
    drv.set_enabled(True)
    drv.set_torque(100)
    bus.hand_rpm = [-600.0, -600.0]      # beide Seile werden gezogen (10 Umdrehungen pro Sekunde)
    settle(drv, 20)
    p1 = drv.read_position()
    assert p1 < p0                                                        # Ziehen zählt abwärts
    assert drv.read_speed() == pytest.approx(-600)
    assert drv.read_load() == pytest.approx(100, abs=0.2)
    assert drv.read_power() == pytest.approx(-2.88 * 600 * 0.10472, abs=2)   # ≈ −181 W
    assert all(v["rpm"] == pytest.approx(-600) for v in drv.axis_values())


def test_homing_per_axis_and_mean_position(drive):
    drv, bus = drive()
    bus.stop_at = [bus.pos[0] + 2 * bus.cpr, -bus.pos[1] + 5 * bus.cpr]   # Anschläge verschieden weit weg
    drv.calibrate_end_position(100, 15, 100)
    assert drv.read_position() == drv.POSITION_BASE                       # beide Achsen an ihrer Endlage
    assert bus.outputs[0][0] == D.CW_SHUTDOWN                             # danach Endstufe aus
    bus.pos[0] -= bus.cpr                                                 # Seil 1 eine Umdrehung herausgezogen
    assert drv.read_position() == drv.POSITION_BASE - 32768               # Mittelwert: halbe Umdrehung


def test_homing_times_out_when_a_motor_unwinds(drive):
    drv, bus = drive(directions=(1, 1))          # Motor 2 ist gespiegelt eingebaut, aber nicht so eingestellt
    drv.HOMING_TIMEOUT_S = 0.3
    bus.stop_at = [bus.pos[0] + bus.cpr, None]   # Motor 2 wickelt ab und findet keinen Anschlag
    with pytest.raises(RuntimeError, match="Drehrichtung"):
        drv.calibrate_end_position(100, 15, 100)
    settle(drv)
    assert [o[1] for o in bus.outputs] == [0, 0]


def test_sto_and_fault_end_the_loop_and_reset_recovers(drive):
    drv, bus = drive()
    assert drv.hardware_enabled()
    bus.trip(1, 0x3E1)                           # andere Störung: Training läuft weiter (Pause + Quittieren)
    settle(drv)
    assert drv.hardware_enabled() and drv.drive_fault() == 0x3E1 and "AL3E1" in drv.fault_text(0x3E1)
    bus.alarm[1] = 0
    drv.reset()
    assert drv.drive_fault() is None
    bus.trip(0, 0x500)                           # Sicherheitsschalter ausgelöst
    settle(drv)
    assert not drv.hardware_enabled()
    assert drv.axis_values()[0]["alarm"] == 0x500
    bus.alarm[0] = 0                             # Schalter wieder zu -> quittieren
    drv.wait_for_sto_on()
    assert drv.hardware_enabled()


def test_watchdog_stops_torque_when_loop_hangs(drive):
    drv, bus = drive()
    drv.APP_WATCHDOG_S = 0.05
    drv.set_speed(3000)
    drv.set_enabled(True)
    drv.set_torque(50)
    drv.set_watchdog_enabled(True)
    for _ in range(10):
        drv.service_watchdog()
        time.sleep(0.01)
    assert bus.outputs[0][1] > 0 and drv.hardware_enabled()
    time.sleep(0.12)                             # Regelschleife hängt
    assert bus.outputs[0][1] == 0 and bus.outputs[0][0] == D.CW_SHUTDOWN
    assert drv.drive_fault() == drv.WATCHDOG_FAULT and "Watchdog" in drv.fault_text(drv.drive_fault())
    assert drv.hardware_enabled()                # keine STO: x-ski pausiert und lässt quittieren
    drv.set_enabled(False)
    drv.reset()
    assert drv.drive_fault() is None


def test_bus_loss_is_reported(drive):
    drv, bus = drive()
    bus.silent = True
    time.sleep((drv.BUS_LOST_CYCLES + 10) * drv.cycle_s)
    assert not drv.hardware_enabled()
    assert drv.read_position() is None


def test_shutdown_closes_bus():
    drv, bus = make()
    drv.wait_until_ready()
    drv.set_enabled(True)
    drv.shutdown()
    assert bus.closed and bus.outputs[0][0] == D.CW_SHUTDOWN and bus.outputs[0][1] == 0


def test_factory_selects_drive_from_machine_settings(tmp_path, monkeypatch):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["simulation"]["motor_rated_torque_nm"] = 2.88
    s = Settings.from_config(cfg, {})
    assert s.drive_type == "m751" and s.drive_axes == 1
    assert type(create_drive(s)).__name__ == "DriveM751"

    machine_file = tmp_path / "maschine.json"
    machine_file.write_text('{"drive": {"type": "delta_b3", "axes": 2, "direction_2": 1}}')
    monkeypatch.setenv("X_SKI_MACHINE_FILE", str(machine_file))
    s = Settings.from_config(cfg, {})
    assert (s.drive_type, s.drive_axes, s.drive_directions) == ("delta_b3", 2, (1, 1))
    drv = create_drive(s)
    assert type(drv).__name__ == "DriveDeltaB3" and drv.axes == 2


def test_wait_for_moved_axis_finds_the_pulled_rope(drive):
    drv, bus = drive()
    assert drv.wait_for_moved_axis(min_revs=1.0, timeout_s=0.2) is None      # niemand zieht
    import threading as th
    def pull():                                  # Motor 2 (gespiegelt) wird 2 Umdrehungen herausgezogen
        time.sleep(0.05)
        bus.pos[1] += 2 * bus.cpr
    th.Thread(target=pull).start()
    assert drv.wait_for_moved_axis(min_revs=1.0, timeout_s=2.0) == 1
