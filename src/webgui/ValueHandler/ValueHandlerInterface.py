from abc import ABC, abstractmethod
from typing import List, Tuple
from HardwareController.HardwareController import MeasurementValues
from Utils.CustomLogger import CustomLogger
from threading import Lock


from Utils.CustomLogger import CustomLogger

from threading import Event, Thread

from time import time, sleep

import numpy as np

class ValueHandler(ABC):
    def __init__(self, node_name = "Unknown", update_interval: float=0.1):

        # Variables for continuous handler to Socket IO
        self._handler_thread: Thread = None
        self._handler_running = Event()
        self._handler_terminated = Event()
        self._handler_terminated.set()
        self._handler_update_interval = update_interval
        self._last_publishing_time = time()
        
        self._node_name = node_name

        self._measurement_value_queue: List[np.ndarray] = []
        self._measurement_value_queue_lock = Lock()


    def __str__(self):
        return f"ValueHandler | {self._node_name}     "


    @abstractmethod
    def process(self):
        pass

    def handler(self):
        """This is the thread function registered with the handler.
        To publish messages to socketio, the child of BackendNode has to define @abstractmethod process().
        In it, it should handle if and what to publish using Backend().publish()

        """
        while not self._handler_terminated.is_set():
            if not self._handler_running.wait(timeout=1):
                CustomLogger.debug(f"{self}: Wait Timeout")
                continue

            
            self._last_publishing_time = time()
            while True:
                value = None
                with self._measurement_value_queue_lock:
                    if len(self._measurement_value_queue) == 0:
                        break

                    value = self._measurement_value_queue.pop(0)
            
                self.evaluateValue(value)

            dt = self._handler_update_interval - (time() - self._last_publishing_time)
            if (dt > 0):
                sleep(dt)

    def startHandler(self):
        """Start the SocketIO handler
        """
        CustomLogger.info(f"Starting {self}")
        self._handler_terminated.clear()
        if self._handler_thread is None or not self._handler_thread.is_alive():
            self._handler_thread = Thread(name=f"handler_{self}", target=self.handler)
            self._handler_thread.start()

    def stopHandler(self, wait_for_termination = True):
        """Terminate the SocketIO handler

        Args:
            wait_for_termination (bool, optional): Whether the function should wait for Thread termination or return directly. Defaults to True.
        """
        CustomLogger.info(f"Terminating {self}")
        if self._handler_thread is None or not self._handler_thread.is_alive():
            return 
        
        self._handler_terminated.set()
        if wait_for_termination:
            self._handler_thread.join()


    def playHandler(self):
        """Resume publishing to SocketIO
        """
        CustomLogger.info(f"Resuming {self}")
        if self._handler_terminated.is_set():
            CustomLogger.info(f"{self} is not active yet! Starting...")
            self.startHandler()
        self._handler_running.set()

    def pauseHandler(self):
        """Suspend publishing to SocketIO (this will not terminate the thread, but only stop it for the moment)
        """
        CustomLogger.info(f"Pausing {self}")
        self._handler_running.clear()


    @abstractmethod
    def evaluateValue(self, measurement_value: np.ndarray):
        """evaluate a set of hardware measurements

        Args:
            measurement_value (np.ndarray): Measurement values. Should be a numpy array np.array
        """
        pass

    def addValues(self, measurement_values: MeasurementValues):

        array = np.array([measurement_values.position, measurement_values.speed, measurement_values.time, measurement_values.force, measurement_values.power])
        with self._measurement_value_queue_lock:
            self._measurement_value_queue.append(array)

        