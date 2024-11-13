
from flask import Flask, render_template
from flask_socketio import SocketIO
import time
import random
import threading

from flask import Flask, jsonify


import os
import random

import logging

import numpy as np

from HeartRateManager import BluetoothHeartRateSensor

from threading import Thread, Lock

profiles_data = [
    {"file_name": "alice.cgf", "name": "Alice", "age": 30, "max_heart_rate": 180, "mac_address": "00:1B:44:11:3A:B7", "pole_length": 120},
    {"file_name": "bob.cfg", "name": "Bob", "age": 25, "max_heart_rate": 175, "mac_address": "00:1B:44:11:3A:B8", "pole_length": 115},
    # Add more profiles as needed
]

class WebGUIBackend(Flask):
    def __init__(self, importName):
        super().__init__(importName)
        # self.config['UPLOAD_FOLDER'] = 'uploads/'  # Folder to save uploaded files
        # self.config['ALLOWED_EXTENSIONS'] = {'gpx'}  # Restrict file type to GPX
        # self.config['gps_loaded'] = False
        # # Create upload directory if not exists
        # os.makedirs(self.config['UPLOAD_FOLDER'], exist_ok=True)
        self._async_mode=None


        self.add_routes()
        self._socket = SocketIO(self, async_mode=self._async_mode)
        self._socket.on_event('connect', self.socket_connect)
        self._hrm = BluetoothHeartRateSensor(self._socket)

        # self.t: Thread = None
        # self.lock = Lock()

    # def thread(self):
    #     hr = 0
        # while True:
        #     self._hrm.set_value(hr)
        #     time.sleep(20)
        #     hr+=2

    # t = None
    # lock = Lock()


    def socket_connect(self, msg):
        self._hrm.start_gui_update()
        # with self.lock:
        #     if self.t is None:
        #         self.t = Thread(target=self.thread)
        #         self.t.start()

        sensors = self._hrm.available_sensors()
        if len(sensors['hr_sensors']) > 0:
            self._hrm.connect_sensor(sensors['hr_sensors'][0]['address'])
        


    def add_routes(self):
        # self.add_url_rule("/", view_func=self._index)
        self.add_url_rule("/", view_func=self._settings)
        self.add_url_rule("/api/profiles", view_func=self._get_profiles, methods=['GET'])


    def _get_profiles(self):
        return jsonify({"profiles": profiles_data})
        # self.add_url_rule("/settings", view_func=self._settings)
        # self.add_url_rule("/set-gpx", view_func=self._set_gpx, methods=['POST'])
        # self.add_url_rule("/update-checkbox", view_func=self._set_control_mode, methods=['POST'])
        # self.add_url_rule("/current-position", view_func=self._get_position)
        # self.add_url_rule("/release-session", view_func=self._release_session, methods=['POST'])

    def run_backend(self):
        self._socket.run(self)
        
        
    def _index(self):
        return render_template('index.html', async_mode=self._socket.async_mode)
    
    def _settings(self):
        return render_template('settings.html', async_mode=self._socket.async_mode)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app = WebGUIBackend(__name__)
    app.run_backend()