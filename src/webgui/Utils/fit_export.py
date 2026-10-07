# Utils/fit_export.py – Training als FIT-Datei (Garmin Flexible and Interoperable Data Transfer)
#
# Sportart: cross_country_skiing (12). Hinweis: "fitness_equipment / indoor_skiing" (wie Concept2 SkiErg)
# zeigt Strava beim Datei-Upload nur als "Training" an (getestet 07.10.2026). Dateien ohne GPS-Koordinaten
# markiert Strava automatisch als stationär/indoor; in der Streckensimulation wird die virtuelle Position
# mitgeschrieben.
#
# Aufbau: 14-Byte-Kopf, Definitions- und Datennachrichten, CRC-16 am Schluss (FIT-Protokoll 2.0).

import math
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

FIT_EPOCH_OFFSET = 631065600          # 1989-12-31 00:00:00 UTC in Unix-Sekunden
SPORT_FITNESS_EQUIPMENT = 4
SPORT_CROSS_COUNTRY_SKIING = 12
SUB_SPORT_GENERIC = 0
SUB_SPORT_INDOOR_SKIING = 25
DEFAULT_SPORT = SPORT_CROSS_COUNTRY_SKIING
DEFAULT_SUB_SPORT = SUB_SPORT_GENERIC
SEMICIRCLES_PER_DEG = 2 ** 31 / 180.0

# Basistypen: (Kennung, struct-Format, ungültiger Wert)
BASE = {
    "enum": (0x00, "B", 0xFF),
    "uint8": (0x02, "B", 0xFF),
    "sint16": (0x83, "h", 0x7FFF),
    "uint16": (0x84, "H", 0xFFFF),
    "sint32": (0x85, "i", 0x7FFFFFFF),
    "uint32": (0x86, "I", 0xFFFFFFFF),
    "uint32z": (0x8C, "I", 0x00000000),
}

# Nachrichten: globale Nummer und Felder (Feldnummer, Name, Basistyp)
MESSAGES = {
    "file_id": (0, [(0, "type", "enum"), (1, "manufacturer", "uint16"), (2, "product", "uint16"),
                    (3, "serial_number", "uint32z"), (4, "time_created", "uint32")]),
    "event": (21, [(253, "timestamp", "uint32"), (0, "event", "enum"), (1, "event_type", "enum")]),
    "record": (20, [(253, "timestamp", "uint32"), (0, "position_lat", "sint32"), (1, "position_long", "sint32"),
                    (2, "altitude", "uint16"), (3, "heart_rate", "uint8"), (4, "cadence", "uint8"),
                    (5, "distance", "uint32"), (6, "speed", "uint16"), (7, "power", "uint16"), (9, "grade", "sint16")]),
    "lap": (19, [(253, "timestamp", "uint32"), (254, "message_index", "uint16"), (0, "event", "enum"),
                 (1, "event_type", "enum"), (2, "start_time", "uint32"), (7, "total_elapsed_time", "uint32"),
                 (8, "total_timer_time", "uint32"), (9, "total_distance", "uint32"), (13, "avg_speed", "uint16"),
                 (14, "max_speed", "uint16"), (15, "avg_heart_rate", "uint8"), (16, "max_heart_rate", "uint8"),
                 (17, "avg_cadence", "uint8"), (19, "avg_power", "uint16"), (20, "max_power", "uint16"),
                 (21, "total_ascent", "uint16"), (22, "total_descent", "uint16"), (24, "lap_trigger", "enum"),
                 (25, "sport", "enum"), (39, "sub_sport", "enum")]),
    "session": (18, [(253, "timestamp", "uint32"), (254, "message_index", "uint16"), (0, "event", "enum"),
                     (1, "event_type", "enum"), (2, "start_time", "uint32"), (5, "sport", "enum"),
                     (6, "sub_sport", "enum"), (7, "total_elapsed_time", "uint32"), (8, "total_timer_time", "uint32"),
                     (9, "total_distance", "uint32"), (14, "avg_speed", "uint16"), (15, "max_speed", "uint16"),
                     (16, "avg_heart_rate", "uint8"), (17, "max_heart_rate", "uint8"), (18, "avg_cadence", "uint8"),
                     (20, "avg_power", "uint16"), (21, "max_power", "uint16"), (22, "total_ascent", "uint16"),
                     (23, "total_descent", "uint16"), (25, "first_lap_index", "uint16"), (26, "num_laps", "uint16"),
                     (28, "trigger", "enum")]),
    "activity": (34, [(253, "timestamp", "uint32"), (0, "total_timer_time", "uint32"), (1, "num_sessions", "uint16"),
                      (2, "type", "enum"), (3, "event", "enum"), (4, "event_type", "enum"),
                      (5, "local_timestamp", "uint32")]),
}

_CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)


def fit_crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def fit_time(unix_s: float) -> int:
    return int(unix_s) - FIT_EPOCH_OFFSET


class FitWriter:
    def __init__(self):
        self._body = bytearray()
        self._local: Dict[str, int] = {}

    def _define(self, name: str):
        if name in self._local:
            return self._local[name]
        local = len(self._local)
        if local > 15:
            raise ValueError("Zu viele Nachrichtentypen")
        global_num, fields = MESSAGES[name]
        self._body += struct.pack("<BBBHB", 0x40 | local, 0, 0, global_num, len(fields))
        for num, _, base in fields:
            base_id, fmt, _ = BASE[base]
            self._body += struct.pack("<BBB", num, struct.calcsize(fmt), base_id)
        self._local[name] = local
        return local

    def write(self, name: str, **values):
        local = self._define(name)
        _, fields = MESSAGES[name]
        self._body += struct.pack("<B", local)
        for _, fname, base in fields:
            _, fmt, invalid = BASE[base]
            v = values.get(fname)
            if v is None:
                v = invalid
            else:
                v = int(round(v))
                # Werte ausserhalb des Typbereichs als "ungültig" schreiben statt abzustürzen
                lo, hi = {"B": (0, 0xFE), "H": (0, 0xFFFE), "I": (0, 0xFFFFFFFE),
                          "h": (-0x7FFF, 0x7FFE), "i": (-0x7FFFFFFF, 0x7FFFFFFE)}[fmt]
                if not lo <= v <= hi:
                    v = invalid
            self._body += struct.pack("<" + fmt, v)

    def to_bytes(self) -> bytes:
        header = struct.pack("<BBHI4s", 14, 0x20, 2132, len(self._body), b".FIT")
        header += struct.pack("<H", fit_crc(header))
        data = header + bytes(self._body)
        return data + struct.pack("<H", fit_crc(data))


# ---------------------------------------------------------------------------------------------
@dataclass
class FitSample:
    t: float                       # Unix-Zeit [s]
    distance_m: float
    speed_m_s: Optional[float] = None
    heart_rate: Optional[float] = None
    cadence: Optional[float] = None
    power: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    altitude_m: Optional[float] = None
    grade_percent: Optional[float] = None


@dataclass
class FitLap:
    start_t: float
    end_t: float
    trigger: int = 0               # 0 manuell (Intervall/Ende), 2 Distanz (pro km)


class FitRecorder:
    """Sammelt Sekundenwerte und Runden während des Trainings und schreibt am Ende eine FIT-Datei."""

    def __init__(self):
        self.samples: List[FitSample] = []
        self.laps: List[FitLap] = []
        self._lap_start: Optional[float] = None
        self._lap_key = None

    def add(self, sample: FitSample, lap_key=None, lap_trigger: int = 0):
        """Sekundenwert hinzufügen. Wechselt lap_key (z.B. km oder Intervallblock), beginnt eine neue Runde."""
        if self._lap_start is None:
            self._lap_start = sample.t
            self._lap_key = lap_key
        elif lap_key != self._lap_key:
            self.laps.append(FitLap(self._lap_start, sample.t, lap_trigger))
            self._lap_start = sample.t
            self._lap_key = lap_key
        self.samples.append(sample)

    def finish(self, end_t: Optional[float] = None):
        if self._lap_start is not None and self.samples:
            end = end_t if end_t is not None else self.samples[-1].t
            if end > self._lap_start or not self.laps:
                self.laps.append(FitLap(self._lap_start, max(end, self._lap_start), 0))
            self._lap_start = None

    def write(self, path: str, sport: int = DEFAULT_SPORT, sub_sport: int = DEFAULT_SUB_SPORT):
        if not self.samples:
            raise ValueError("Keine Messwerte – keine FIT-Datei.")
        self.finish()
        data = build_fit(self.samples, self.laps, sport, sub_sport)
        with open(path, "wb") as f:
            f.write(data)
        return path


