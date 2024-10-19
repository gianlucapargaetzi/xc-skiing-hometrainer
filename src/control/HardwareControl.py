
from abc import ABC, abstractmethod
from typing import List, Union, Tuple

from pyModbusTCP.client import ModbusClient 
from minimalmodbus import Instrument

from dataclasses import dataclass

class MotorSpecs():
    """Struct-like class holding all motor specific parameters and properties
    """
    max_speed: float
    max_voltage: float

    max_torque: float

"""
How to use the interfaces:
"""







class HardwareInterface(ABC):
    """Abstract Class Interface for a Hardware implementation of a Controller Communication

    The functions read() and write() are communication protocol specific and need to be implemented by the derived Subclass
    """
    def __init__(specs: MotorSpecs = None):
        pass


    @abstractmethod
    def read(registers: Union[int, List[int]], type: str = "int") -> Union[int, float, List, None]:
        """Abstract Method to read Parameters from the Hardware. This class MUST BE defined in the specific Controller class (since it depends on the underlaying protocol)

        Args:
            registers (Union[int, List[int]]): Address(es) of register(s) to be read from
            type (str, optional): How the read binary values should be interpreted. Defaults to "int".

        Returns:
            Tuple[Union[int, float, List], bool]: Value(s) read from the Controller or None if reading was not successful
        """
        pass

    @abstractmethod
    def write(registers: Union[int, List[int]], values: Union[int, List[int], float, List[float]]) -> bool:
        """Abstract Method to write Parameters to the Hardware. This class MUST BE defined in the specific Controller class (since it depends on the underlaying protocol)

        Args:
            registers (Union[int, List[int]]): Address(es) of register(s) to be written to
            values (Union[int, List[int], float, List[float]]): Value(s) to be written

        Returns:
            bool: Successful or Not
        """
        pass




class MotorControllerInterface(ABC):
    """This interface defines functions which need to be implemented for a specific controller type in order for it to be usable in the overall controlling application
    """

    @abstractmethod
    def setup(motor_parameters: MotorSpecs) -> bool:
        """Function for setting up the Controller to be ready to use

        Args:
            motor_parameters (MotorSpecs): Motor parameters to be set on the controller

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_position(position: float) -> bool:
        """Setting the Target Position in the Controller

        Args:
            position (float): Target position in rad

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_velocity(velocity: float) -> bool:
        """Setting the Target Velocity in the Controller

        Args:
            velocity (float): Target velocity in rad/s

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def set_target_torque(velocity: float) -> bool:
        """Setting the Target Torque in the Controller

        Args:
            Torque (float): Target torque in Nm

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    def get_actual_position() -> Union[float, None]:
        """Reading the current position from the controller

        Returns:
            Union[float, None]: Either current position in rad or None if not successful
        """
        pass

    @abstractmethod
    def get_actual_velocity() -> Union[float, None]:
        """Reading the current velocity from the controller

        Returns:
            Union[float, None]: Either current velocity in rad/s or None if not successful
        """
        pass
    
    @abstractmethod
    def get_actual_torque() -> Union[float, None]:
        """Reading the current torque from the controller

        Returns:
            Union[float, None]: Either current torque in rad/s or None if not successful
        """
        pass

    @abstractmethod
    def zero(position_value: float = 0,  move: Union[float, None] = None) -> bool:
        """Zeroing the position

        Args:
            position_value (float, optional): The internal position value the position should get internally. Defaults to 0.
            move (Union[float, None], optional): Relative movement of motor before zeroing to position_value. Defaults to None (No movement before zeoring).

        Returns:
            bool: Success
        """
        pass

    @abstractmethod
    
    def start():
        """Starting the Motor
        """
        pass

    @abstractmethod
    def stop():
        """Stopping the Motor"""
        pass


class ModbusTCPController(HardwareInterface, ModbusClient):
    """Implementation for a ModbusTCP communication interface
    """
    def __init__(self, **kwargs):
        ModbusClient.__init__(**kwargs)
        pass


class ModbusRTUController(HardwareInterface, Instrument):
    """Implementation for a ModbusRTU communication interface
    """
    def __init__(self, **kwargs):
        Instrument.__init__(**kwargs)
        pass

class AnalogController(HardwareInterface):
    """Implementation for a ModbusRTU communication interface
    """ 


class ControllerXY(MotorControllerInterface):
    """This is the implementation of a specific Controller. Every abstract method of MotorControllerInterface has to be implemented here.
    """
    def __init__(self, hw: HardwareInterface):
        """Constructor

        Args:
            hw (HardwareInterface): This is the controller communication interface (i.e. ModbusTCPController / ModbusRTUController, EtherCatController, AnalogController), 
                                    whose read() and write() then can be used in the definition of the abstract functions of MotorControllerInterface
        """
        self._hw = hw
        pass

