import os
import yaml
import numpy as np
import sys
import itertools
from flask import jsonify, request
from time import time
from typing import Dict, List

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from Utils.TorqueCurve import createTorqueCurve
from Utils.State import ControllerState
from Utils.CustomLogger import Logger
from BasicWebGUI import BackendNode, Backend
from IntensityController.IntensityControllerInterface import IntensityControllerInterface


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
INTERVAL_PATH = os.path.join(BASE_DIR, "intervals")
INTERVAL_FILENAME_ENDING = ".xciv"


class IntervallParser:
    def __init__(self, filename):
        self._filename = filename
        self._data = None
        self._intensity_list: np.ndarray = None
        self._block_starts: List[Dict[str, object]] = []
        self._segments: List[Dict[str, object]] = []
        self._global_training_recommendation: str = ''

        if not os.path.exists(self._filename):
            raise FileNotFoundError(f"Interval file not found: {self._filename}")

        with open(filename, 'r', encoding='utf-8') as file:
            self._data = yaml.safe_load(file)

        if self._data is None:
            raise ValueError("Interval file is empty")

        if not isinstance(self._data, dict):
            raise ValueError("Interval file must contain a YAML mapping/object at top level")

        self._global_training_recommendation = str(self._data.get('global_training_recommendation', '') or '')

        self.evaluate()

    def _iter_interval_items(self):
        for block_name, block_data in self._data.items():
            if block_name == 'global_training_recommendation':
                continue

            if not isinstance(block_data, dict):
                raise ValueError(f"Block '{block_name}' is not a mapping/object")

            block_type = block_data.get('type')
            if block_type is None:
                raise ValueError(f"Block '{block_name}' has no 'type' field")

            yield block_name, block_data

    @staticmethod
    def _training_recommendation(block_data: dict) -> str:
        return str(block_data.get('training_recommendation', '') or '')

    def _append_segment(self, name: str, block_type: str, start: int, end: int, training_recommendation: str):
        self._segments.append({
            'name': str(name),
            'type': str(block_type),
            'start': int(start),
            'end': int(end),
            'training_recommendation': str(training_recommendation or ''),
        })

    def evaluate(self):
        current_time = 0
        x_all = []
        y_all = []
        self._block_starts = []
        self._segments = []
        interval_items = list(self._iter_interval_items())

        for (block_name, block_data), (next_block_name, next_block_data) in itertools.zip_longest(
            interval_items,
            itertools.islice(interval_items, 1, None),
            fillvalue=(None, None)
        ):
            block_type = block_data.get('type')
            training_recommendation = self._training_recommendation(block_data)

            if block_type == 'duration_block':
                block_start = current_time
                duration = int(block_data['duration'])
                x = np.linspace(current_time, current_time + duration - 1, duration)
                y = np.linspace(
                    float(block_data['intensity_start']),
                    float(block_data['intensity_end']),
                    duration
                )
                x_all.append(x)
                y_all.append(y)
                current_time += duration
                self._block_starts.append({
                    'name': str(block_name),
                    'type': block_type,
                    'start': int(block_start),
                    'end': int(current_time - 1),
                    'training_recommendation': training_recommendation,
                })
                self._append_segment(block_name, block_type, block_start, current_time - 1, training_recommendation)

            elif block_type == 'transition':
                if next_block_data is None or len(y_all) == 0:
                    continue

                if not isinstance(next_block_data, dict):
                    continue

                y0 = y_all[-1][-1]
                y1 = 0

                transition_type = block_data.get('curve', 'None')
                transition_duration = int(block_data['duration'])

                next_type = next_block_data.get('type')
                if next_type == 'interval_block':
                    y1 = float(next_block_data['on_intensity'])
                elif next_type == 'duration_block':
                    y1 = float(next_block_data['intensity_start'])
                else:
                    continue

                if transition_type == 'None':
                    x = np.linspace(current_time, current_time + transition_duration - 1, transition_duration)
                    y = np.linspace(y0, y1, transition_duration)
                elif transition_type == 'ease':
                    x, y = createTorqueCurve(
                        ease_in=0.49,
                        ease_out=0.49,
                        xkrit=0.5,
                        y0=y0,
                        y1=y1,
                        len=transition_duration,
                        relative=True
                    )
                    x = x + current_time
                else:
                    x = np.linspace(current_time, current_time + transition_duration - 1, transition_duration)
                    y = np.linspace(y0, y1, transition_duration)

                transition_start = current_time
                x_all.append(x)
                y_all.append(y)
                current_time += transition_duration
                self._append_segment(block_name, block_type, transition_start, current_time - 1, training_recommendation)

            elif block_type == 'interval_block':
                block_start = current_time
                on_duration = int(block_data['on_duration'])
                off_duration = int(block_data['off_duration'])
                block_amount = int(block_data['block_amount'])
                on_intensity = float(block_data['on_intensity'])
                off_intensity = float(block_data['off_intensity'])

                if block_amount <= 0:
                    raise ValueError(f"Block '{block_name}' has invalid block_amount={block_amount}")

                x_block = []
                y_block = []

                do_transition = False
                transition_type = 'None'
                transition_duration = 0

                if block_data.get('transition'):
                    do_transition = True
                    transition_type = block_data['transition'].get('type', 'None')
                    transition_duration = int(block_data['transition']['duration'])

                for i in range(block_amount):
                    if i > 0 and do_transition:
                        if transition_type == 'None':
                            x = np.linspace(current_time, current_time + transition_duration - 1, transition_duration)
                            y = np.linspace(off_intensity, on_intensity, transition_duration)
                        elif transition_type == 'ease':
                            x, y = createTorqueCurve(
                                ease_in=0.49,
                                ease_out=0.49,
                                xkrit=0.5,
                                y0=off_intensity,
                                y1=on_intensity,
                                len=transition_duration,
                                relative=True
                            )
                            x = x + current_time
                        else:
                            x = np.linspace(current_time, current_time + transition_duration - 1, transition_duration)
                            y = np.linspace(off_intensity, on_intensity, transition_duration)

                        x_block.append(x)
                        y_block.append(y)
                        current_time += transition_duration

                    x = np.linspace(current_time, current_time + on_duration - 1, on_duration)
                    y = np.ones(on_duration) * on_intensity
                    x_block.append(x)
                    y_block.append(y)
                    current_time += on_duration

                    if do_transition:
                        if transition_type == 'None':
                            x = np.linspace(current_time, current_time + transition_duration - 1, transition_duration)
                            y = np.linspace(on_intensity, off_intensity, transition_duration)
                        elif transition_type == 'ease':
                            x, y = createTorqueCurve(
                                ease_in=0.45,
                                ease_out=0.45,
                                xkrit=0.5,
                                y0=on_intensity,
                                y1=off_intensity,
                                len=transition_duration,
                                relative=True
                            )
                            x = x + current_time
                        else:
                            x = np.linspace(current_time, current_time + transition_duration - 1, transition_duration)
                            y = np.linspace(on_intensity, off_intensity, transition_duration)

                        x_block.append(x)
                        y_block.append(y)
                        current_time += transition_duration

                    x = np.linspace(current_time, current_time + off_duration - 1, off_duration)
                    y = np.ones(off_duration) * off_intensity
                    x_block.append(x)
                    y_block.append(y)
                    current_time += off_duration

                x_block = np.concatenate(x_block)
                y_block = np.concatenate(y_block)
                x_all.append(x_block)
                y_all.append(y_block)
                self._block_starts.append({
                    'name': str(block_name),
                    'type': block_type,
                    'start': int(block_start),
                    'end': int(current_time - 1),
                    'training_recommendation': training_recommendation,
                })
                self._append_segment(block_name, block_type, block_start, current_time - 1, training_recommendation)

            else:
                raise ValueError(f"Unknown block type '{block_type}' in block '{block_name}'")

        if len(y_all) == 0:
            raise ValueError("No intensity data could be created from interval file")

        self._intensity_list = np.concatenate(y_all)

        if len(self._block_starts) == 0:
            self._block_starts.append({
                'name': 'Block 1',
                'type': 'generated',
                'start': 0,
                'end': int(len(self._intensity_list) - 1),
                'training_recommendation': '',
            })
            self._append_segment('Block 1', 'generated', 0, len(self._intensity_list) - 1, '')

    def isValid(self) -> bool:
        return self._intensity_list is not None

    @property
    def intensityList(self) -> List[float]:
        if self._intensity_list is None:
            return []
        return self._intensity_list.tolist()

    @property
    def blockStarts(self) -> List[Dict[str, object]]:
        return [dict(block) for block in self._block_starts]

    @property
    def globalTrainingRecommendation(self) -> str:
        return self._global_training_recommendation

    def blockCount(self) -> int:
        return len(self._block_starts)

    def getBlockStart(self, block_index: int) -> int:
        if len(self._block_starts) == 0:
            return 0

        block_index = max(0, min(int(block_index), len(self._block_starts) - 1))
        return int(self._block_starts[block_index]['start'])

    def getBlockIndexForTime(self, idx: int) -> int:
        if len(self._block_starts) == 0:
            return 0

        idx = max(0, min(int(idx), max(0, self.length() - 1)))
        current_block_index = 0

        for block_index, block in enumerate(self._block_starts):
            if idx >= int(block['start']):
                current_block_index = block_index
            else:
                break

        return current_block_index

    def getBlockName(self, block_index: int) -> str:
        if len(self._block_starts) == 0:
            return ''

        block_index = max(0, min(int(block_index), len(self._block_starts) - 1))
        return str(self._block_starts[block_index].get('name', ''))

    def getTrainingRecommendationForTime(self, idx: int) -> str:
        if len(self._segments) == 0:
            return ''

        idx = max(0, min(int(idx), max(0, self.length() - 1)))
        current_recommendation = ''

        for segment in self._segments:
            if idx >= int(segment['start']):
                current_recommendation = str(segment.get('training_recommendation', '') or '')
            else:
                break

        return current_recommendation

    def get(self, idx) -> float:
        if self._intensity_list is None or len(self._intensity_list) == 0:
            return 0

        if idx < 0:
            idx = 0
        elif idx >= len(self._intensity_list):
            idx = len(self._intensity_list) - 1

        return float(self._intensity_list[idx])

    def length(self) -> int:
        if self._intensity_list is None:
            return 0
        return len(self._intensity_list)