def _stats(samples: List[FitSample]) -> dict:
    def vals(attr):
        return [getattr(s, attr) for s in samples if getattr(s, attr) is not None and getattr(s, attr) > 0]
    hr, pw, cad, sp = vals("heart_rate"), vals("power"), vals("cadence"), vals("speed_m_s")
    ascent = descent = 0.0
    alts = [s.altitude_m for s in samples if s.altitude_m is not None]
    for a, b in zip(alts, alts[1:]):
        if b > a:
            ascent += b - a
        else:
            descent += a - b
    return {
        "avg_heart_rate": sum(hr) / len(hr) if hr else None, "max_heart_rate": max(hr) if hr else None,
        "avg_power": sum(pw) / len(pw) if pw else None, "max_power": max(pw) if pw else None,
        "avg_cadence": sum(cad) / len(cad) if cad else None,
        "max_speed": max(sp) * 1000 if sp else None,
        "total_ascent": ascent if alts else None, "total_descent": descent if alts else None,
    }


def build_fit(samples: List[FitSample], laps: List[FitLap], sport: int = DEFAULT_SPORT,
              sub_sport: int = DEFAULT_SUB_SPORT) -> bytes:
    w = FitWriter()
    t0, t1 = samples[0].t, samples[-1].t
    w.write("file_id", type=4, manufacturer=255, product=1, serial_number=1, time_created=fit_time(t0))
    w.write("event", timestamp=fit_time(t0), event=0, event_type=0)  # Timer start

    for s in samples:
        w.write("record",
                timestamp=fit_time(s.t),
                position_lat=None if s.lat is None else s.lat * SEMICIRCLES_PER_DEG,
                position_long=None if s.lon is None else s.lon * SEMICIRCLES_PER_DEG,
                altitude=None if s.altitude_m is None else (s.altitude_m + 500) * 5,
                heart_rate=s.heart_rate or None, cadence=s.cadence or None,
                distance=s.distance_m * 100, speed=None if s.speed_m_s is None else s.speed_m_s * 1000,
                power=s.power, grade=None if s.grade_percent is None else s.grade_percent * 100)

    for i, lap in enumerate(laps):
        part = [s for s in samples if lap.start_t <= s.t <= lap.end_t] or [samples[-1]]
        dist = part[-1].distance_m - part[0].distance_m
        dur = max(lap.end_t - lap.start_t, 0.0)
        st = _stats(part)
        w.write("lap", timestamp=fit_time(lap.end_t), message_index=i, event=9, event_type=1,
                start_time=fit_time(lap.start_t), total_elapsed_time=dur * 1000, total_timer_time=dur * 1000,
                total_distance=dist * 100, avg_speed=(dist / dur * 1000) if dur > 0 else None,
                lap_trigger=lap.trigger, sport=sport, sub_sport=sub_sport, **st)

    total = t1 - t0
    dist = samples[-1].distance_m - samples[0].distance_m
    st = _stats(samples)
    w.write("event", timestamp=fit_time(t1), event=0, event_type=4)  # Timer stop_all
    w.write("session", timestamp=fit_time(t1), message_index=0, event=8, event_type=1, start_time=fit_time(t0),
            sport=sport, sub_sport=sub_sport,
            total_elapsed_time=total * 1000, total_timer_time=total * 1000, total_distance=dist * 100,
            avg_speed=(dist / total * 1000) if total > 0 else None, first_lap_index=0, num_laps=len(laps),
            trigger=0, **{k: v for k, v in st.items() if k != "avg_cadence"}, avg_cadence=st["avg_cadence"])
    local_offset = datetime.fromtimestamp(t1).astimezone().utcoffset().total_seconds()
    w.write("activity", timestamp=fit_time(t1), total_timer_time=total * 1000, num_sessions=1, type=0,
            event=26, event_type=1, local_timestamp=fit_time(t1 + local_offset))
    return w.to_bytes()
