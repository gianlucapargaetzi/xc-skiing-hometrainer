import pytest
import time

from HardwareController import DriveM751 as D


class RecordingDrive(D.DriveM751):
    def __init__(self):
        super().__init__("127.0.0.1", 1, 1, max_torque_pct=250)
        self.writes = []

    def _write(self, addr, value):
        self.writes.append((time.monotonic(), addr, value))


def test_watchdog_rising_edge_well_within_one_second():
    drv = RecordingDrive()
    end = time.monotonic() + 1.0
    loops = 0
    while time.monotonic() < end:  # Regelschleife mit ~5 ms pro Zyklus
        drv.service_watchdog()
        loops += 1
        time.sleep(0.005)

    wd = [(t, v) for t, a, v in drv.writes if a == D.REG_WATCHDOG_TOGGLE]
    assert wd[0][1] == 0 and wd[1][1] == D.WATCHDOG_BIT        # beginnt mit 0 -> 1
    assert all(a[1] != b[1] for a, b in zip(wd, wd[1:]))        # strikt abwechselnd
    rises = [t for (t0, v0), (t, v) in zip(wd, wd[1:]) if v0 == 0 and v == D.WATCHDOG_BIT]
    gaps = [b - a for a, b in zip(rises, rises[1:])]
    assert max(gaps) < 0.2                                      # Flanke ca. alle 100 ms, Grenze 1 s
    assert len(wd) < loops / 4                                  # deutlich weniger Schreibzugriffe


def test_update_torque_only_writes_on_change():
    drv = RecordingDrive()
    for _ in range(10):
        drv.update_torque(50)
    drv.update_torque(60)
    torque_writes = [v for _, a, v in drv.writes if a == D.REG_TORQUE_REF]
    assert torque_writes == [5000, 6000]


def test_torque_is_clamped():
    drv = RecordingDrive()
    drv.set_torque(999)
    drv.set_torque(-5)
    assert [v for _, a, v in drv.writes if a == D.REG_TORQUE_REF] == [25000, 0]


def test_thermal_registers_are_scaled():
    class ReadDrive(RecordingDrive):
        def _read1(self, addr):
            return {D.REG_MOTOR_OVERLOAD: 9, D.REG_BRAKE_RESISTOR_LOAD: 755}.get(addr)
    drv = ReadDrive()
    assert drv.read_motor_overload_pct() == pytest.approx(0.9)
    assert drv.read_brake_resistor_pct() == pytest.approx(75.5)


def test_simple_controller_max_matches_drive_limit():
    from IntensityController import SimpleIntensityController as S
    assert S.MAX_VALUE == 180


def test_thermal_protection_mode_written_and_read_back():
    class ModeDrive(RecordingDrive):
        def _read1(self, addr):
            return dict((a, v) for _, a, v in self.writes).get(addr)
    drv = ModeDrive()
    assert drv.set_thermal_protection_mode(D.DriveM751.THERMAL_MODE_MOTOR_LIMIT) == 1
    assert (D.REG_THERMAL_PROTECTION_MODE, 1) in [(a, v) for _, a, v in drv.writes]
