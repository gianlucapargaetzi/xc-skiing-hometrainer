import os
import yaml
import numpy as np

import matplotlib.pyplot as plt

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from Utils.TorqueCurve import createTorqueCurve
from Utils.State import ControllerState
from Utils.CustomLogger import Logger
from Utils.FileSystem import list_files
from BasicWebGUI import BackendNode, Backend
from IntensityController.IntensityControllerInterface import IntensityControllerInterface
import itertools

from flask import jsonify, request
from threading import Lock
from time import time

INTERVAL_PATH = "~/xc/intervals/"
INTERVAL_FILENAME_ENDING = ".xciv"

from typing import List

class IntervallParser():
    def __init__(self, filename):
        self._filename = filename
        self._data = None
        self._intensity_list: np.ndarray = None
        if not os.path.exists(self._filename):
            return

        with open(filename, 'r') as file:
            self._data = yaml.safe_load(file)

        self.evaluate()


    def evaluate(self):
        time = 0
        if self._data is None:
            return
        
        x_all = []
        y_all = []

        for (block_name, block_data), (next_block_name, next_block_data) in itertools.zip_longest(self._data.items(), itertools.islice(self._data.items(), 1, None), fillvalue=(None, None)) :
            
            if block_data['type'] == 'duration_block':
                duration = int(block_data['duration'])
                x = np.linspace(time, time+duration-1, duration)
                y = np.linspace(float(block_data['intensity_start']), 
                                float(block_data['intensity_end']), duration)
                
                x_all.append(x)
                y_all.append(y)
                time = time + duration
            
            if block_data['type'] == 'transition':
                # Check if next block is a sensible one.
                if next_block_data is None:
                    continue
                
                y0 = y_all[-1][-1]
                y1 = 0

                transition_type = block_data['curve']
                transition_duration = block_data['duration']

                if next_block_data['type'] == 'interval_block':
                    y1 = next_block_data['on_intensity']
                elif next_block_data['type'] == 'duration_block':
                    y1 = next_block_data['intensity_start']
                else:
                    continue

                if transition_type == 'None':
                    x = np.linspace(time, time+transition_duration-1, transition_duration)
                    y = np.linspace(y0,y1, transition_duration)           
                    time += transition_duration
                    x_all.append(x)
                    y_all.append(y)
                elif transition_type == 'ease':
                    x,y=createTorqueCurve(ease_in=0.49, ease_out=0.49, xkrit= 0.5, y0 =y0, y1=y1, len=transition_duration, relative=True )
                    x = x + time
                    x_all.append(x)
                    y_all.append(y)
                    time += transition_duration

            if block_data['type'] == 'interval_block':
                on_duration = int(block_data['on_duration'])
                off_duration = int(block_data['off_duration'])
                x_block = []
                y_block = []

                do_transition = False
                transition_type = 'None'
                transition_duration = 0

                if block_data['transition']:
                    do_transition = True
                    transition_type = block_data['transition']['type']
                    transition_duration = block_data['transition']['duration']

                for i in range(int(block_data['block_amount'])):
                    if i:
                        if do_transition:
                            if transition_type == 'None':
                                x = np.linspace(time, time+transition_duration-1, transition_duration)
                                y = np.linspace(int(block_data['off_intensity']),int(block_data['on_intensity']), transition_duration)           
                                time += transition_duration
                                x_block.append(x)
                                y_block.append(y)
                            elif transition_type == 'ease':
                                x,y=createTorqueCurve(ease_in=0.49, ease_out=0.49, xkrit= 0.5, y0 = int(block_data['off_intensity']), y1=int(block_data['on_intensity']), len=transition_duration, relative=True )
                                x = x + time
                                x_block.append(x)
                                y_block.append(y)
                                time += transition_duration
                        #handle transition
                        pass
                    x = np.linspace(time, time+on_duration-1, on_duration)
                    y = np.ones(on_duration) * int(block_data['on_intensity'])
                    x_block.append(x)
                    y_block.append(y)
                    time += on_duration

                    if do_transition:
                        if transition_type == 'None':
                            x = np.linspace(time, time+transition_duration-1, transition_duration)
                            y = np.linspace(int(block_data['on_intensity']),int(block_data['off_intensity']), transition_duration)           
                            time += transition_duration
                            x_block.append(x)
                            y_block.append(y)
                        elif transition_type == 'ease':
                            x,y =createTorqueCurve(ease_in=0.45, ease_out=0.45, xkrit= 0.5, y1 = int(block_data['off_intensity']), y0=int(block_data['on_intensity']), len=transition_duration, relative=True )
                            x = x + time
                            x_block.append(x)
                            y_block.append(y)
                            time += transition_duration
                    x = np.linspace(time, time+off_duration-1, off_duration)
                    y = np.ones(off_duration) * int(block_data['off_intensity'])
                    x_block.append(x)
                    y_block.append(y)
                    time += off_duration

                x_block = np.concatenate(x_block)
                y_block = np.concatenate(y_block)
                y_all.append(y_block)
                x_all.append(x_block)

                # plt.figure()        
                # plt.plot(x_block, y_block)
                # plt.show()

        self._intensity_list = np.concatenate(y_all)
        # x_all = np.concatenate(x_all)


        # plt.plot(x_all, y_all)
        # plt.xlim([0, x_all[-1]])
        # plt.ylim([0, 120])
        # plt.grid(True)
        # plt.show()

    def isValid(self) -> bool:
        return self._intensity_list is not None
    
    @property
    def intensityList(self) -> List[float]:
        return self._intensity_list.tolist()


    def get(self, idx) -> float:
        return self._intensity_list[idx]
    
