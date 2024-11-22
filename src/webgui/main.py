from BasicWebGUI import Backend
from IntensityController.IntervallIntensityController import IntervallIntensityController
from ValueHandler.Scope import Scope
from Utils.CustomLogger import Logger
from time import sleep
from threading import Thread
from flask import jsonify, request
from datetime import datetime


import numpy as np
if __name__ == '__main__':
    data = np.genfromtxt(
        'Training.txt',          # Replace 'data.txt' with the path to your file
        delimiter=';',       # Delimiter used in the file
        dtype=None,          # Automatically infer data types for each column
        names=True,          # Use the first row as column names
        encoding='utf-8'     # Set encoding to read text data correctly
    )

    timestamps = data['TIMESTAMP']
    position = np.array(data['POSITION'], dtype=float)
    speed = np.array(data['SPEED'], dtype=float)
    load = np.array(data['LOAD'],dtype=float)
    power = np.array(data['POWER'])
    torque_ref = np.array(data['TORQUEREF'])


    scope = Scope()
    min = np.min(position)
    max = np.max(position)

    dp = max-min
    relative_position = (position - np.ones(np.shape(position)) * min) / dp * 100

    dt = []

    for j in range (len(timestamps.tolist())-1):
        t0 = str(timestamps[j])
        t1 = str(timestamps[j+1])
        dt0 = datetime.strptime(t0, '%Y-%m-%d %H:%M:%S.%f')
        dt1 = datetime.strptime(t1, '%Y-%m-%d %H:%M:%S.%f')
        # Convert to seconds since epoch
        dt.append(dt1.timestamp() - dt0.timestamp())

    values = [relative_position, speed, load, power, torque_ref]
    values = np.stack(values)


    t = None
    def run():
        scope.evaluateValue(values[:,0])
        for j in range(len(dt)):
            sleep(dt[j])
            scope.evaluateValue(values[:,j+1])

    def start():
        data = request.json
        if data.get('start', False):
            print("Simulation started")
            t = Thread(target=run)
            t.start()
            return jsonify({"message": "Simulation started"}), 200
        return jsonify({"error": "Invalid request"}), 400


    app = Backend(__name__)
    app.add_url_rule("/start_simulation", view_func=start, methods=["POST"])
    # tb = SimpleIntensityController()
    tb = IntervallIntensityController()
    tb.init('intervall.yaml')

    app.startBackend()
    while True:
        sleep(10)
        # tb.start()
        # sleep(10)
        # tb.pause()
        # sleep(5)
        # tb.start()
        # sleep(10)
        # tb.stop()
        # sleep(5)
        # tb.start()
        # Logger().warning("Warn MSG")
        # sleep(2)
        # Logger().error("Error MSG")
        # sleep(2)
        # Logger().info("Info MSG")
        # sleep(2)
        # Logger().critical("Critical MSG")