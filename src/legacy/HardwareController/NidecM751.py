
from abc import ABC, abstractmethod
from typing import List, Union, Tuple

import serial
from pyModbusTCP.client import ModbusClient
from threading import Lock

from dataclasses import dataclass

from HardwareController.MotorControllerInterface import MotorControllerInterface, SystemSpecifications

from Utils.TypeConversion import toInt16
import logging


REGISTER_GET_POSITION=327
NUM_REGS_GET_POSITION=2
UPPER_WORD_INDEX=0
LOWER_WORD_INDEX=1


REGISTER_GET_VELOCITY=301
NUM_REGS_GET_VELOCITY=1
MULTIPLIER_GET_VELOCITY=1/10

REGISTER_GET_TORQUE=419
NUM_REGS_GET_TORQUE=1
MULTIPLIER_GET_TORQUE=1/10

REGISTER_SET_DIRECTION=629


REGISTER_SET_VELOCITY=117
MULTIPLIER_SET_VELOCITY=10

REGISTER_SET_TORQUE=408
MULTIPLIER_SET_TORQUE=10

REGISTER_ENABLE_WATCHDOG=642
ENABLE_WATCHDOG=1
DISABLE_WATCHDOG=0

REGISTER_TRIGGER_WATCHDOG=641
WATCHDOG_BIT=1 << 14

REGISTER_DRIVE_RESET=1032






# This is so that velocity and torque does not get written everytime it changes only slighly, but only when it changes "noticable"
VELOCITY_UPDATE_THRESHOLD=10 
TORQUE_UPDATE_THRESHOLD=0.5





class NidecM751TCP(MotorControllerInterface, ModbusClient):
    """This is the implementation of a specific Controller. Every abstract method of MotorControllerInterface has to be implemented here.
    """
    def __init__(self, **kwargs):
        ModbusClient.__init__(**kwargs)

        self._lock = Lock()
        self._last_velocity: float = 0.0
        self._last_torque: float = 0

    # Use "with" programming paradigm to lock hardware ressource access
    def __enter__(self):
        self._lock.acquire()

    def __exit__(self):
        self._lock.release()

    def program(self, specs: SystemSpecifications) -> bool:
        pass

    def setup(positive_limit: int, negative_limit: int) -> bool:
        return True

    def set_target_velocity(self, velocity: float) -> bool:
        # If velocity is almost the same as last set velocity, do not update (To minimize network traffic). Only always update zero
        if (velocity != 0 and (abs(self._last_velocity-velocity) < VELOCITY_UPDATE_THRESHOLD)):
            return True
    
        self._last_velocity = velocity
        return self.write_single_register(REGISTER_SET_DIRECTION, int(velocity * MULTIPLIER_SET_VELOCITY))

    def set_target_torque(self, torque: float) -> bool:
        # If differenc to last target torque is not bigger than TORQUE_UPDATE_THRESHOLD, do not set torque
        if (torque != 0 and abs(self._last_torque-torque) < TORQUE_UPDATE_THRESHOLD):
            return True
        
        self._last_torque = torque
        return self.write_single_register(REGISTER_SET_TORQUE, int(torque * MULTIPLIER_GET_TORQUE))

    
    def get_actual_position(self) -> Union[int, None]:
        values = self.read_holding_registers(REGISTER_GET_POSITION,NUM_REGS_GET_POSITION)
        if values is None:
            return None
        return values[UPPER_WORD_INDEX]* 2**16 +  values[LOWER_WORD_INDEX]

    def get_actual_velocity(self) -> Union[float, None]:
        values = self.read_holding_registers(REGISTER_GET_VELOCITY,NUM_REGS_GET_VELOCITY)
        if values is None:
            return None
        return toInt16(values[0])*MULTIPLIER_GET_VELOCITY

    
    def get_actual_torque(self) -> Union[float, None]:
        values = self.read_holding_registers(REGISTER_GET_TORQUE,NUM_REGS_GET_TORQUE)
        if values is None:
            return None
        return toInt16(values[0])*MULTIPLIER_GET_TORQUE
    

    def start(self) -> bool:
        # TODO: PAJ: Aktiviere Watchdog und aktive Bestromung
        ret = self.write_single_register(REGISTER_DRIVE_RESET, 1)
        ret |= self.write_single_register(REGISTER_DRIVE_RESET, 0)

        if ret:
            logging.log(logging.ERROR, "Drive Reset failed")
            return False
        

        ret = self.write_single_register(REGISTER_ENABLE_WATCHDOG, ENABLE_WATCHDOG)
        ret |= self.trigger_watchdog()

        if ret:
            logging.log(logging.ERROR, "Enabling Watchdog failed")
            return False

        return True

    def stop(self) -> bool:
        # TODO: PAJ: Deaktiviere Watchdog und aktive Bestromung
        return self.write_single_register(REGISTER_ENABLE_WATCHDOG, DISABLE_WATCHDOG)

    def get_errors(self) -> Union[int, None]:
        pass

    def trigger_watchdog(self) -> bool:
        # TODO: PAJ: Schreibe Watchdog register
        ret = self.write_single_register(REGISTER_TRIGGER_WATCHDOG, WATCHDOG_BIT)
        ret |= self.write_single_register(REGISTER_TRIGGER_WATCHDOG, 0)
        return ret
    

    def read(self, **kwargs) -> bool:
        return self.read_holding_registers(**kwargs)
    
    def write(self, **kwargs) -> bool:
        return self.write_single_register(**kwargs)