class IntervallIntensityController(BackendNode, IntensityControllerInterface):
    def __init__(self):
        BackendNode.__init__(self, "IntervalIntensityControllerBackend", update_interval=1) # No publishing via socket IO...
        IntensityControllerInterface.__init__(self, "IntervallIntensityController")
        self._flask_requests.append(("/upload_interval_file", self._upload_file, ['POST']))
        self._flask_requests.append(("/load_interval_file", self._load_file, ['POST']))
        self._flask_requests.append(("/get_interval_list", self._get_list, ['GET']))
        self._controller_state: ControllerState = ControllerState.UNINITIALIZED
        self._start_time: float = None
        self._elapsed: float = 0.0
        self._interval: IntervallParser = None
        self._filepath: str = None
        Backend().registerNode(self)

    def __str__(self):
        return "IntervallIntensityController"

    def publish(self):
        return Backend().publish("interval_intensity", {"intensity": self.getIntensity(),"time": int(self._elapsed)})

    def _upload_file(self):
        def ret_json(success: bool, error: str = 'None') :
            return {'success': success, 'error': error}

        print("\nHellooo\n")


        if 'intervalFile' not in request.files:
            Logger().error(f"{self}: No Interval File in request")
            return jsonify(ret_json(False, "No interval file")), 400
        
        file = request.files['intervalFile']
        if file.filename == '':
            Logger().error(f"{self}: Empty Interval File in request")
            return jsonify(ret_json(False, "Interval filename empty")), 400
        
        if not file.filename.endswith(INTERVAL_FILENAME_ENDING):
            Logger().error(f"{self}: Wrong Filetype")
            return jsonify(ret_json(False, "Wrong Filetype")), 400
        
        try:
            path = os.path.expanduser(INTERVAL_PATH)
            filepath = os.path.join(path, file.filename)

            if os.path.exists(filepath):
                return jsonify(ret_json(False, "File already exists on server")), 400
            
            file.save(filepath)
        except Exception as e:
            Logger().error(f"{self}: {e}")
            return jsonify(ret_json(False, str(e))), 400

        return ret_json(True)

    def _get_list(self):
        def ret_json(success: bool, filelist: List[str] = [], error: str = 'None'):
            return {'success': success, 'files': filelist, 'error': error}

        try:
            return jsonify(ret_json(True, filelist=list_files(os.path.expanduser(INTERVAL_PATH), INTERVAL_FILENAME_ENDING)))
        except Exception as e:
            return jsonify(ret_json(False, [], str(e)))

        # return jsonify(ret_json(True,filelist=list_files(os.path.expanduser(INTERVAL_PATH), INTERVAL_FILENAME_ENDING)))

    def _load_file(self):
        # if os.path.exists(os.path.join(os.path.expanduser(INTERVAL_PATH), request.get_json))


        def ret_json(success: bool, data: dict = {'x':[], 'y':[]}, error: str = 'None'):
            return {'success': success, 'data': data, 'error': error}
        
        # print(request.get_json())
        data = request.get_json()
        if not data or 'fileName' not in data:
            Logger().error(f"{self}: Filename not provided")
            return jsonify(ret_json(False, error="Filename not provided")), 400        
        
        filepath = os.path.join(os.path.expanduser(INTERVAL_PATH), data['fileName'])
        if not os.path.exists(filepath):
            Logger().error(f"{self}: File does not exist")
            return jsonify(ret_json(False, error="File does not exist")), 400    
        
        self._filepath = filepath
        self._interval = IntervallParser(self._filepath)

        if not self._interval.isValid():
            Logger().error(f"{self}: Error occurd while parsing interval file")
            return jsonify(ret_json(False, error="Unknown parsing error")), 400    
        
        self._controller_state=ControllerState.INITIALIZED
        y = self._interval.intensityList
        x = np.linspace(0, len(y)-1, len(y)).tolist()
        # plt.plot(x,y)
        # plt.show()
        self.start()
        return jsonify(ret_json(True,data={'x':x, 'y':y}))

    def uninit(self):
        self._interval = None
        self._filepath = None
        self._elapsed = 0.0
        self._start_time = None
        self._controller_state = ControllerState.UNINITIALIZED

    def start(self):
        if self._controller_state == ControllerState.INITIALIZED:
            self._start_time = time()
        elif self._controller_state == ControllerState.PAUSED:
            self._start_time = time() - self._elapsed
        else:
            return
        
        Logger().info(f"{self}: Starting")
        self._controller_state = ControllerState.RUNNING
        BackendNode.start(self)
        
    def stop(self):
        if self._controller_state == ControllerState.RUNNING or self._controller_state == ControllerState.PAUSED:
            Logger().info(f"{self}: Stopping")
            self._start_time = None
            self._elapsed = 0.0
            self._controller_state = ControllerState.INITIALIZED

        BackendNode.stop(self)
        
    def pause(self):
        if self._controller_state == ControllerState.RUNNING:
            Logger().info(f"{self}: Pausing")
            self._elapsed = time() - self._start_time
            self._controller_state = ControllerState.PAUSED

        BackendNode.stop(self)

    def getIntensity(self) -> float:
        if self._controller_state == ControllerState.RUNNING:
            self._elapsed = time()-self._start_time
        elif self._controller_state == ControllerState.UNINITIALIZED:
            return 30
        elif self._controller_state == ControllerState.INITIALIZED:
            return self._interval.get(0)

        return self._interval.get(int(self._elapsed))
