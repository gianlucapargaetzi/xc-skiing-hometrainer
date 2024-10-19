import asyncio
from bleak import BleakClient, BleakScanner

# UUIDs for Heart Rate Service and Measurement Characteristic
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"



from threading import Thread
from time import sleep

async def is_heart_rate_sensor(device):
    """Check if a BLE device has the Heart Rate Measurement service."""
    try:
        async with BleakClient(device) as client:
            # Get the list of services
            services = await client.services

            # Check for the Heart Rate Service UUID
            for service in services:
                if HEART_RATE_SERVICE_UUID in str(service.uuid):
                    print(f"Device {device.name} ({device.address}) is a Heart Rate Sensor!")
                    return True
            return False
    except Exception as e:
        print(f"Failed to connect to {device.name}: {e}")
        return False

def discovery_thread():
    async def find_heart_rate_sensors():
        """Discover and list all BLE devices that are heart rate sensors."""
        print("Discovering Bluetooth Devices...")
        devices = await BleakScanner.discover()

        heart_rate_sensors = []

        for device in devices:
            print(device.details['props']['Alias'], device.details['props']['UUIDs'])
            if HEART_RATE_SERVICE_UUID in device.details['props']['UUIDs']:
                heart_rate_sensors.append(device)

        if not heart_rate_sensors:
            print("No Heart Rate Sensors found.")
        else:
            print("\nDiscovered Heart Rate Sensors:")
            for sensor in heart_rate_sensors:
                print(f" - {sensor.name} ({sensor.address})")

        return heart_rate_sensors

    while True:
        sensors = asyncio.run(find_heart_rate_sensors())
        sleep(20)

if __name__ == "__main__":
    t = Thread(target=discovery_thread)
    t.start()