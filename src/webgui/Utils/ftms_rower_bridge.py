# Utils/ftms_rower_server.py

from __future__ import annotations

import struct
import threading
from dataclasses import dataclass

from bluezero import adapter, peripheral


def uuid16(value: int) -> str:
    return f"0000{value:04x}-0000-1000-8000-00805f9b34fb"


FTMS_SERVICE_UUID = uuid16(0x1826)
FITNESS_MACHINE_FEATURE_UUID = uuid16(0x2ACC)
ROWER_DATA_UUID = uuid16(0x2AD1)
FITNESS_MACHINE_CONTROL_POINT_UUID = uuid16(0x2AD9)

DEVICE_INFO_SERVICE_UUID = uuid16(0x180A)
MANUFACTURER_NAME_UUID = uuid16(0x2A29)
MODEL_NUMBER_UUID = uuid16(0x2A24)
FIRMWARE_REVISION_UUID = uuid16(0x2A26)


@dataclass
class FTMSMetrics:
    stroke_rate_spm: float = 0.0
    stroke_count: int = 0
    total_distance_m: float = 0.0
    pace_s_per_500: int = 0
    avg_pace_s_per_500: int = 0
    power_w: int = 0
    avg_power_w: int = 0
    hr_bpm: int = 0
    elapsed_s: int = 0
    running: bool = False


