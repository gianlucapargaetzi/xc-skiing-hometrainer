# Utils/traccar_osmand.py – virtuelle Position per OsmAnd-Protokoll (HTTP) an Traccar senden
#
# Format wie der Traccar Client: GET http://<server>:5055/?id=<Geräte-ID>&timestamp=<Unix s>&lat=..&lon=..
#   &altitude=<m>&speed=<Knoten>&bearing=<Grad>  ->  Antwort 200 OK

import threading
import time
import urllib.parse
import urllib.request
from typing import Optional

from Utils.traccar_eelink import TrackerFix

KMH_PER_KNOT = 1.852


def osmand_url(base_url: str, device_id: str, fix: TrackerFix) -> str:
    params = {
        "id": device_id,
        "timestamp": int(fix.timestamp),
        "lat": f"{fix.lat:.6f}",
        "lon": f"{fix.lon:.6f}",
        "altitude": f"{fix.altitude_m:.1f}",
        "speed": f"{max(0.0, fix.speed_kmh) / KMH_PER_KNOT:.2f}",
        "bearing": f"{fix.course_deg % 360:.1f}",
    }
    return base_url.rstrip("/") + "/?" + urllib.parse.urlencode(params)


class OsmAndTracker:
    """
    Sendet die jeweils neueste Position im Hintergrund per HTTP. update() speichert nur und kehrt
    sofort zurück; ein langsamer oder nicht erreichbarer Server blockiert die Regelschleife nie.
    """

    TIMEOUT_S = 5.0
    RETRY_MAX_S = 60.0

    def __init__(self, base_url: str, device_id: str, interval_s: float = 5.0):
        if not device_id:
            raise ValueError("Geräte-ID (wie in Traccar angelegt) fehlt.")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Ungültige Traccar-URL: {base_url}")
        self.base_url = base_url
        self.device_id = device_id
        self.interval_s = max(1.0, float(interval_s))

        self._lock = threading.Lock()
        self._fix: Optional[TrackerFix] = None
        self._fix_sent = True
        self._stop = threading.Event()
        self.sent_count = 0
        self.connected = False
        self.last_error = ""
        self._thread = threading.Thread(target=self._run, name="traccar-osmand", daemon=True)
        self._thread.start()

    def update(self, fix: TrackerFix):
        with self._lock:
            self._fix = fix
            self._fix_sent = False

    def close(self):
        self._stop.set()

    def _send(self, fix: TrackerFix):
        req = urllib.request.Request(osmand_url(self.base_url, self.device_id, fix), method="GET",
                                     headers={"User-Agent": "x-ski"})
        with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
            if resp.status != 200:
                raise ConnectionError(f"HTTP {resp.status}")

    def _run(self):
        retry_s = self.interval_s
        while not self._stop.is_set():
            with self._lock:
                fix = None if self._fix_sent else self._fix
            if fix is None:
                self._stop.wait(0.2)
                continue
            try:
                self._send(fix)
                with self._lock:
                    if self._fix is fix:
                        self._fix_sent = True
                self.sent_count += 1
                if not self.connected:
                    print(f"📡 Traccar (OsmAnd) erreichbar: {self.base_url}, Gerät {self.device_id}")
                self.connected = True
                self.last_error = ""
                retry_s = self.interval_s
                self._stop.wait(self.interval_s)
            except Exception as e:
                if str(e) != self.last_error:
                    print(f"⚠️ Traccar (OsmAnd) nicht erreichbar ({self.base_url}): {e}")
                self.connected = False
                self.last_error = str(e)
                self._stop.wait(retry_s)
                retry_s = min(retry_s * 2, self.RETRY_MAX_S)


def create_tracker(protocol: str, *, url: str, host: str, port: int, device_id: str, interval_s: float):
    protocol = (protocol or "osmand").lower()
    if protocol == "osmand":
        return OsmAndTracker(url, device_id, interval_s)
    if protocol == "eelink":
        from Utils.traccar_eelink import EelinkTracker
        return EelinkTracker(host, port, device_id, interval_s)
    raise ValueError(f"Unbekanntes Traccar-Protokoll '{protocol}' (erlaubt: osmand, eelink).")
