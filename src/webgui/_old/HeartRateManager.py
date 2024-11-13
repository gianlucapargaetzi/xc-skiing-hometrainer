from flask_socketio import SocketIO
from threading import Thread, Lock, Event

import time

import asyncio
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from typing import List, Tuple


HEART_RATE_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


import logging


class BluetoothHeartRateSensor:
    def __init__(self, socket: SocketIO, hr_update_interval=0.3, discover_interval=30, timeout_interval=20):
        # Webpage Interface
        self._socket=socket
        self._update_interval = hr_update_interval
        self._discover_interval = discover_interval
        self._timeout_interval = timeout_interval


        self._gui_update_thread: Thread = None      # Updating thread to transmit heart rate via socket IO
        self._gui_update_thread_lock = Lock()       # Lock for accessing the updating thread
        self._stop_event = Event()

        ### Sensor Data has to be thread safe....

        ### Todo: Change to list of last_values in order to cache if more than one value gets written by BLUETOOTH
        self._hr_data_lock = Lock()                                                             
        self._last_heartrate = {"heart_rate": 0, "timestamp": 0, "connected": False}
        self._heartrate_changed = True

        self._battery_data_lock = Lock()
        self._battery_status: int = None
        self._battery_status_changed = False


        self._device_list_lock = Lock()
        self._device_list: List[BLEDevice] = []



        
        self._sensor_thread_lock = Lock()
        self._sensor_thread: Thread = None
        self._disconnect_event = asyncio.Event()

        self._connected_device: BleakClient = None

        self._start_time = time.time()




    # Thread for continuous GUI update
    def _update_gui(self):
        self._last_emmited =  {"heart_rate": 0, "timestamp": 0, "connected": False}
        while not self._stop_event.is_set():
            with self._hr_data_lock:
                if self._heartrate_changed:
                    self._heartrate_changed = False
                    logging.info(f"Emit {self._last_heartrate}")
                    self._socket.emit("heart_rate_update", self._last_heartrate)  # Emit heart rate
                    self._last_emmited = self._last_heartrate

            self._socket.sleep(self._update_interval)


    def available_sensors(self) -> dict:
        """Discovers all Bluetooth Heart Rate Sensors

        Returns:
            dict: List of Sensors Containing name and address
        """

        sensor_list = {'hr_sensors': []}
        async def find_heart_rate_sensors():
            """Discover and list all BLE devices that are heart rate sensors."""

            logging.info("Discovering Bluetooth Devices...")
            devices = await BleakScanner.discover()

            with self._device_list_lock:
                self._device_list.clear()
                for device in devices:
                    if HEART_RATE_SERVICE_UUID in device.details['props']['UUIDs']: # Device is assumed to be Heart Rate Sensor when it has Heart Rate Service
                        self._device_list.append(device)
                        sensor_list['hr_sensors'].append({'name': device.name, 'address': device.address})
                    
            logging.info(f"Sensor List: {sensor_list}")

        try:
            asyncio.run(find_heart_rate_sensors())
        except Exception as e:
            logging.error(str(e))
        return sensor_list
    
    # Thread for sensor async sensor readout:
    def _read_sensor(self):
        def _hr_notify_callback(sender: int, data: bytearray):
            # Byte 0: Flags
            flags = data[0]
            # Byte 1 or 2: Heart rate value (8-bit or 16-bit depending on flags)
            heart_rate = data[1] if flags & 0b00000001 == 0 else (data[1] + (data[2] << 8))
            self.set_value(heart_rate)
            logging.info(f"Heart Rate: {heart_rate} bpm")

        # Function to read and display battery level
        async def _read_battery_level(client: BleakClient):
            try:
                while True:
                    battery_level = await client.read_gatt_char(BATTERY_LEVEL_UUID)
                    logging.info(f"Battery Level: {int(battery_level[0])}%")
                    await asyncio.sleep(60)  # Sleep for 1 minute
            except asyncio.CancelledError:
                logging.info("Battery level reading cancelled.")


        async def sensor_readout():
            async with self._connected_device as client:
                logging.info(f'Connected to {self._connected_device.address}')
                # Start heart rate notifications
                await client.start_notify(HEART_RATE_MEASUREMENT_UUID, _hr_notify_callback)

                # Start reading battery level every 60 seconds in a separate task
                battery_task = asyncio.create_task(_read_battery_level(client))

                try:
                    # Keep the connection open indefinitely or adjust time here
                    await self._disconnect_event.wait()
                    logging.info("Disconnect event occured")
                except asyncio.CancelledError:
                    logging.warning("Sensor Readout aborted")
                finally:
                    # Properly stop notifications and clean up
                    try:
                        await client.stop_notify(HEART_RATE_MEASUREMENT_UUID)
                    except:
                        pass

                    battery_task.cancel()  # Cancel the battery level task

                    try:
                        await battery_task
                    except asyncio.CancelledError:
                        pass

        asyncio.run(sensor_readout())

    def disconnect_sensor(self, join=True):
        logging.info(f"Disconnecting device {self._connected_device.address}")
        self._disconnect_event.set()
        logging.info("Waiting for sensor thread to finish")
        with self._sensor_thread_lock:
            if join:
                self._sensor_thread.join()
            self._connected_device = None
            self._sensor_thread = None
            self._disconnect_event.clear()
        
        logging.info("Successfully cleaned up sensor thread")

    def _sensor_disconnect_callback(self, client: BleakClient) -> None:
        self.disconnect_sensor(join=False)
        self.set_value(0, False)
        pass

    # Function to call to start sensor readout
    def connect_sensor(self, mac_address) -> int:
        hr_sensor: BLEDevice = None
        with self._device_list_lock:
            for dev in self._device_list:
                if dev.address == mac_address:
                    hr_sensor = dev
        
        if hr_sensor is None:
            logging.error(f"MAC-Address {mac_address} not found in discovered sensor list!")
            return -1
        
        logging.info(f"Setting up sensor readout thread with device {hr_sensor.name}  ---  f{hr_sensor.address}")

        with self._sensor_thread_lock:
            if self._sensor_thread is None or not self._sensor_thread.is_alive():
                self._connected_device = BleakClient(hr_sensor, disconnected_callback=self._sensor_disconnect_callback, timeout=self._timeout_interval)
                self._sensor_thread = Thread(target=self._read_sensor)
                self._sensor_thread.start()

        return 0

    def set_value(self, heart_rate: int, connected=True):
        uptime = time.time() - self._start_time
        if heart_rate <= 0:
            heart_rate = 0
            connected = False

        with self._hr_data_lock:
            self._last_heartrate = {"heart_rate": heart_rate, "timestamp": uptime, "connected": connected}
            self._heartrate_changed = True

    def start_gui_update(self):
        with self._gui_update_thread_lock:
            if self._gui_update_thread is None:
                self._gui_update_thread = self._socket.start_background_task(self._update_gui)

    def stop_gui_update(self):
        with self._gui_update_thread_lock:
            if self._gui_update_thread is not None and self._gui_update_thread.is_alive():
                self._stop_event.set()
                self._gui_update_thread.join()
                self._stop_event.clear()
                