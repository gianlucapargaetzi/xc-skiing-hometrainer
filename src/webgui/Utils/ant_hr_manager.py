# Utils/ant_hr_manager.py

import time
from threading import Lock, Thread

from openant.easy.node import Node
from openant.devices import ANTPLUS_NETWORK_KEY
from openant.devices.heart_rate import HeartRate, HeartRateData


class ANTHRManager:
    """
    Liest einen ANT+ Herzfrequenzsensor über einen ANT USB Stick ein.

    device_id = 0:
        Wildcard-Suche, erster passender HR-Sensor.
    device_id > 0:
        Auf genau diesen ANT+ Sensor pinnen.

    Kommt RESEARCH_AFTER_S lang kein Puls (Gurt beim Start noch aus, abgelegt, Funkloch), wird die Suche neu
    gestartet – der Gurt darf sich also jederzeit verbinden. Früher blieb eine Suche ohne Fund für die ganze
    Session erfolglos (12. und 14.10.2026: Gurt erst nach dem Start eingeschaltet, kein Puls im Training).
    """

    RESEARCH_AFTER_S = 30.0      # ohne Puls so lange -> neue Suche
    STALE_AFTER_S = 5.0          # ohne Puls so lange -> Anzeige 0 (statt eines alten Werts)

    def __init__(
        self,
        device_id: int = 0,
        enabled: bool = True,
        reconnect_delay_s: float = 2.0,
    ):
        self.device_id = int(device_id or 0)
        self.enabled = bool(enabled)
        self.reconnect_delay_s = float(reconnect_delay_s)

        self.heart_rate = 0
        self.hr_lock = Lock()

        self._node = None
        self._device = None
        self._thread = None
        self._stop_requested = False
        self._connected = False
        self._last_seen_monotonic = 0.0
        self._search_started = 0.0
        self._research_requested = False

        if self.enabled:
            self._start_thread()

    def _start_thread(self):
        self._thread = Thread(
            target=self._run,
            daemon=True,
            name="ant-hr-thread",
        )
        self._thread.start()

    def _run(self):
        while not self._stop_requested:
            try:
                self._connected = False
                self._research_requested = False
                self._node = Node()
                self._node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)

                self._device = HeartRate(self._node, device_id=self.device_id)
                self._device.on_found = self._on_found
                self._device.on_device_data = self._on_device_data

                if self.device_id == 0:
                    print("🔎 ANT+ HR: Wildcard-Suche nach Herzfrequenzsensor läuft ...")
                else:
                    print(f"🔎 ANT+ HR: Suche nach Sensor mit device_id={self.device_id} ...")

                self._search_started = time.monotonic()
                worker = Thread(target=self._node.start, daemon=True, name="ant-hr-node")
                worker.start()
                self._supervise(worker)

            except Exception as e:
                if not self._stop_requested:
                    print(f"❌ ANT+ HR-Verbindung fehlgeschlagen: {e}")

            finally:
                self._safe_stop_node()

                if not self._stop_requested:
                    time.sleep(self.reconnect_delay_s)

    def _supervise(self, worker: Thread):
        """Läuft, solange die Suche bzw. Verbindung lebt; beendet sie, wenn zu lange kein Puls kommt
        oder research() aufgerufen wurde (die Schleife in _run sucht dann neu)."""
        while worker.is_alive() and not self._stop_requested:
            time.sleep(0.5)
            if self._research_requested:
                print("🔎 ANT+ HR: neue Suche angefordert")
                return
            since = max(self._last_seen_monotonic, self._search_started)
            if time.monotonic() - since > self.RESEARCH_AFTER_S:
                if self._last_seen_monotonic > self._search_started:
                    print(f"⚠️ ANT+ HR: seit {self.RESEARCH_AFTER_S:.0f} s kein Puls – Suche neu")
                return

    def research(self):
        """Suche sofort neu starten (Knopf «Pulsgurt suchen»)."""
        if not self.enabled:
            return
        self._research_requested = True

    def _on_found(self):
        self._connected = True

        found_id = getattr(self._device, "device_id", self.device_id)
        if found_id:
            print(f"✅ ANT+ HR gefunden (device_id={found_id})")
        else:
            print("✅ ANT+ HR gefunden")

    def _on_device_data(self, page: int, page_name: str, data):
        if isinstance(data, HeartRateData):
            with self.hr_lock:
                self.heart_rate = int(data.heart_rate)

            self._last_seen_monotonic = time.monotonic()

    def _safe_stop_node(self):
        node = self._node
        self._node = None
        self._device = None
        self._connected = False

        if node is None:
            return

        try:
            if hasattr(node, "stop"):
                node.stop()
        except Exception:
            pass

    def close(self):
        self._stop_requested = True
        self._safe_stop_node()

    def get_heart_rate(self) -> int:
        """Aktueller Puls; 0, wenn seit STALE_AFTER_S keiner mehr kam (kein eingefrorener alter Wert)."""
        if self.get_last_seen_age_s() > self.STALE_AFTER_S:
            return 0
        with self.hr_lock:
            return int(self.heart_rate)

    def is_connected(self) -> bool:
        return bool(self._connected) and self.get_last_seen_age_s() <= self.STALE_AFTER_S

    def status(self) -> dict:
        """Für die Anzeige: verbunden (Puls kommt), Puls, sucht gerade."""
        connected = self.is_connected()
        return {"enabled": self.enabled, "device_id": self.device_id, "connected": connected,
                "heart_rate": self.get_heart_rate() if connected else 0,
                "searching": self.enabled and not connected}

    def get_last_seen_age_s(self) -> float:
        if self._last_seen_monotonic <= 0:
            return float("inf")
        return max(0.0, time.monotonic() - self._last_seen_monotonic)