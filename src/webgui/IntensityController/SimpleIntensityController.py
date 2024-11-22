from threading import Lock
from IntensityController.IntensityControllerInterface import IntensityControllerInterface
from BasicWebGUI import BackendNode, Backend
from flask import jsonify

MIN_VALUE = 5
MAX_VALUE = 120
STEP = 5

class SimpleIntensityController(BackendNode):
    def __init__(self):
        super().__init__("SimpleIntensityControllerBackend", update_interval=None) # No publishing via socket IO...
        self._intensity_lock = Lock()
        self._intensity = 40
        self._flask_requests.append(("/set_to_20", self.set_to_20, ['POST']))
        self._flask_requests.append(("/decrement", self.decrement, ['POST']))
        self._flask_requests.append(("/increment", self.increment, ['POST']))
        self._flask_requests.append(("/get_value", self.get_value, ['GET']))

        Backend().registerNode(self)
        self.cnt = 0

    def __str__(self):
        return "SimpleIntensityController"

    def set_to_20(self):
        with self._intensity_lock:
            self._intensity = 20
            return jsonify({"value": self._intensity})

    def decrement(self):
        with self._intensity_lock:
            self._intensity = max(self._intensity - STEP, MIN_VALUE)
            return jsonify({"value": self._intensity})
        
    def increment(self):
        with self._intensity_lock:
            self._intensity = min(self._intensity + STEP, MAX_VALUE)
            return jsonify({"value": self._intensity})

    def get_value(self):
        with self._intensity_lock:
            json = jsonify({"value": self._intensity})
        return json


    def publish(self):
        pass