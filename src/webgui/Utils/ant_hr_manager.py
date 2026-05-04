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
    """

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
                self._node = Node()
                self._node.set_network_key(0x00, ANTPLUS_NETWORK_KEY)

                self._device = HeartRate(self._node, device_id=self.device_id)
                self._device.on_found = self._on_found
                self._device.on_device_data = self._on_device_data

                if self.device_id == 0:
                    print("🔎 ANT+ HR: Wildcard-Suche nach Herzfrequenzsensor läuft ...")
                else:
                    print(f"🔎 ANT+ HR: Suche nach Sensor mit device_id={self.device_id} ...")

                self._node.start()

            except Exception as e:
                if not self._stop_requested:
                    print(f"❌ ANT+ HR-Verbindung fehlgeschlagen: {e}")

            finally:
                self._safe_stop_node()

                if not self._stop_requested:
                    time.sleep(self.reconnect_delay_s)

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
        with self.hr_lock:
            return int(self.heart_rate)

    def is_connected(self) -> bool:
        return bool(self._connected)

    def get_last_seen_age_s(self) -> float:
        if self._last_seen_monotonic <= 0:
            return float("inf")
        return max(0.0, time.monotonic() - self._last_seen_monotonic)