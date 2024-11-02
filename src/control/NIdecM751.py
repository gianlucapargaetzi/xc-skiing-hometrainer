
from abc import ABC, abstractmethod
from typing import List, Union, Tuple

import serial
import minimalmodbus
from threading import Lock

from dataclasses import dataclass

from HardwareControlInterface import MotorControllerInterface, MotorSpecs

import logging


ACTUAL_VELOCITY_REG=10
ACTUAL_TORQUE_REG=10
ACTUAL_REVS_REG=10
ACTUAL_POS_REG=10

SET_VELOCITY_REG=10
SET_TORQUE_REG=10
SET_POSITION_REG=10




class NidecM751RTU(MotorControllerInterface, minimalmodbus.Instrument):
    """This is the implementation of a specific Controller. Every abstract method of MotorControllerInterface has to be implemented here.
    """
    def __init__(self, device="/dev/ttyACM0", baud_rate=115200, timeout=2, **kwargs):
        minimalmodbus.Instrument.__init__(port=device, baud_rate=baud_rate, **kwargs)
        self.serial.parity = serial.PARITY_NONE
        self.serial.bytesize = 8
        self.serial.stopbits = 1
        self.serial.timeout = timeout
        self.address = 1
        self.mode = minimalmodbus.MODE_RTU
        self.clear_buffers_before_each_transaction = True

        self._lock = Lock()

    # Use "with" programming paradigm to lock hardware ressource access
    def __enter__(self):
        self._lock.acquire()

    def __exit__(self):
        self._lock.release()

    def set_target_position(self, position: float) -> bool:
        logging.debug(f"Setting target position '{position}'")
        with self:
            try:
                self.write_register(SET_POSITION_REG, position, 1, 6,  True)
            except Exception as e:
                logging.info(str(e))
                return False     

       
    def setup(self, motor_parameters: MotorSpecs) -> bool:

        pass

    def set_mode(self, mode:int) -> bool:
        pass

    def set_target_velocity(self, velocity: float) -> bool:
        pass

    def set_target_torque(self, velocity: float) -> bool:
        pass

    def get_actual_position(self) -> Union[float, None]:
        pass

    def get_actual_velocity(self) -> Union[float, None]:
        pass
    
    def get_actual_torque(self) -> Union[float, None]:
        pass

    def zero(self, position_value: float = 0,  move: Union[float, None] = None) -> bool:
        pass

    def start(self):
        pass

    def stop(self):
        pass



