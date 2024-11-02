
from abc import ABC, abstractmethod
from typing import List, Union, Tuple

from dataclasses import dataclass


from threading import Lock

class MotorSpecs():
    """Struct-like class holding all motor specific parameters and properties
    """
    max_speed: float
    max_voltage: float

    max_torque: float

class MotorControllerInterface(ABC):
    """This interface defines functions which need to be implemented for a specific controller type in order for it to be usable in the overall controlling application
    """

    @abstractmethod
    def setup(self, motor_parameters: MotorSpecs) -> bool:
        """Function for setting up the Controller to be ready to use

        Args:
            motor_parameters (MotorSpecs): Motor parameters to be set on the controller

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_mode(self, mode:int) -> bool:
        """Function for setting up the Controller mode

        Args:
            mode (int): Mode to be set

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_position(self, position: float) -> bool:
        """Setting the Target Position in the Controller

        Args:
            position (float): Target position in rad

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_velocity(self, velocity: float) -> bool:
        """Setting the Target Velocity in the Controller

        Args:
            velocity (float): Target velocity in rad/s

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_torque(self, velocity: float) -> bool:
        """Setting the Target Torque in the Controller

        Args:
            Torque (float): Target torque in Nm

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def get_actual_position(self) -> Union[float, None]:
        """Reading the current position from the controller

        Returns:
            Union[float, None]: Either current position in rad or None if not successful
        """
        pass

    @abstractmethod
    def get_actual_velocity(self) -> Union[float, None]:
        """Reading the current velocity from the controller

        Returns:
            Union[float, None]: Either current velocity in rad/s or None if not successful
        """
        pass
    
    @abstractmethod
    def get_actual_torque(self) -> Union[float, None]:
        """Reading the current torque from the controller

        Returns:
            Union[float, None]: Either current torque in rad/s or None if not successful
        """
        pass

    @abstractmethod
    def zero(self, position_value: float = 0,  move: Union[float, None] = None) -> bool:
        """Zeroing the position

        Args:
            position_value (float, optional): The internal position value the position should get internally. Defaults to 0.
            move (Union[float, None], optional): Relative movement of motor before zeroing to position_value. Defaults to None (No movement before zeoring).

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def start(self):
        """Starting the Motor
        """
        pass

    @abstractmethod
    def stop(self):
        """Stopping the Motor"""
        pass
