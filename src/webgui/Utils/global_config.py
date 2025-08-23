import json

class GlobalConfig:
    def __init__(self):
        self.reset()

    def reset(self):
        self.pulli_diameter = 100
        self.rope_diameter = 2
        self.top_position = 2000
        self.pole_length = 1500
        self.swing_length = 1200

        self.swing_start_max_torque_pml = 300
        self.swing_end_max_torque_pml = 1200

        self.min_torque_calib_pct = 20
        self.min_speed_calib = 5
        self.min_torque_pct = 15
        self.CurrentLimit = 8
        self.pull_speed = 20

        self.weight_kg = 75
        self.mu = 0.02
        self.s_s = 0.5
        self.slope_percent = 0

        self.firstname = ""
        self.lastname = ""
        self.birthdate = ""
        self.email = ""

        self.hr_sensor_address = ""

        self.drive_host = "localhost"
        self.drive_port = 502
        self.drive_unitid = 1

    def load(self, config_data):
        try:
            hw = config_data.get("hardware", {})
            self.pulli_diameter = hw.get("pulli_diameter", self.pulli_diameter)
            self.rope_diameter = hw.get("rope_diameter", self.rope_diameter)
            self.top_position = hw.get("top_position", self.top_position)
            self.pole_length = hw.get("pole_length", self.pole_length)
            self.swing_length = hw.get("swing_length", self.swing_length)

            swing = config_data.get("swing_torque", {})
            self.swing_start_max_torque_pml = swing.get("swing_start_max_torque_pml", self.swing_start_max_torque_pml)
            self.swing_end_max_torque_pml = swing.get("swing_end_max_torque_pml", self.swing_end_max_torque_pml)

            control = config_data.get("control", {})
            self.min_torque_calib_pct = control.get("min_torque_calib_pct", self.min_torque_calib_pct)
            self.min_speed_calib = control.get("min_speed_calib", self.min_speed_calib)
            self.min_torque_pct = control.get("min_torque_pct", self.min_torque_pct)
            self.CurrentLimit = control.get("CurrentLimit", self.CurrentLimit)
            self.pull_speed = control.get("pull_speed", self.pull_speed)

            user = config_data.get("user", {})
            self.firstname = user.get("firstname", self.firstname)
            self.lastname = user.get("lastname", self.lastname)
            self.birthdate = user.get("birthdate", self.birthdate)
            self.email = user.get("email", self.email)
            self.weight_kg = user.get("weight_kg", self.weight_kg)
            self.mu = user.get("mu", self.mu)
            self.s_s = user.get("s_s", self.s_s)
            self.slope_percent = user.get("slope_percent", self.slope_percent)

            hr = config_data.get("hr_sensor", {})
            self.hr_sensor_address = hr.get("address", self.hr_sensor_address)

            drive = config_data.get("drive", {})
            self.drive_host = drive.get("host", self.drive_host)
            self.drive_port = drive.get("port", self.drive_port)
            self.drive_unitid = drive.get("unit_id", self.drive_unitid)
        except Exception as e:
            print("⚠️ Fehler beim Laden der Konfiguration:", e)

    def to_dict(self):
        return {
            "hardware": {
                "pulli_diameter": self.pulli_diameter,
                "rope_diameter": self.rope_diameter,
                "top_position": self.top_position,
                "pole_length": self.pole_length,
                "swing_length": self.swing_length,
            },
            "swing_torque": {
                "swing_start_max_torque_pml": self.swing_start_max_torque_pml,
                "swing_end_max_torque_pml": self.swing_end_max_torque_pml,
            },
            "control": {
                "min_torque_calib_pct": self.min_torque_calib_pct,
                "min_speed_calib": self.min_speed_calib,
                "min_torque_pct": self.min_torque_pct,
                "CurrentLimit": self.CurrentLimit,
                "pull_speed": self.pull_speed,
            },
            "user": {
                "firstname": self.firstname,
                "lastname": self.lastname,
                "birthdate": self.birthdate,
                "email": self.email,
                "weight_kg": self.weight_kg,
                "mu": self.mu,
                "s_s": self.s_s,
                "slope_percent": self.slope_percent,
            },
            "hr_sensor": {
                "address": self.hr_sensor_address,
            },
            "drive": {
                "host": self.drive_host,
                "port": self.drive_port,
                "unit_id": self.drive_unitid,
            }
        }

# Globale Instanz
global_config = GlobalConfig()
