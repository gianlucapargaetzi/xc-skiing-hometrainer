from threading import Lock
from IntensityController.IntensityControllerInterface import IntensityControllerInterface
from BasicWebGUI import BackendNode, Backend
from flask import jsonify

MIN_VALUE = 5
DEFAULT_INIT_VALUE = 60
MAX_VALUE = 200
STEP = 5


class SimpleIntensityController(BackendNode, IntensityControllerInterface):
    def __init__(self, init_value: float = DEFAULT_INIT_VALUE):
        BackendNode.__init__(self, "SimpleIntensityControllerBackend", update_interval=None)
        IntensityControllerInterface.__init__(self, "SimpleIntensityController")

        self._intensity_lock = Lock()
        self._init_value = self._clamp_intensity(init_value)
        self._intensity = self._init_value

        self.active = True
        self.stop_requested = False

        self._flask_requests.append(("/set_to_20", self._set_to_20, ['POST']))
        self._flask_requests.append(("/decrement", self._decrement, ['POST']))
        self._flask_requests.append(("/increment", self._increment, ['POST']))
        self._flask_requests.append(("/get_value", self._get_value, ['GET']))
        self._flask_requests.append(("/stop", self._stop, ['POST']))

        Backend().registerNode(self)
        self.cnt = 0

    def __str__(self):
        return "SimpleIntensityController"

    def _clamp_intensity(self, value: float) -> int:
        return int(max(MIN_VALUE, min(value, MAX_VALUE)))

    def _resume_training_if_needed(self):
        self.active = True
        self.stop_requested = False

    def set_init_value(self, init_value: float, apply_now: bool = False):
        with self._intensity_lock:
            self._init_value = self._clamp_intensity(init_value)
            if apply_now:
                self._intensity = self._init_value
            return {
                "init_value": self._init_value,
                "value": self._intensity,
                "active": self.active,
                "stop_requested": self.stop_requested
            }

    def _set_to_20(self):
        with self._intensity_lock:
            self._intensity = self._clamp_intensity(20)
            self._resume_training_if_needed()
            return jsonify({
                "value": self._intensity,
                "init_value": self._init_value,
                "active": self.active,
                "stop_requested": self.stop_requested
            })

    def _decrement(self):
        with self._intensity_lock:
            self._intensity = self._clamp_intensity(self._intensity - STEP)
            self._resume_training_if_needed()
            return jsonify({
                "value": self._intensity,
                "init_value": self._init_value,
                "active": self.active,
                "stop_requested": self.stop_requested
            })

    def _increment(self):
        with self._intensity_lock:
            self._intensity = self._clamp_intensity(self._intensity + STEP)
            self._resume_training_if_needed()
            return jsonify({
                "value": self._intensity,
                "init_value": self._init_value,
                "active": self.active,
                "stop_requested": self.stop_requested
            })

    def _get_value(self):
        with self._intensity_lock:
            self._intensity = self._clamp_intensity(self._intensity)
            return jsonify({
                "value": self._intensity,
                "init_value": self._init_value,
                "active": self.active,
                "stop_requested": self.stop_requested
            })

    def _stop(self):
        self.stop()
        return jsonify({
            "status": "stopped",
            "value": self._intensity,
            "init_value": self._init_value,
            "active": self.active,
            "stop_requested": self.stop_requested
        })

    def getIntensity(self) -> float:
        with self._intensity_lock:
            self._intensity = self._clamp_intensity(self._intensity)
            return self._intensity

    def start(self):
        with self._intensity_lock:
            self.active = True
            self.stop_requested = False
        print("SimpleIntensityController started.")

    def stop(self):
        with self._intensity_lock:
            self.active = False
            self.stop_requested = True
        print("SimpleIntensityController stopped.")

    def pause(self):
        with self._intensity_lock:
            self.active = False

    def init(self):
        pass

    def uninit(self):
        pass

    def publish(self):
        pass