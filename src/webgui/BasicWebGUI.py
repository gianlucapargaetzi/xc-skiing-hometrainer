
from abc import abstractmethod, ABC
from typing import Tuple, List, Union

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

from threading import Event, Thread, Lock

from time import time, sleep

class BackendNode(ABC):
    def __init__(self, node_name = "Unknown", update_interval: float=None):

        # Variables for continuous Publisher to Socket IO
        self._publisher_thread: Thread = None
        self._publisher_running = Event()
        self._publisher_update_interval = update_interval
        
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

    def start(self):
        if self._publisher_update_interval is None: # No threading when _publisher_update_interval = None
            return

        if self._publisher_thread is not None and self._publisher_thread.is_alive(): # Nothing to do if already running
            return 
        
        self._publisher_thread = Thread(target=self.publisher)
        self._publisher_running.set()
        self._publisher_thread.start()

    def stop(self, wait_for_termination = True):
        if self._publisher_thread is None or not self._publisher_thread.is_alive(): # If already stopped, do not stop
            return
        
        self._publisher_running.clear()
        if wait_for_termination:
            self._publisher_thread.join()
        
        self._publisher_thread = None

    def publisher(self):
        """This is the thread function registered with the publisher.
        To publish messages to socketio, the child of BackendNode has to define @abstractmethod publish().
        In it, it should handle if and what to publish using Backend().publish()
        """
        while self._publisher_running.is_set():
            # Call the publishing logic from the child
            self.publish()
            sleep(self._publisher_update_interval)

            
class Backend(Flask):
    _instance = None  # Class variable to store the singleton instance

    def __new__(cls, importName="backend", *args, **kwargs):
        """This method ensures only one instance of Backend is created"""
        if not cls._instance:
            cls._instance = super(Backend, cls).__new__(cls)
        return cls._instance

    def __init__(self, importName="backend"):
        if not hasattr(self, '_initialized') or not self._initialized:
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

        # CustomLogger.info(f"Registered Node '{node}' at backend")
        for request in node.requests:
            self.add_url_rule(request[0], view_func=request[1],methods=request[2])

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
        print("Disconnected from frontend")
        # CustomLogger.error("DISCONNECTED")
