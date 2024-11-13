
from abc import abstractmethod, ABC
from typing import Tuple, List, Union

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
from Utils.CustomLogger import CustomLogger

from threading import Event, Thread

from time import time, sleep

class BackendNode(ABC):
    def __init__(self, node_name = "Unknown", update_interval: float=1.0):

        # Variables for continuous Publisher to Socket IO
        self._publisher_thread: Thread = None
        self._publisher_running = Event()
        self._publisher_terminated = Event()
        self._publisher_terminated.set()
        self._publisher_update_interval = update_interval
        self._last_publishing_time = time()
        
        self._node_name = node_name


        self._socketio_subscribers: List[Tuple[str, function]] = []
        self._flask_requests: List[Tuple[str, function, List[str]]] =  []   


    def __str__(self):
        return f"BackendNode | {self._node_name}     "
    
    @property
    def subscribers(self):
        return self._socketio_subscribers
    
    @property
    def requests(self):
        return self._flask_requests

    @abstractmethod
    def publish(self):
        pass

    def publisher(self):
        """This is the thread function registered with the publisher.
        To publish messages to socketio, the child of BackendNode has to define @abstractmethod publish().
        In it, it should handle if and what to publish using Backend().publish()

        """
        while not self._publisher_terminated.is_set():
            if not self._publisher_running.wait(timeout=1):
                CustomLogger.debug(f"{self}: Wait Timeout")
                continue
            self._last_publishing_time = time()

            # Call the publishing logic from the child
            self.publish()

            dt = self._publisher_update_interval - (time() - self._last_publishing_time)
            if (dt > 0):
                sleep(dt)

    def startPublishing(self):
        """Start the SocketIO Publisher
        """
        CustomLogger.info(f"Starting {self}")
        self._publisher_terminated.clear()
        if self._publisher_thread is None or not self._publisher_thread.is_alive():
            self._publisher_thread = Thread(name=f"Publisher_{self}", target=self.publisher)
            self._publisher_thread.start()

    def stopPublishing(self, wait_for_termination = True):
        """Terminate the SocketIO Publisher

        Args:
            wait_for_termination (bool, optional): Whether the function should wait for Thread termination or return directly. Defaults to True.
        """
        CustomLogger.info(f"Terminating {self}")
        if self._publisher_thread is None or not self._publisher_thread.is_alive():
            return 
        
        self._publisher_terminated.set()
        if wait_for_termination:
            self._publisher_thread.join()


    def playPublishing(self):
        """Resume publishing to SocketIO
        """
        CustomLogger.info(f"Resuming {self}")
        if self._publisher_terminated.is_set():
            CustomLogger.info(f"{self} is not active yet! Starting...")
            self.startPublishing()
        self._publisher_running.set()

    def pausePublishing(self):
        """Suspend publishing to SocketIO (this will not terminate the thread, but only stop it for the moment)
        """
        CustomLogger.info(f"Pausing {self}")
        self._publisher_running.clear()



class TestBackend(BackendNode):
    def __init__(self, update_interval=1.0):
        super().__init__("TestBackend", update_interval=update_interval)
        Backend().registerNode(self)
        self.cnt = 0

    def publish(self):
        print("Publishing", self.cnt)
        Backend().publish("test", {"value": self.cnt})
        self.cnt +=1

            
class Backend(Flask):
    _instance = None  # Class variable to store the singleton instance

    def __new__(cls, importName="backend", *args, **kwargs):
        """This method ensures only one instance of Backend is created"""
        if not cls._instance:
            cls._instance = super(Backend, cls).__new__(cls)
        return cls._instance

    def __init__(self, importName="backend"):
        if not hasattr(self, '_initialized'):
            # Initialize Flask with the import name only once
            super().__init__(importName)
            self.add_url_rule("/", view_func=self._index)

            self._socket = SocketIO(self, async_mode=None)
            def _run():
                self._socket.run(self)

            self._socket_thread = Thread(name="SocketIO", target=_run)

            self._socket.on_event('connect', self._callback_connect)
            self._socket.on_event('disconnect', self._callback_disconnect)

            self._registered_nodes: List[BackendNode] = []
            self._initialized = True  # Set initialized flag to avoid re-initialization


########################################################################################
# PUBLIC
########################################################################################
    def registerNode(self, node: BackendNode):

        CustomLogger.info(f"Registered Node '{node}' at backend")
        # self._socket.start_background_task(node.publisher)
        # t = Thread(target=node.publisher)
        # node.publisherThread = t
        self._registered_nodes.append(node)
            

    def publish(self, topic: str, payload: dict):
        with self.app_context():
            self._socket.emit(topic, payload) 


    def startBackend(self):
        if not self._socket_thread.is_alive():
            self._socket_thread.start()
########################################################################################
# PRIVATE
########################################################################################

    def _index(self):
        return render_template('index.html', async_mode=self._socket.async_mode)
    
    def _callback_connect(self):
        print("Connection to frontend established")

    def _callback_disconnect(self):
        CustomLogger.error("DISCONNECTED")



if __name__ == '__main__':
    app = Backend(__name__)
    tb = TestBackend()

    app.startBackend()
    sleep(3)
    tb.playPublishing()
    sleep(5)
    tb.pausePublishing()
    sleep(5)
    tb.playPublishing()
    sleep(5)
    tb.stopPublishing()
    sleep(2)
    tb.startPublishing()
    sleep(3)
    tb.stopPublishing()
