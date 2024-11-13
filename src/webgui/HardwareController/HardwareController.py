
MOUNTING_HEIGHT=2.0
POLE_LENGTH=1.5
INCREMENTS_PER_REVOLUTION=1024
NUM_REVOLUTIONS=12
PULLEY_DIAMETER= 0.055
WATCHDOG_TIMEOUT=2

WATCHDOG_UPDATE_INTERVAL = WATCHDOG_TIMEOUT/2

from typing import List

from HardwareController.NidecM751 import NidecM751TCP
from webgui.HardwareController.MotorControllerInterface import MotorControllerInterface, SystemSpecifications

from threading import Thread
from enum import Enum

import numpy as np

import logging

from time import time, sleep

from dataclasses import dataclass

@dataclass
class MeasurementValues:
    time: float
    force: float
    speed: float
    position: float
    power: float


class ControllerState(Enum):
    UNINITIALIZED = 1
    INITIALIZED = 2     # Homed and ready for run
    RUNNING = 3         # Running
    ERROR = 4

def map_value(x, in_min, in_max, out_min, out_max):
    """
    Maps a value x from the input range [in_min, in_max]
    to the output range [out_min, out_max].
    
    Parameters:
    x (float): The value to be mapped.
    in_min (float): Minimum value of the input range.
    in_max (float): Maximum value of the input range.
    out_min (float): Minimum value of the output range.
    out_max (float): Maximum value of the output range.
    
    Returns:
    float: The mapped value in the output range.
    """
    # Ensure the input range is valid
    if in_max - in_min == 0:
        raise ValueError("Input range cannot be zero.")
    
    # Apply the mapping formula
    mapped_value = out_min + (x - in_min) * (out_max - out_min) / (in_max - in_min)
    mapped_value = max(out_min, min(mapped_value, out_max))

    return mapped_value



class Controller():
    def __init__(self):
        self._torqueLookup: None
        self._state: ControllerState = ControllerState.UNINITIALIZED
        self._hw: MotorControllerInterface = None
        self._running_thread = Thread(target=self._run)

        self._pole_length = POLE_LENGTH
        self._mounting_height = MOUNTING_HEIGHT

        # These parameters should be set during homing sequence, so that the current rotor position can be mapped to a speed
        self._start_position: int = 0 # Encoder value for upper limit (Rope fully wound up)
        self._end_position: int = 0 # Encoder value for lower limit (Rope fully unwound)

        self._last_update_timestamp: float = time()
        self._last_watchdog_timestamp: float = time()-WATCHDOG_UPDATE_INTERVAL

    @property
    def hw(self) -> MotorControllerInterface:
        return self._hw
    
    @hw.setter
    def hw(self, hw: MotorControllerInterface):
        self._hw = hw




    def init(self) -> bool:
        """Initialisation of Hardware. This should include homing the system and setting up all necessary parameters for normal operation mode

        Returns:
            bool: Success
        """

        if self._pole_length == 0:
            logging.log(logging.ERROR, "Pole length not set")
            return False

        if self._mounting_height == 0:
            logging.log(logging.ERROR, "Mouning height not set")
            return False
        
        if self._hw is None:
            logging.log(logging.ERROR, "No controller specified")
            return False
        
        if self._state != ControllerState.UNINITIALIZED:
            logging.log(logging.ERROR, "Controller not in uninitialized state")
            return False

        # Homing
        # Abrollen
        end = self.hw.get_actual_position()


        # Aufrollen bis Limit
        self.hw.set_target_velocity(50)
        while (True):
            sleep(0.2)

            # TODO: Warte bis homing fertig (entweder Stromschwelle oder Endposition erreicht)
            break

        start = self.hw.get_actual_position()
        self._start_position = 0
        self._end_position = end - start
        self.hw.setup(self._start_position, self._end_position)

        


    def start(self) -> bool:
        """Start the controller update thread

        Returns:
            bool: Success
        """

        if (self._state != ControllerState.INITIALIZED):
            logging.log(logging.ERROR, "Controller not initialized or already running!")
            return False

        self._running_thread.start()
        return True

    def stop(self) -> bool:
        """Stop the controller update thread

        Returns:
            bool: Success
        """
        if (self._state != ControllerState.RUNNING):
            logging.log(logging.ERROR, "Controller not running!")

        self._state = ControllerState.INITIALIZED
        self._running_thread.join() # Wait for running thread to terminate
        

    def _home(self):
        pass

    def _run(self):
        # Activate the Watchdog functionality

        while (self._state == ControllerState.RUNNING):
            try: 
                t = time()
                if (abs(t - self._last_watchdog_timestamp) > WATCHDOG_UPDATE_INTERVAL):
                    self._hw.trigger_watchdog()
                    self._last_watchdog_timestamp = t
                    # Update Watchdog

                self._last_update_timestamp = t

            except Exception as e:
                logging.log(logging.ERROR, str(e))
                self._state = ControllerState.ERROR

        # Deactivate the Watchdog functionality