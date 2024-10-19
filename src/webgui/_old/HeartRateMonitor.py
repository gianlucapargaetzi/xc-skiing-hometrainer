from flask_socketio import SocketIO
from threading import Thread, Lock

import time

import asyncio

class HeartRateMonitor():
    def __init__(self, socket: SocketIO, update_interval=1):
        self._socket=socket
        self._update_interval = update_interval

        self._gui_update_thread: Thread = None
        self._gui_update_thread_lock = Lock()
        self._is_running = False


        self._lock = Lock()
        self._last_heartrate = {"heart_rate": 0, "timestamp": 0, "connected": False}
        self._new_value = True

        self._start_time = time.time()

    def _update_gui(self):
        self._last_emmited =  {"heart_rate": 0, "timestamp": 0, "connected": False}
        while True:
            value: dict = None
            queue = False
            with self._lock:
                if self._new_value and self._last_heartrate is not None and self._last_heartrate["heart_rate"] != self._last_emmited["heart_rate"]:
                    value = self._last_heartrate
                    self._new_value = False
                    print(f"Emit {self._last_heartrate}")
                    self._socket.emit("heart_rate_update", value)  # Emit heart rate
                    self._last_emmited = value

            self._socket.sleep(self._update_interval)

    def set_value(self, heart_rate: int):
        uptime = time.time() - self._start_time
        connected = True
        if heart_rate <= 0:
            heart_rate = 0
            connected = False

        with self._lock:
            self._last_heartrate = {"heart_rate": heart_rate, "timestamp": uptime, "connected": connected}
            self._new_value = True

    def start(self):
        with self._gui_update_thread_lock:
            if self._gui_update_thread is None:
                self._gui_update_thread = self._socket.start_background_task(self._update_gui)
                print("Started")