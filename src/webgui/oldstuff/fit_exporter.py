
from fitencode import FitEncoderMinimal
from datetime import datetime

class FitExporter:
    def __init__(self, filename_prefix="x-ski"):
        current_time = datetime.now()
        self.formatted_time = current_time.strftime("%Y-%m-%d_%H-%M-%S")
        self.filename = f"{filename_prefix}_{self.formatted_time}.fit"
        self.encoder = FitEncoderMinimal()

    def add(self, timestamp_str, cadence, power, heart_rate, torque):
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d_%H:%M:%S.%f")
            self.encoder.add_record(timestamp, cadence, power, heart_rate, torque)
        except ValueError as e:
            print(f"⚠️ Zeitformat-Fehler: {e} bei '{timestamp_str}'")

    def save(self):
        self.encoder.write(self.filename)
        print(f"✅ FIT-Datei gespeichert: {self.filename}")
