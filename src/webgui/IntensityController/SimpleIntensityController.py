from threading import Lock
from IntensityController.IntensityControllerInterface import IntensityControllerInterface
from BasicWebGUI import BackendNode, Backend
from flask import jsonify

MIN_VALUE = 5
INIT_VALUE = 60
MAX_VALUE = 120
STEP = 5

class SimpleIntensityController(BackendNode):
    def __init__(self):
        BackendNode.__init__(self, "SimpleIntensityControllerBackend", update_interval=None)
        IntensityControllerInterface.__init__(self, "SimpleIntensityController")
        self._intensity_lock = Lock()
        self._intensity = INIT_VALUE
        self.active = True  # Steuerung für laufende Prozesse

        # Flask-Routen
        self._flask_requests.append(("/set_to_20", self._set_to_20, ['POST']))
        self._flask_requests.append(("/decrement", self._decrement, ['POST']))
        self._flask_requests.append(("/increment", self._increment, ['POST']))
        self._flask_requests.append(("/get_value", self._get_value, ['GET']))
        self._flask_requests.append(("/stop", self._stop, ['POST']))  # Neue Route für Stop-Button

        Backend().registerNode(self)
        self.cnt = 0

    def __str__(self):
        return "SimpleIntensityController"

    def _set_to_20(self):
        with self._intensity_lock:
            self._intensity = 20
            return jsonify({"value": self._intensity})

    def _decrement(self):
        with self._intensity_lock:
            self._intensity = max(self._intensity - STEP, MIN_VALUE)
            return jsonify({"value": self._intensity})

    def _increment(self):
        with self._intensity_lock:
            self._intensity = min(self._intensity + STEP, MAX_VALUE)
            return jsonify({"value": self._intensity})

    def _get_value(self):
        with self._intensity_lock:
            return jsonify({"value": self._intensity})

    def _stop(self):
        self.stop()  # Ruft stop()-Methode auf
        return jsonify({"status": "stopped"})

    def getIntensity(self) -> float:
        return self._intensity

    # Steuerungsmethoden (erweiterbar)
    def start(self):
        self.active = True
        print("SimpleIntensityController started.")

    def stop(self):
        self.active = False
        print("SimpleIntensityController stopped.")

    def pause(self):
        pass

    def init(self):
        pass

    def uninit(self):
        pass

    def publish(self):
        pass
