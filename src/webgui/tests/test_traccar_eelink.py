import socket
import struct
import threading
import time

import pytest

from Utils.traccar_eelink import (
    EelinkTracker,
    TrackerFix,
    build_frame,
    heartbeat_frame,
    imei_bcd,
    location_frame,
    login_frame,
)

IMEI = "123456789012345"


def decode(frames: bytes):
    """Nachbau von Traccar EelinkProtocolDecoder.decodePackage/decodeNew (nur die genutzten Teile)."""
    out = []
    buf = memoryview(frames)
    while len(buf) >= 7:
        assert bytes(buf[:2]) == b"\x67\x67"
        msg_type = buf[2]
        length = struct.unpack(">H", buf[3:5])[0]
        body = bytes(buf[5:5 + length])
        index = struct.unpack(">H", body[:2])[0]
        payload = body[2:]
        msg = {"type": msg_type, "index": index}
        if msg_type == 0x01:
            msg["imei"] = payload[:8].hex()[1:]
        elif msg_type == 0x12:
            t, flags = struct.unpack(">IB", payload[:5])
            assert flags & 1
            lat, lon, alt, speed, course, sats, status = struct.unpack(">iihHHBH", payload[5:5 + 18])
            msg.update(time=t, lat=lat / 1800000.0, lon=lon / 1800000.0, alt=alt, speed_kmh=speed,
                       course=course, satellites=sats, valid=bool(status & 1))
        out.append(msg)
        buf = buf[5 + length:]
    assert len(buf) == 0
    return out


def test_imei_bcd():
    assert imei_bcd(IMEI).hex() == "0" + IMEI
    for bad in ("12345", "12345678901234a", ""):
        with pytest.raises(ValueError):
            imei_bcd(bad)


def test_frames_roundtrip():
    fix = TrackerFix(timestamp=1_760_000_000, lat=46.79786, lon=9.831803, altitude_m=1539.7,
                     speed_kmh=12.4, course_deg=67.7)
    frames = login_frame(IMEI, 1) + heartbeat_frame(2) + location_frame(fix, 3)
    login, hb, loc = decode(frames)
    assert login == {"type": 1, "index": 1, "imei": IMEI}
    assert hb == {"type": 3, "index": 2}
    assert loc["type"] == 0x12 and loc["index"] == 3
    assert loc["time"] == 1_760_000_000
    assert loc["lat"] == pytest.approx(46.79786, abs=1e-6)
    assert loc["lon"] == pytest.approx(9.831803, abs=1e-6)
    assert loc["alt"] == 1540 and loc["speed_kmh"] == 12 and loc["course"] == 68
    assert loc["valid"]


def test_frame_length_field():
    f = build_frame(0x12, 7, b"\x01\x02\x03")
    assert f[:3] == b"\x67\x67\x12"
    assert struct.unpack(">H", f[3:5])[0] == 2 + 3


class FakeTraccar:
    """TCP-Server, der wie Traccar Login/Heartbeat beantwortet und alles mitschreibt."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.received = b""
        self.connections = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.connections += 1
            conn.settimeout(0.2)
            with conn:
                while True:
                    try:
                        data = conn.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not data:
                        break
                    self.received += data
                    for msg in decode(data):
                        if msg["type"] in (0x01, 0x03):
                            conn.sendall(build_frame(msg["type"], msg["index"], b"\x00" * 7))

    def close(self):
        self.srv.close()


def test_tracker_logs_in_and_sends_latest_position():
    server = FakeTraccar()
    tracker = EelinkTracker("127.0.0.1", server.port, IMEI, interval_s=1.0)
    try:
        for i in range(30):
            tracker.update(TrackerFix(time.time(), 46.7 + i * 1e-4, 9.8, 1500, 10.0, 90.0))
            time.sleep(0.1)
        deadline = time.time() + 5
        while time.time() < deadline and tracker.sent_count < 2:
            time.sleep(0.1)
        msgs = decode(server.received)
        assert msgs[0]["type"] == 0x01 and msgs[0]["imei"] == IMEI
        locations = [m for m in msgs if m["type"] == 0x12]
        assert len(locations) >= 2
        assert len(locations) <= 5  # gedrosselt auf interval_s, nicht jede update()-Meldung
        assert tracker.connected
    finally:
        tracker.close()
        server.close()


def test_tracker_survives_unreachable_server():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tracker = EelinkTracker("127.0.0.1", port, IMEI, interval_s=1.0)
    try:
        t0 = time.perf_counter()
        tracker.update(TrackerFix(time.time(), 46.7, 9.8, 1500, 10.0, 90.0))
        assert time.perf_counter() - t0 < 0.01  # update() blockiert nie
        time.sleep(0.5)
        assert not tracker.connected and tracker.last_error
    finally:
        tracker.close()


# ---------------------- OsmAnd (HTTP) ----------------------
import http.server
import urllib.parse as _up

from Utils.traccar_osmand import OsmAndTracker, osmand_url


def test_osmand_url():
    fix = TrackerFix(1_760_000_000, 46.79786, 9.831803, 1539.7, 18.52, 367.0)
    q = dict(_up.parse_qsl(_up.urlparse(osmand_url("http://traccar:5055/", "xski-1", fix)).query))
    assert q == {"id": "xski-1", "timestamp": "1760000000", "lat": "46.797860", "lon": "9.831803",
                 "altitude": "1539.7", "speed": "10.00", "bearing": "7.0"}


def test_osmand_tracker_sends_and_throttles():
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(dict(_up.parse_qsl(_up.urlparse(self.path).query)))
            self.send_response(200); self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tracker = OsmAndTracker(f"http://127.0.0.1:{srv.server_port}", "xski-1", interval_s=1.0)
    try:
        for i in range(25):
            tracker.update(TrackerFix(time.time(), 46.7 + i * 1e-4, 9.8, 1500, 10.0, 90.0))
            time.sleep(0.1)
        time.sleep(0.3)
        assert 2 <= len(received) <= 4
        assert received[0]["id"] == "xski-1"
        assert tracker.connected
    finally:
        tracker.close()
        srv.shutdown()


def test_osmand_rejects_bad_config():
    with pytest.raises(ValueError):
        OsmAndTracker("traccar:5055", "x")
    with pytest.raises(ValueError):
        OsmAndTracker("http://traccar:5055", "")
