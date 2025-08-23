# Utils/ble_manager.py

import asyncio
from threading import Lock, Thread
from bleak import BleakClient
from Utils.ble_power_meter_module import BLEPowerServer

HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_MEASUREMENT_CHAR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"


class BLEManager:
    def __init__(self, hr_sensor_address: str):
        self.hr_sensor_address = hr_sensor_address
        self.heart_rate = 0
        self.hr_lock = Lock()
        self.page_loaded = False
        self.page_lock = Lock()

        # Power-Meter-Server starten
        self.ble_server = BLEPowerServer()
        self.t_ble = Thread(target=self.ble_server.start, daemon=True)
        self.t_ble.start()

        # Herzfrequenz-Thread starten
        self.t_hr = Thread(target=self._start_hr_ble, daemon=True)
        self.t_hr.start()

    def hr_measurement_handler(self, sender, data: bytearray):
        if not data:
            return
        flags = data[0]
        hr_16bit = flags & 0x01
        if hr_16bit and len(data) >= 3:
            value = int.from_bytes(data[1:3], byteorder="little")
        elif len(data) >= 2:
            value = data[1]
        else:
            return
        with self.hr_lock:
            self.heart_rate = int(value)

    async def _connect_heart_rate_sensor(self):
        KNOWN_MODELS = {"INW4J": "Polar Verity Sense", "H10": "Polar H10"}
        address = self.hr_sensor_address
        print(f"🔗 Versuche Verbindung mit Herzsensor unter {address}...")
        try:
            client = BleakClient(address)
            await client.connect()
            try:
                model_number = await client.read_gatt_char(MODEL_NUMBER_UUID)
                model_code = model_number.decode("utf-8", errors="ignore").strip()
                friendly_name = KNOWN_MODELS.get(model_code, f"Unbekanntes Modell ({model_code})")
                print(f"📦 Modell erkannt: {friendly_name}")
            except Exception as e:
                print(f"ℹ️ Modellnummer konnte nicht gelesen werden: {e}")
            await client.start_notify(HR_MEASUREMENT_CHAR_UUID, self.hr_measurement_handler)
            print("📡 Herzfrequenzübertragung aktiv")
            while True:
                await asyncio.sleep(1)
        except Exception as e:
            print(f"❌ Verbindung fehlgeschlagen: {e}")

    def _start_hr_ble(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._connect_heart_rate_sensor())

    def get_heart_rate(self) -> int:
        with self.hr_lock:
            return self.heart_rate