class FTMSRowerServer:
    def __init__(self, adapter_address: str | None = None, device_name: str = "x-ski FTMS"):
        self.adapter_address = adapter_address
        self.device_name = device_name

        self._metrics = FTMSMetrics()
        self._lock = threading.Lock()
        self._ready = threading.Event()

        self._peripheral = None
        self._rower_data_char = None
        self._control_point_char = None

    def start(self):
        adapter_addr = self._resolve_adapter_address()

        p = peripheral.Peripheral(adapter_addr, local_name=self.device_name)

        # FTMS
        p.add_service(srv_id=1, uuid=FTMS_SERVICE_UUID, primary=True)

        p.add_characteristic(
            srv_id=1,
            chr_id=1,
            uuid=FITNESS_MACHINE_FEATURE_UUID,
            value=self._pack_fitness_machine_feature(),
            notifying=False,
            flags=["read"],
            read_callback=self._read_fitness_machine_feature,
        )

        p.add_characteristic(
            srv_id=1,
            chr_id=2,
            uuid=ROWER_DATA_UUID,
            value=self._pack_rower_data(),
            notifying=False,
            flags=["read", "notify"],
            read_callback=self._read_rower_data,
        )

        p.add_characteristic(
            srv_id=1,
            chr_id=3,
            uuid=FITNESS_MACHINE_CONTROL_POINT_UUID,
            value=[0x00],
            notifying=False,
            flags=["write", "indicate"],
            write_callback=self._write_control_point,
        )

        # Device Info
        p.add_service(srv_id=2, uuid=DEVICE_INFO_SERVICE_UUID, primary=False)

        p.add_characteristic(
            srv_id=2,
            chr_id=1,
            uuid=MANUFACTURER_NAME_UUID,
            value=list(b"x-ski.ch"),
            notifying=False,
            flags=["read"],
            read_callback=lambda: list(b"x-ski.ch"),
        )

        p.add_characteristic(
            srv_id=2,
            chr_id=2,
            uuid=MODEL_NUMBER_UUID,
            value=list(b"x-ski-v1"),
            notifying=False,
            flags=["read"],
            read_callback=lambda: list(b"x-ski-v1"),
        )

        p.add_characteristic(
            srv_id=2,
            chr_id=3,
            uuid=FIRMWARE_REVISION_UUID,
            value=list(b"0.1-ftms"),
            notifying=False,
            flags=["read"],
            read_callback=lambda: list(b"0.1-ftms"),
        )

        self._peripheral = p

        # bluezero speichert die Characteristics in einer Liste.
        # In dieser Reihenfolge ist chr_id=2 die Rower-Data-Characteristic,
        # chr_id=3 der Control Point.
        self._rower_data_char = p.characteristics[1]
        self._control_point_char = p.characteristics[2]

        self._ready.set()
        p.publish()

    def wait_ready(self, timeout: float = 8.0) -> bool:
        return self._ready.wait(timeout=timeout)

    def reset(self):
        with self._lock:
            self._metrics = FTMSMetrics()
        self._push_rower_data()

    def update_metrics(
        self,
        *,
        stroke_rate_spm: float,
        stroke_count: int,
        total_distance_m: float,
        pace_s_per_500: int,
        avg_pace_s_per_500: int,
        power_w: int,
        avg_power_w: int,
        hr_bpm: int,
        elapsed_s: int,
        running: bool,
    ):
        with self._lock:
            self._metrics.stroke_rate_spm = max(0.0, float(stroke_rate_spm))
            self._metrics.stroke_count = self._clamp_int(stroke_count, 0, 0xFFFF)
            self._metrics.total_distance_m = max(0.0, float(total_distance_m))
            self._metrics.pace_s_per_500 = self._clamp_int(pace_s_per_500, 0, 0xFFFF)
            self._metrics.avg_pace_s_per_500 = self._clamp_int(avg_pace_s_per_500, 0, 0xFFFF)
            self._metrics.power_w = self._clamp_int(power_w, -32768, 32767)
            self._metrics.avg_power_w = self._clamp_int(avg_power_w, -32768, 32767)
            self._metrics.hr_bpm = self._clamp_int(hr_bpm, 0, 255)
            self._metrics.elapsed_s = self._clamp_int(elapsed_s, 0, 0xFFFF)
            self._metrics.running = bool(running)

        self._push_rower_data()

    def _resolve_adapter_address(self) -> str:
        if self.adapter_address:
            return self.adapter_address

        adapters = list(adapter.Adapter.available())
        if not adapters:
            raise RuntimeError("Kein Bluetooth-Adapter gefunden")

        return adapters[0].address

    def _read_fitness_machine_feature(self):
        return self._pack_fitness_machine_feature()

    def _read_rower_data(self):
        return self._pack_rower_data()

    def _write_control_point(self, value, options):
        if not value:
            return

        opcode = int(value[0])

        # Minimal-ACK: Response Code (0x80), angefragter Opcode, Success (0x01)
        response = [0x80, opcode, 0x01]

        if self._control_point_char is not None:
            self._control_point_char.set_value(response)

    def _pack_fitness_machine_feature(self) -> list[int]:
        # Konservativer Start: keine falschen Features behaupten.
        return list((0).to_bytes(8, byteorder="little", signed=False))

    def _pack_rower_data(self) -> list[int]:
        with self._lock:
            m = FTMSMetrics(**self._metrics.__dict__)

        # Flags:
        # bit 2  Total Distance present
        # bit 3  Instantaneous Pace present
        # bit 4  Average Pace present
        # bit 5  Instantaneous Power present
        # bit 6  Average Power present
        # bit 9  Heart Rate present
        # bit 11 Elapsed Time present
        flags = (
            (1 << 2)
            | (1 << 3)
            | (1 << 4)
            | (1 << 5)
            | (1 << 6)
            | (1 << 9)
            | (1 << 11)
        )

        stroke_rate_half_spm = self._clamp_int(round(m.stroke_rate_spm * 2.0), 0, 255)
        stroke_count = self._clamp_int(m.stroke_count, 0, 0xFFFF)
        total_distance = self._clamp_int(round(m.total_distance_m), 0, 0xFFFFFF)
        inst_pace = self._clamp_int(m.pace_s_per_500, 0, 0xFFFF)
        avg_pace = self._clamp_int(m.avg_pace_s_per_500, 0, 0xFFFF)
        inst_power = self._clamp_int(m.power_w, -32768, 32767)
        avg_power = self._clamp_int(m.avg_power_w, -32768, 32767)
        hr = self._clamp_int(m.hr_bpm, 0, 255)
        elapsed = self._clamp_int(m.elapsed_s, 0, 0xFFFF)

        payload = bytearray()
        payload += struct.pack("<H", flags)
        payload += struct.pack("<B", stroke_rate_half_spm)
        payload += struct.pack("<H", stroke_count)
        payload += bytes((
            total_distance & 0xFF,
            (total_distance >> 8) & 0xFF,
            (total_distance >> 16) & 0xFF,
        ))
        payload += struct.pack("<H", inst_pace)
        payload += struct.pack("<H", avg_pace)
        payload += struct.pack("<h", inst_power)
        payload += struct.pack("<h", avg_power)
        payload += struct.pack("<B", hr)
        payload += struct.pack("<H", elapsed)

        return list(payload)

    def _push_rower_data(self):
        if self._rower_data_char is not None:
            self._rower_data_char.set_value(self._pack_rower_data())

    @staticmethod
    def _clamp_int(value, lo: int, hi: int) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return max(lo, min(value, hi))