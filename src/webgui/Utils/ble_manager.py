# Utils/ble_manager.py

from threading import Lock, Thread

from Utils.ble_power_meter_module import BLEPowerServer


class BLEManager:
    """
    Nur noch BLE-Ausgang für MyWhoosh / FTMS.
    Kein eingehender HR-Sensor mehr in dieser Klasse.
    """

    _server_lock = Lock()
    _shared_ble_server = None
    _shared_ble_thread = None

    def __init__(
        self,
        enable_ftms: bool = True,
        ftms_device_name: str = "x-ski FTMS",
        ftms_adapter: str = "hci0",
    ):
        self.enable_ftms = bool(enable_ftms)
        self.ftms_device_name = ftms_device_name
        self.ftms_adapter = ftms_adapter

        if self.enable_ftms:
            self._ensure_power_server(
                local_name=self.ftms_device_name,
                adapter=self.ftms_adapter,
            )

    @classmethod
    def _ensure_power_server(cls, local_name="x-ski FTMS", adapter="hci0"):
        with cls._server_lock:
            if cls._shared_ble_server is not None:
                return

            cls._shared_ble_server = BLEPowerServer(
                adapter=adapter,
                local_name=local_name,
            )
            cls._shared_ble_thread = Thread(
                target=cls._shared_ble_server.start,
                daemon=True,
                name="ble-ftms-server",
            )
            cls._shared_ble_thread.start()
            print(f"✅ BLE FTMS Rower Server gestartet ({local_name} auf {adapter})")

    def close(self):
        # Shared FTMS-Server bleibt absichtlich bestehen.
        pass

    def reset_rower_session(self):
        with self.__class__._server_lock:
            server = self.__class__._shared_ble_server

        if server is not None and hasattr(server, "reset"):
            server.reset()

    def update_rower_metrics(
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
        with self.__class__._server_lock:
            server = self.__class__._shared_ble_server

        if server is None:
            return

        server.update_rower_metrics(
            stroke_rate_spm=stroke_rate_spm,
            stroke_count=stroke_count,
            total_distance_m=total_distance_m,
            pace_s_per_500=pace_s_per_500,
            avg_pace_s_per_500=avg_pace_s_per_500,
            power_w=power_w,
            avg_power_w=avg_power_w,
            hr_bpm=hr_bpm,
            elapsed_s=elapsed_s,
            running=running,
        )