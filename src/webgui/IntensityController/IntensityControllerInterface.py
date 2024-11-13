from abc import ABC, abstractmethod
from threading import Lock

class IntensityControllerInterface(ABC):
    def __init__(self, name="UnknownIntensityController"):
        self._intensity_lock = Lock()
        self._intensity: float = 0.0
        self._name = name

    def get_intensity(self) -> float:
        with self._intensity_lock:
            return self._intensity
        
    