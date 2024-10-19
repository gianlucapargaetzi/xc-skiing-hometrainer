from HeartRateManager import BluetoothHeartRateSensor

import logging

from time import sleep

logging.basicConfig(level= logging.INFO)
hrm = BluetoothHeartRateSensor(None)

sensor_info = hrm.available_sensors()
print(sensor_info)

mac_address = None
if len(sensor_info['hr_sensors']) == 0:
    exit(1)

mac_address = sensor_info['hr_sensors'][0]['address']
print(f"My MAC-Adresss: f{mac_address}")

hrm.connect_sensor(mac_address)

print("Sleeping for 15s")
sleep(15)

hrm.disconnect_sensor()