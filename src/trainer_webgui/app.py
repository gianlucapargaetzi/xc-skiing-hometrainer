
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import os
import random
import gpxpy
import geopy.distance

import logging

import numpy as np

from threading import Thread, Lock

import time


class Map():
    def __init__(self, filepath):
        self._valid = False
        self._filepath = filepath
        self._coordinates = []
        self._distances: np.ndarray = None
        self._current_position = None
        self._total_length = 0.0

        if not os.path.exists(self._filepath):
            logging.error(f".GPX File '{self._filepath}' does not exist")
            return
        
        self._valid = self._open()

    #     if self._valid:
    #         t = Thread(target=self.updating_thread)
    #         t.start()
    
    # def updating_thread(self):
    #     while True:
    #         distance = self._current_position["distance"]
    #         distance += 0.05

    #         self._current_position = self.coordinate_from_distance(distance)
    #         print(self._current_position)
    #         time.sleep(1)


    def _open(self) -> bool:
        # Parse the GPX file and extract coordinates and elevation
        with open(self._filepath, 'r') as gpx_file:
            gpx = gpxpy.parse(gpx_file)
            coordinates = []   
            if len(gpx.tracks) == 0:
                logging.error("No tracks found!")
                return False
            
            if len(gpx.tracks) > 1:
                logging.warning("More than one track found! Discarding tracks other than first one!")   

            track = gpx.tracks[0]

            if len(track.segments) == 0:
                logging.error("No segments found!")
                return False
            
            accumulated_distance = 0.0
            last_coordinates = (0.0, 0.0)
            first_element=True

            distance=[]

            for segment in track.segments:
                for point in segment.points:  
                    if first_element:
                        first_element=False
                        last_coordinates = (point.latitude, point.longitude)
                    else:
                        new_coordinates = (point.latitude, point.longitude)
                        accumulated_distance += geopy.distance.geodesic(last_coordinates,new_coordinates).km
                        last_coordinates = new_coordinates    
                        
                    coordinates.append({
                        'lat': point.latitude,
                        'lon': point.longitude,
                        'elevation': point.elevation,  # Extract elevation if available
                        'distance' : accumulated_distance
                    })

                    distance.append(accumulated_distance)


            self._coordinates = coordinates
            self._distances = np.array(distance)
            self._total_length = self._coordinates[-1]["distance"]
            self._current_position = self._coordinates[100]
            print(self._current_position)
            return True
    
    @property
    def filepath(self):
        return self._filepath    

    @property
    def coordinates(self):
        return self._coordinates
    
    @property
    def current_position(self):
        return self._current_position

    @property
    def valid(self):
        return self._valid
    
    def coordinate_from_distance(self, distance)->dict:
        """Calculate the GPS coordinates for a distance

        Args:
            distance (float): Distance for which the GPS-Coordinates should be calculated

        Returns:
            dict: Dicitionary with Point Data
        """
        index = np.where(self._distances <= distance)[0][-1]
        if index < len(self._coordinates)-1:
            offset = distance - self._coordinates[index]["distance"]
            deltaSegment = self._coordinates[index+1]["distance"] - self._coordinates[index]["distance"]
            
            fraction = 0.0
            if (deltaSegment > 0.0):
                fraction=offset/deltaSegment
            
            lat = self._coordinates[index]["lat"] + fraction * (self._coordinates[index+1]["lat"]- self._coordinates[index]["lat"])
            lon = self._coordinates[index]["lon"] + fraction * (self._coordinates[index+1]["lon"]- self._coordinates[index]["lon"])

            elevation = self._coordinates[index]["elevation"] + fraction * (self._coordinates[index+1]["elevation"]- self._coordinates[index]["elevation"])
            return  {
                        'lat': lat,
                        'lon': lon,
                        'elevation': elevation,  # Extract elevation if available
                        'distance' : distance
                    }
        else:
            return self._coordinates[-1]

class WebGUIBackend(Flask):
    def __init__(self, importName):
        super().__init__(importName)
        self.config['UPLOAD_FOLDER'] = 'uploads/'  # Folder to save uploaded files
        self.config['ALLOWED_EXTENSIONS'] = {'gpx'}  # Restrict file type to GPX
        self.config['gps_loaded'] = False
        # Create upload directory if not exists
        os.makedirs(self.config['UPLOAD_FOLDER'], exist_ok=True)
        self.add_routes()
        self._map: Map = None

        self._site_locked_lock = Lock()
        self._site_locked = False
        self.before_request(self._limit_access)

        self.secret_key="Testkey123"


    def add_routes(self):
        self.add_url_rule("/", view_func=self._index)
        self.add_url_rule("/settings", view_func=self._settings)
        self.add_url_rule("/set-gpx", view_func=self._set_gpx, methods=['POST'])
        self.add_url_rule("/update-checkbox", view_func=self._set_control_mode, methods=['POST'])
        self.add_url_rule("/current-position", view_func=self._get_position)
        self.add_url_rule("/release-session", view_func=self._release_session, methods=['POST'])

        
    def _limit_access(self):
        print("Lock session")


    def _release_session(self):
        print("Release session")
        # This route can be used to release the lock when the user logs out or leaves
        # with self._site_locked_lock:
        #     self._site_locked = False
        #     session.pop('active_session', None)
        return redirect(url_for('_index'))

    def _index(self):
        return render_template('index.html')
    
    def _settings(self):
        return render_template('settings.html')

    def _get_position(self):
        if self._map != None and self._map.valid:
            return jsonify({'success': self._map.valid, "position": self._map.current_position})
        else:
            return jsonify({'success': False, 'error': "No map loaded"}), 400

    def _set_gpx(self):
        def map_dictionary():
            return {'success': self._map.valid, 'gpx': self._map.coordinates, "position": self._map.current_position, 'new_data': False}


        if 'gpxFile' not in request.files:
            if self._map != None and self._map.valid:
                print("Loading old Map")
                return jsonify(map_dictionary())
            else:
                return jsonify({'success': False, 'error': 'Unknown error'}), 404
        
        file = request.files['gpxFile']
        if file.filename == '':
            if self._map != None and self._map.valid:
                return jsonify(map_dictionary())
            else:
                return jsonify({'success': False, 'error': 'No file selected'}), 402

        # Save the file to the server
        try:
            filepath = os.path.join(self.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)
            self._map = Map(filepath)
        except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 403

        # Return the coordinates and elevation as JSON
        content = map_dictionary()
        content["new_data"] = True
        return jsonify(content)



    def _allowed_file(self, filename):
        # Check if the file is allowed (ends with .gpx)
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

    def _set_control_mode(self):
        data = request.get_json()
        checkbox_state = data.get('checkbox_state')
        # Do something with the checkbox state (True or False)
        print(f"Checkbox state received: {checkbox_state}")
        return jsonify({"message": "Checkbox state updated", "state": checkbox_state})




if __name__ == '__main__':
    app = WebGUIBackend(__name__)
    app.run(debug=True)
