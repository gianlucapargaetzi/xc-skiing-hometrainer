
from abc import abstractmethod, ABC
from typing import Tuple, List, Union

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

from threading import Event, Thread

from time import sleep

class BackendNode(ABC):
    def __init__(self, node_name = "Unknown", update_interval: float=None):
        self._publisher_thread: Thread = None
        self._publisher_running = Event()
        self._publisher_update_interval = update_interval
        self._node_name = node_name
        self._socketio_subscribers: List[Tuple[str, callable]] = []
        self._flask_requests: List[Tuple[str, callable, List[str]]] = []

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
        if self._publisher_update_interval is None:
            return
        if self._publisher_thread and self._publisher_thread.is_alive():
            return
        self._publisher_thread = Thread(target=self.publisher)
        self._publisher_running.set()
        self._publisher_thread.start()

    def stop(self, wait_for_termination=True):
        if not self._publisher_thread or not self._publisher_thread.is_alive():
            return
        self._publisher_running.clear()
        if wait_for_termination:
            self._publisher_thread.join()
        self._publisher_thread = None

    def publisher(self):
        while self._publisher_running.is_set():
            self.publish()
            sleep(self._publisher_update_interval)


class Backend(Flask):
    _instance = None

    def __new__(cls, importName="backend", *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Backend, cls).__new__(cls)
        return cls._instance

    def __init__(self, importName="backend"):
        if not hasattr(self, '_initialized') or not self._initialized:
            super().__init__(importName)
            self.add_url_rule("/dashboard", view_func=self._index)
            self.add_url_rule("/simple", view_func=self._simple)
            self.add_url_rule("/interval", view_func=self._interval)
            self.add_url_rule("/sic", view_func=self._sic)
            self.add_url_rule("/iic", view_func=self._iic)
            self.add_url_rule("/config", view_func=self._config)

            self._socket = SocketIO(self, async_mode=None)

            def _run():
                self._socket.run(self)

            self._socket_thread = Thread(name="SocketIO", target=_run)

            self._socket.on_event('connect', self._callback_connect)
            self._socket.on_event('disconnect', self._callback_disconnect)

            self._registered_nodes: List[BackendNode] = []
            self._initialized = True

    @property
    def socket(self):
        return self._socket

    def registerNode(self, node: BackendNode):
        for request in node.requests:
            self.add_url_rule(request[0], view_func=request[1], methods=request[2])
        self._registered_nodes.append(node)

    def publish(self, topic: str, payload: dict):
        with self.app_context():
            self._socket.emit(topic, payload)

    def startBackend(self):
        if not self._socket_thread.is_alive():
            self._socket_thread.start()

    def _index(self):
        return render_template('dashboard.html', async_mode=self._socket.async_mode)

    def _interval(self):
        return render_template('interval.html', async_mode=self._socket.async_mode)

    def _sic(self):
        return render_template('multi_view_sic.html', async_mode=self._socket.async_mode)

    def _iic(self):
        return render_template('multi_view_iic.html', async_mode=self._socket.async_mode)

    def _simple(self):
        return render_template('simple.html', async_mode=self._socket.async_mode)

    def _config(self):
        return render_template('config.html', async_mode=self._socket.async_mode)


    def _callback_connect(self):
        print("Connection to frontend established")

    def _callback_disconnect(self):
        print("Disconnected from frontend")
