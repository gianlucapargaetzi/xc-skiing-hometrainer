from threading import Lock
from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit
import requests
from time import sleep
from HeartRateMonitor import HeartRateMonitor
from threading import Thread

from multiprocessing import Process, Queue
import time

import heart_rate_sensor

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
socketio = SocketIO(app, async_mode=async_mode)
hrm = HeartRateMonitor(socket=socketio)

# def thread():
#     hr = 0
#     while True:
#         hrm.set_value(hr)
#         sleep(20)
#         hr+=2

# t = None
# lock = Lock()


@app.route('/')
def index():
    return render_template('index.html', async_mode=socketio.async_mode)

@socketio.event
def connect(msg):
    # global t
    # with lock:
    #     if t is None:
    #         t = Thread(target=thread)
    #         t.start()
    hrm.start()


def receiver(queue):
    while True:
        data = queue.get()
        print(f"Script B received: {data}")


if __name__ == '__main__':
    heart_rate_sensor.set_hrm(hrm)
    bluetooth_thread = Thread(target=heart_rate_sensor.main)
    bluetooth_thread.start()
    q = Queue()
    p = Process(target=receiver, args=(q,))
    p.start()

    socketio.run(app)
