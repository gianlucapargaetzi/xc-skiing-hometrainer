from abc import ABC, abstractmethod

import numpy as np


class ValueHandler(ABC):
    def __init__(self, node_name="Unknown"):
        self._node_name = node_name

    def __str__(self):
        return f"ValueHandler | {self._node_name}"

    @abstractmethod
    def evaluateValue(self, measurement_value: np.ndarray):
        """evaluate a set of hardware measurements

        Args:
            measurement_value (np.ndarray): Measurement values. Should be a numpy array np.array
        """
        pass
