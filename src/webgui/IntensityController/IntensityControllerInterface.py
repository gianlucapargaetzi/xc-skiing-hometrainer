from abc import ABC, abstractmethod
from threading import Lock

class IntensityControllerInterface(ABC):
    """The IntensitiyControllerInterface is used to implement differen types of IntensityControllers with a universal interface to other control elements.
    """

    def __init__(self, name="UnknownIntensityController"):
        # self._intensity_lock = Lock()
        # self._intensity: float = 0.0
        self._name = name

    @abstractmethod
    def get_intensity(self) -> float:
        """This is the interface for elements using the IntensityControllerInterface within the control structure. 
        Every other control is controller specific and has to be implemented in the class using this interface.

        Returns:
            float: Float value of intensity in %
        """
        pass
        # with self._intensity_lock:
        #     return self._intensity
        
