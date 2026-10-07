# Utils/traccar_eelink.py – virtuelle Position per Eelink-Protokoll an einen Traccar-Server senden
#
# Format gemäss Traccar EelinkProtocolDecoder (TCP):
#   Rahmen     0x67 0x67 | Typ (1) | Länge (2, = Index + Nutzlast) | Index (2) | Nutzlast
#   Login      Typ 0x01, Nutzlast = IMEI als 8 Byte BCD ("0" + 15 Ziffern)
#   Heartbeat  Typ 0x03, ohne Nutzlast (hält nur die Verbindung offen)
#   Standort   Typ 0x12 (MSG_NORMAL): Zeit (u32, Unix s) | Flags (u8, Bit 0 = GPS) |
#              Breite, Länge (i32, Grad × 1 800 000) | Höhe (i16, m) | Tempo (u16, km/h) |
#              Kurs (u16, Grad) | Satelliten (u8) | Status (u16, Bit 0 gültig, Bit 10 GPS)
# Der Server bestätigt Login und Heartbeat mit einem eigenen Rahmen; diese Antworten werden gelesen
# und verworfen.

import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional

HEADER = b"\x67\x67"
MSG_LOGIN = 0x01
MSG_HEARTBEAT = 0x03
MSG_NORMAL = 0x12
COORD_SCALE = 1800000.0
STATUS_VALID = 1 << 0
STATUS_GPS = 1 << 10
STATUS_MOTION_INFO = 1 << 3
STATUS_MOTION = 1 << 9


def imei_bcd(imei: str) -> bytes:
    imei = str(imei).strip()
    if len(imei) != 15 or not imei.isdigit():
        raise ValueError("IMEI muss aus genau 15 Ziffern bestehen.")
    return bytes.fromhex("0" + imei)


def build_frame(msg_type: int, index: int, payload: bytes = b"") -> bytes:
    body = struct.pack(">H", index & 0xFFFF) + payload
    return HEADER + struct.pack(">BH", msg_type, len(body)) + body


def login_frame(imei: str, index: int) -> bytes:
    return build_frame(MSG_LOGIN, index, imei_bcd(imei))


def heartbeat_frame(index: int) -> bytes:
    return build_frame(MSG_HEARTBEAT, index)


@dataclass
class TrackerFix:
    timestamp: float
    lat: float
    lon: float
    altitude_m: float
    speed_kmh: float
    course_deg: float


def location_frame(fix: TrackerFix, index: int, satellites: int = 12) -> bytes:
    status = STATUS_VALID | STATUS_GPS | STATUS_MOTION_INFO
    if fix.speed_kmh > 0.5:
        status |= STATUS_MOTION
    payload = struct.pack(
        ">IBiihHHBH",
        int(fix.timestamp),
        0x01,  # Flags: nur GPS-Block
        int(round(fix.lat * COORD_SCALE)),
        int(round(fix.lon * COORD_SCALE)),
        max(-32768, min(32767, int(round(fix.altitude_m)))),
        max(0, min(65535, int(round(fix.speed_kmh)))),
        int(round(fix.course_deg)) % 360,
        satellites,
        status,
    )
    return build_frame(MSG_NORMAL, index, payload)


class EelinkTracker:
    """
    Sendet die jeweils neueste Position im Hintergrund. update() speichert nur und kehrt sofort
    zurück – Verbindungsaufbau, Login, Wiederverbindung und Senden laufen im eigenen Thread.
    """

    CONNECT_TIMEOUT_S = 5.0
    RETRY_MAX_S = 60.0

    def __init__(self, host: str, port: int, imei: str, interval_s: float = 5.0, heartbeat_s: float = 60.0):
        imei_bcd(imei)  # früh prüfen
        self.host = host
        self.port = int(port)
        self.imei = imei
        self.interval_s = max(1.0, float(interval_s))
        self.heartbeat_s = max(10.0, float(heartbeat_s))

        self._lock = threading.Lock()
        self._fix: Optional[TrackerFix] = None
        self._fix_sent = True
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._index = 0
        self.sent_count = 0
        self.connected = False
        self.last_error = ""
        self._thread = threading.Thread(target=self._run, name="traccar-eelink", daemon=True)
        self._thread.start()

    def update(self, fix: TrackerFix):
        with self._lock:
            self._fix = fix
            self._fix_sent = False

    def close(self):
        self._stop.set()
        self._disconnect()

    # ---------------------- Hintergrund ----------------------
    def _next_index(self) -> int:
        self._index = (self._index + 1) & 0xFFFF
        return self._index

    def _connect(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.CONNECT_TIMEOUT_S)
        sock.settimeout(self.CONNECT_TIMEOUT_S)
        sock.sendall(login_frame(self.imei, self._next_index()))
        self._read_responses(sock, wait_s=self.CONNECT_TIMEOUT_S, expect=True)
        self._sock = sock
        self.connected = True
        self.last_error = ""
        print(f"📡 Traccar verbunden ({self.host}:{self.port}, IMEI {self.imei})")

    def _disconnect(self):
        sock, self._sock = self._sock, None
        self.connected = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @staticmethod
    def _read_responses(sock: socket.socket, wait_s: float = 0.0, expect: bool = False):
        """Antworten des Servers lesen und verwerfen. Mit expect=True muss eine Antwort kommen."""
        sock.settimeout(wait_s if wait_s > 0 else 0.0)
        try:
            data = sock.recv(4096)
            if not data:
                raise ConnectionError("Server hat die Verbindung geschlossen")
            if expect and not data.startswith(HEADER):
                raise ConnectionError("Unerwartete Antwort auf den Login")
        except (BlockingIOError, socket.timeout):
            if expect:
                raise ConnectionError("Keine Antwort auf den Login")
        finally:
            sock.settimeout(EelinkTracker.CONNECT_TIMEOUT_S)

    def _run(self):
        retry_s = 2.0
        last_sent = 0.0
        last_heartbeat = time.monotonic()
        while not self._stop.is_set():
            if self._sock is None:
                try:
                    self._connect()
                    retry_s = 2.0
                    last_heartbeat = time.monotonic()
                except Exception as e:
                    self._disconnect()
                    if str(e) != self.last_error:
                        print(f"⚠️ Traccar nicht erreichbar ({self.host}:{self.port}): {e}")
                    self.last_error = str(e)
                    self._stop.wait(retry_s)
                    retry_s = min(retry_s * 2, self.RETRY_MAX_S)
                    continue

            now = time.monotonic()
            try:
                with self._lock:
                    fix = None if self._fix_sent else self._fix
                if fix is not None and now - last_sent >= self.interval_s:
                    self._sock.sendall(location_frame(fix, self._next_index()))
                    with self._lock:
                        if self._fix is fix:
                            self._fix_sent = True
                    last_sent = now
                    self.sent_count += 1
                elif now - last_heartbeat >= self.heartbeat_s:
                    self._sock.sendall(heartbeat_frame(self._next_index()))
                    last_heartbeat = now
                self._read_responses(self._sock)
            except Exception as e:
                print(f"⚠️ Traccar-Verbindung unterbrochen: {e}")
                self.last_error = str(e)
                self._disconnect()
                continue

            self._stop.wait(0.2)