class IntervallIntensityController(BackendNode, IntensityControllerInterface):
    def __init__(self):
        BackendNode.__init__(self, "IntervalIntensityControllerBackend", update_interval=1)
        IntensityControllerInterface.__init__(self, "IntervallIntensityController")

        self.active = False
        self.stop_requested = False

        self._flask_requests.append(("/upload_interval_file", self._upload_file, ['POST']))
        self._flask_requests.append(("/load_interval_file", self._load_file, ['POST']))
        self._flask_requests.append(("/get_interval_list", self._get_list, ['GET']))
        self._flask_requests.append(("/start_interval", self._start, ['POST']))
        self._flask_requests.append(("/jump_interval_block", self._jump_interval_block, ['POST']))
        self._flask_requests.append(("/stop", self._stop, ['POST']))

        self._controller_state: ControllerState = ControllerState.UNINITIALIZED
        self._start_time: float = None
        self._elapsed: float = 0.0
        self._interval: IntervallParser = None
        self._filepath: str = None

        os.makedirs(INTERVAL_PATH, exist_ok=True)
        Logger().info(f"{self}: Interval directory = {INTERVAL_PATH}")

        Backend().registerNode(self)

    def __str__(self):
        return "IntervallIntensityController"

    def _resolve_interval_filepath(self, requested_name: str) -> str:
        if not requested_name:
            raise ValueError("Filename empty")

        requested_name = requested_name.strip()

        # Falls die Liste bereits einen Pfad liefert: nur Dateiname verwenden
        filename = os.path.basename(requested_name)

        if not filename.endswith(INTERVAL_FILENAME_ENDING):
            raise ValueError("Wrong file type")

        return os.path.join(INTERVAL_PATH, filename)

    def publish(self):
        return Backend().publish("interval_intensity", self._controller_payload())

    def _current_elapsed(self) -> float:
        if (
            self.active
            and self._controller_state == ControllerState.RUNNING
            and self._start_time is not None
        ):
            self._elapsed = time() - self._start_time

        return self._elapsed

    def _set_elapsed(self, elapsed: float):
        if self._interval is None or not self._interval.isValid():
            self._elapsed = 0.0
            self._start_time = None
            return

        max_elapsed = max(0, self._interval.length() - 1)
        self._elapsed = float(max(0, min(int(elapsed), max_elapsed)))

        if (
            self.active
            and self._controller_state == ControllerState.RUNNING
        ):
            self._start_time = time() - self._elapsed

    def _block_navigation_state(self) -> dict:
        block_count = 0
        block_index = 0
        block_name = ''
        global_training_recommendation = ''
        training_recommendation = ''

        if self._interval is not None and self._interval.isValid():
            current_elapsed = int(self._current_elapsed())
            block_count = self._interval.blockCount()
            block_index = self._interval.getBlockIndexForTime(current_elapsed)
            block_name = self._interval.getBlockName(block_index)
            global_training_recommendation = self._interval.globalTrainingRecommendation
            training_recommendation = self._interval.getTrainingRecommendationForTime(current_elapsed)

        return {
            "block_index": block_index,
            "block_number": block_index + 1 if block_count > 0 else 0,
            "block_count": block_count,
            "block_name": block_name,
            "global_training_recommendation": global_training_recommendation,
            "training_recommendation": training_recommendation,
            "can_jump_previous": block_count > 0 and block_index > 0,
            "can_jump_next": block_count > 0 and block_index < block_count - 1,
            "can_jump_last": block_count > 0 and block_index < block_count - 1,
        }

    def _controller_payload(self) -> dict:
        intensity = self.getIntensity()
        payload = {
            "intensity": intensity,
            "time": int(self._elapsed),
            "state": str(self._controller_state),
        }
        payload.update(self._block_navigation_state())
        return payload

    def _start(self):
        def ret_json(success: bool, error: str = 'None'):
            return {'success': success, 'error': error}

        if self._interval is None or not self._interval.isValid():
            Logger().error(f"{self}: No interval loaded")
            return jsonify(ret_json(False, "No interval loaded")), 400

        self.stop_requested = False
        self.restart()
        response = ret_json(True)
        response.update(self._controller_payload())
        return jsonify(response)

    def _jump_interval_block(self):
        def ret_json(success: bool, error: str = 'None'):
            payload = {'success': success, 'error': error}
            if success:
                payload.update(self._controller_payload())
            return payload

        if self._interval is None or not self._interval.isValid():
            Logger().error(f"{self}: Cannot jump, no interval loaded")
            return jsonify(ret_json(False, "No interval loaded")), 400

        data = request.get_json(silent=True) or {}
        direction = str(data.get('direction', '')).lower()

        block_count = self._interval.blockCount()
        if block_count <= 0:
            return jsonify(ret_json(False, "No interval blocks available")), 400

        current_block_index = self._interval.getBlockIndexForTime(int(self._current_elapsed()))

        if direction in ('next', '+1', 'forward'):
            target_block_index = min(current_block_index + 1, block_count - 1)
        elif direction in ('previous', 'prev', '-1', 'back'):
            target_block_index = max(current_block_index - 1, 0)
        elif direction in ('last', 'end'):
            target_block_index = block_count - 1
        else:
            return jsonify(ret_json(False, "Invalid jump direction")), 400

        target_elapsed = self._interval.getBlockStart(target_block_index)
        self._set_elapsed(target_elapsed)

        Logger().info(
            f"{self}: Jumped to block {target_block_index + 1}/{block_count} "
            f"at t={int(self._elapsed)}s"
        )

        try:
            self.publish()
        except Exception as e:
            Logger().error(f"{self}: Error while publishing jump state: {e}")

        return jsonify(ret_json(True))

    def _stop(self):
        Logger().info(f"{self}: Stop command received via Webinterface")
        self.stop_requested = True
        self.stop()
        payload = {"status": "stopped", "success": True}
        payload.update(self._controller_payload())
        return jsonify(payload)

    def _upload_file(self):
        def ret_json(success: bool, error: str = 'None'):
            return {'success': success, 'error': error}

        if 'intervalFile' not in request.files:
            Logger().error(f"{self}: No Interval File in request")
            return jsonify(ret_json(False, "No interval file")), 400

        file = request.files['intervalFile']

        if file.filename == '':
            Logger().error(f"{self}: Empty Interval File in request")
            return jsonify(ret_json(False, "Interval filename empty")), 400

        filename = os.path.basename(file.filename)

        if not filename.endswith(INTERVAL_FILENAME_ENDING):
            Logger().error(f"{self}: Wrong Filetype")
            return jsonify(ret_json(False, "Wrong Filetype")), 400

        try:
            os.makedirs(INTERVAL_PATH, exist_ok=True)
            filepath = os.path.join(INTERVAL_PATH, filename)

            if os.path.exists(filepath):
                return jsonify(ret_json(False, "File already exists on server")), 400

            file.save(filepath)
            Logger().info(f"{self}: Uploaded interval file to {filepath}")
        except Exception as e:
            Logger().error(f"{self}: {e}")
            return jsonify(ret_json(False, str(e))), 400

        return jsonify(ret_json(True))

    def _get_list(self):
        def ret_json(success: bool, filelist: List[str] = None, error: str = 'None'):
            return {'success': success, 'files': filelist or [], 'error': error}

        try:
            os.makedirs(INTERVAL_PATH, exist_ok=True)

            files = sorted([
                f for f in os.listdir(INTERVAL_PATH)
                if os.path.isfile(os.path.join(INTERVAL_PATH, f)) and f.endswith(INTERVAL_FILENAME_ENDING)
            ])

            Logger().info(f"{self}: Interval files found = {files}")
            return jsonify(ret_json(True, filelist=files))
        except Exception as e:
            Logger().error(f"{self}: {e}")
            return jsonify(ret_json(False, [], str(e))), 500

    def _load_file(self):
        def ret_json(success: bool, data: dict = None, error: str = 'None'):
            return {'success': success, 'data': data or {'x': [], 'y': []}, 'error': error}

        try:
            data = request.get_json()
            if not data or 'fileName' not in data:
                Logger().error(f"{self}: Filename not provided")
                return jsonify(ret_json(False, error="Filename not provided")), 400

            requested_name = data['fileName']
            filepath = self._resolve_interval_filepath(requested_name)

            Logger().info(f"{self}: Requested file = {requested_name}")
            Logger().info(f"{self}: Resolved filepath = {filepath}")

            if not os.path.exists(filepath):
                Logger().error(f"{self}: File does not exist: {filepath}")
                return jsonify(ret_json(False, error=f"File does not exist: {filepath}")), 400

            self.stop()

            self._filepath = filepath
            self._interval = IntervallParser(self._filepath)

            if not self._interval.isValid():
                Logger().error(f"{self}: Interval parser returned invalid state")
                return jsonify(ret_json(False, error="Parser returned invalid state")), 400

            self._controller_state = ControllerState.INITIALIZED
            self._elapsed = 0.0
            self._start_time = None
            self.active = False
            self.stop_requested = False

            y = self._interval.intensityList
            x = np.linspace(0, len(y) - 1, len(y)).tolist() if len(y) > 0 else []

            interval_data = {
                'x': x,
                'y': y,
                'blocks': self._interval.blockStarts,
                'block_count': self._interval.blockCount(),
                'global_training_recommendation': self._interval.globalTrainingRecommendation,
            }

            Logger().info(f"{self}: Loaded interval file {requested_name}")
            return jsonify(ret_json(True, data=interval_data))

        except Exception as e:
            Logger().error(f"{self}: Error while loading file: {e}")
            return jsonify(ret_json(False, error=str(e))), 400

    def uninit(self):
        self._interval = None
        self._filepath = None
        self._elapsed = 0.0
        self._start_time = None
        self.active = False
        self.stop_requested = False
        self._controller_state = ControllerState.UNINITIALIZED
        BackendNode.stop(self)

    def start(self):
        if self._interval is None or not self._interval.isValid():
            Logger().error(f"{self}: Cannot start, no valid interval loaded")
            return

        self.active = True
        self._elapsed = 0.0
        self._start_time = time()
        self._controller_state = ControllerState.RUNNING

        Logger().info(f"{self}: Starting interval from beginning")
        BackendNode.start(self)

    def restart(self):
        Logger().info(f"{self}: Restarting interval")
        BackendNode.stop(self)
        self.start()

    def stop(self):
        Logger().info(f"{self}: Stopping")
        self.active = False
        self._start_time = None
        self._elapsed = 0.0

        if self._interval is not None and self._interval.isValid():
            self._controller_state = ControllerState.INITIALIZED
        else:
            self._controller_state = ControllerState.UNINITIALIZED

        BackendNode.stop(self)

    def pause(self):
        if self._controller_state == ControllerState.RUNNING:
            Logger().info(f"{self}: Pausing")
            self._elapsed = time() - self._start_time
            self._controller_state = ControllerState.PAUSED

        BackendNode.stop(self)

    def getIntensity(self) -> float:
        if self._interval is None or not self._interval.isValid():
            return 0

        if not self.active:
            return 0

        if self._controller_state == ControllerState.UNINITIALIZED:
            return 0

        if self._controller_state == ControllerState.INITIALIZED:
            return 0

        if self._controller_state == ControllerState.PAUSED:
            return self._interval.get(int(self._elapsed))

        if self._controller_state == ControllerState.RUNNING:
            self._elapsed = time() - self._start_time

            if self._elapsed >= self._interval.length():
                Logger().info(f"{self}: Interval finished")
                BackendNode.stop(self)
                self.active = False
                self._start_time = None
                self._elapsed = 0.0
                self._controller_state = ControllerState.INITIALIZED
                return 0

            return self._interval.get(int(self._elapsed))

        return 0