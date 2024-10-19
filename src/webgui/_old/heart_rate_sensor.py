# import asyncio
# from bleak import BleakClient, BleakScanner

# # UUIDs
# HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
# HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
# BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
# BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# # Function to process heart rate data
# def process_heart_rate_data(sender: int, data: bytearray):
#     heart_rate = data[1]
#     print(f"Heart Rate: {heart_rate} bpm")

# # Function to read and display battery level
# async def read_battery_level(client):
#     while True:
#         battery_level = await client.read_gatt_char(BATTERY_LEVEL_UUID)
#         print(f"Battery Level: {int(battery_level[0])}%")
#         # Sleep for 60 seconds (or whatever interval you prefer)
#         await asyncio.sleep(10)

# async def main():
#     # Scan for BLE devices and find the Polar H10
#     devices = await BleakScanner.discover()
#     polar_device = None
#     for device in devices:
#         if "Polar" in device.name:
#             polar_device = device
#             break

#     if polar_device is None:
#         print("Polar H10 not found")
#         return

#     # Connect to the Polar H10 device
#     async with BleakClient(polar_device) as client:
#         print(f"Connected to {polar_device.name}")

#         # Start heart rate notifications
#         await client.start_notify(HEART_RATE_MEASUREMENT_UUID, process_heart_rate_data)

#         # # Start reading battery level every 60 seconds
#         await read_battery_level(client)

#         # Keep the connection open and listening for heart rate notifications indefinitely
#         # To stop after a certain time, you could adjust this loop or add more conditions
#         await asyncio.sleep(120)  # Adjust the time as needed

#         # Stop notifications and disconnect
#         await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)

# # Run the BLE connection loop

# async def discover():
#     print("Discover")
#     devices = await BleakScanner.discover()
#     print("Finished discover")
#     for d in devices:
#         print(d)

# asyncio.run(main())

import asyncio
from bleak import BleakClient, BleakScanner

from HeartRateMonitor import HeartRateMonitor

from multiprocessing import Queue
import time

# UUIDs
HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

import subprocess

import subprocess
import time

hrm: HeartRateMonitor = None


# Function to process heart rate data
def process_heart_rate_data(sender: int, data: bytearray):
    # Byte 0: Flags
    flags = data[0]
    # Byte 1 or 2: Heart rate value (8-bit or 16-bit depending on flags)
    heart_rate = data[1] if flags & 0b00000001 == 0 else (data[1] + (data[2] << 8))
    hrm.set_value(heart_rate=heart_rate)
    print(f"Heart Rate: {heart_rate} bpm")

# Function to read and display battery level
async def read_battery_level(client):
    try:
        while True:
            battery_level = await client.read_gatt_char(BATTERY_LEVEL_UUID)
            print(f"Battery Level: {int(battery_level[0])}%")
            await asyncio.sleep(20)  # Sleep for 1 minute
    except asyncio.CancelledError:
        print("Battery level reading cancelled.")

async def run():
    # Scan for BLE devices and find the Polar H10
    print("Discovering Bluetooth Devices")
    devices = await BleakScanner.discover()
    polar_device = None
    for device in devices:
        if "Polar" in device.name:
            polar_device = device
            break

    if polar_device is None:
        print("Polar H10 not found")
        return

    print("Polar Device found: ", polar_device)
    # Connect to the Polar H10 device
    print("Connecting to device...")
    async with BleakClient(polar_device,timeout=20) as client:
        print(f"Connected to {polar_device.name}")

        # Start heart rate notifications
        await client.start_notify(HEART_RATE_MEASUREMENT_UUID, process_heart_rate_data)

        # Start reading battery level every 60 seconds in a separate task
        battery_task = asyncio.create_task(read_battery_level(client))

        try:
            # Keep the connection open indefinitely or adjust time here
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            print("Main task cancelled.")
        finally:
            # Properly stop notifications and clean up
            await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)
            battery_task.cancel()  # Cancel the battery level task
            try:
                await battery_task
            except asyncio.CancelledError:
                pass
            print("Cleaned up and disconnected.")

# Main function to handle async lifecycle with asyncio.run()

def set_hrm(monitor: HeartRateMonitor):
    global hrm
    hrm = monitor


def main():
    try:
        print("Running Bluetooth")
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Program interrupted. Shutting down...")
    finally:
        print("Event loop closed.")



if __name__ == "__main__":
    # restart_bluetooth_service()
    main()