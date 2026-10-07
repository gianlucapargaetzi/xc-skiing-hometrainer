
from abc import ABC, abstractmethod
from typing import List, Union, Tuple
from dataclasses import dataclass

@dataclass
class SystemSpecifications:
    rated_torque: float                         # in Nm
    max_torque: float                           # in Nm
    rated_speed: int                            # in RPM
    max_speed: int                              # in RPM
    brake_resistor_rated_power: int             # in kW



class MotorControllerInterface(ABC):
    """This interface defines functions which need to be implemented for a specific controller type in order for it to be usable in the overall controlling application
    """

    @abstractmethod
    def program(self, specs: SystemSpecifications) -> bool:
        """Function used for initial programming of controller (might not be needed)

        Args:
            specs (SystemSpecifications): Specs about system needed to programm the controller

        Returns:
            bool: Success
        """

    @abstractmethod
    def setup(self, positive_limit: int, negative_limit: int) -> bool:
        """Function for setting up the Controller after startup to be ready to use

        Args:
            positive_limit (int): positive position limit (exceeding this will cause controller fault)
            negative_limit (int): negative position limit (exceeding this will cause controller fault)

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_velocity(self, velocity: float) -> bool:
        """Setting the Target Velocity in the Controller

        Args:
            velocity (float): Target velocity in rpm

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_torque(self, velocity: float) -> bool:
        """Setting the Target Torque in the Controller

        Args:
            Torque (float): Target torque in %

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def get_actual_position(self) -> Union[int, None]:
        """Reading the current position from the controller

        Returns:
            Union[int, None]: Either current position in increments or None if not successful
        """
        pass

    @abstractmethod
    def get_actual_velocity(self) -> Union[float, None]:
        """Reading the current velocity from the controller

        Returns:
            Union[float, None]: Either current velocity in rpm or None if not successful
        """
        pass
    
    @abstractmethod
    def get_actual_torque(self) -> Union[float, None]:
        """Reading the current torque from the controller

        Returns:
            Union[float, None]: Either current torque in % or None if not successful
        """
        pass

    @abstractmethod
    def start(self) -> bool:
        """Starting the Motor
        """
        pass

    @abstractmethod
    def stop(self) -> bool:
        """Stopping the Motor"""
        pass

    @abstractmethod
    def get_errors(self) -> Union[int, None]:
        """Reading the errors from the controller

        Returns:
            Union[int, None]: Either returns error code(s) or None if not successful
        """
        pass

    @abstractmethod
    def trigger_watchdog(self) -> bool:
        """Trigger the watchdog safety function as "Controller still connected"-signal

        Returns:
            bool: Wether triggering watchdog was successful
        """

    @abstractmethod
    def read(self, **kwargs) -> bool:
        """Wrapper for underlaying protocol reading function
        """
        pass

    @abstractmethod
    def write(self, **kwargs) -> bool:
        """Wrapper for underlaying protocol writing function
        """
        pass



