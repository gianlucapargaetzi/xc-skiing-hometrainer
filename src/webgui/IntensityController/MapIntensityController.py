from IntensityController.IntensityControllerInterface import IntensityControllerInterface
from webgui.webgui import BackendNode
from threading import Lock


from typing import Tuple, List
import gpxpy
import geopy.distance

import numpy as np
import os
from Utils.CustomLogger import CustomLogger


class Map():
    def __init__(self, filepath):
        self._valid = False
        self._filepath = filepath
        self._coordinates = []
        self._distances: np.ndarray = None
        self._current_position = None
        self._total_length = 0.0

        if not os.path.exists(self._filepath):
            CustomLogger.error(f".GPX File '{self._filepath}' does not exist")
            return
        
        self._valid = self._open()

    def _open(self) -> bool:
        # Parse the GPX file and extract coordinates and elevation
        with open(self._filepath, 'r') as gpx_file:
            gpx = gpxpy.parse(gpx_file)
            coordinates = []   
            if len(gpx.tracks) == 0:
                CustomLogger.error("No tracks found!")
                return False
            
            if len(gpx.tracks) > 1:
                CustomLogger.warning("More than one track found! Discarding tracks other than first one!")   

            track = gpx.tracks[0]

            if len(track.segments) == 0:
                CustomLogger.error("No segments found!")
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
    def valid(self):
        return self._valid 

    @property
    def filepath(self):
        return self._filepath    

    @property
    def coordinates(self):
        return self._coordinates
    
    def getMapInformationFromDistance(self, distance: float) -> dict:
        """Calculate Coordinates and elevation based on passed distance from start

        Args:
            distance (float): Traveled distance from start

        Returns:
            dict: returns {"lat": latitude, "lon":longitude, "elevation": elevation, "distance":distance}
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
    

class MapIntensityController(IntensityControllerInterface, BackendNode):
    def __init__(self):
        IntensityControllerInterface.__init__(self, "MapIntensityController")
        BackendNode.__init__(self, "MapIntensityController", 1)

        self._map: Map = None

        self._last_map_state_lock = Lock()
        self._last_map_state: dict = {"timestamp": 0.0, "speed": 0.0, "map_information": {"lon": 0.0, "lat": 0.0, "distance": 0.0, "elevation": 0.0}}



    def loadGPX(self, filepath: str):
        self._map = Map(filepath=filepath)
        pass

    def update(self, sim_value: dict):
        """This is the callback for DigitalTwin to update the map position based on DigitalTwin simulated speed

        Args:
            sim_val
        """
        if self._last_map_state['timestamp']== 0.0:
            self._last_map_state  = {"timestamp": sim_value["timestamp"], 
                                     "speed": sim_value["speed"], 
                                     "map_information": {"lon": 0.0, 
                                                         "lat": 0.0, 
                                                         "distance": 0.0, 
                                                         "elevation": 0.0}}
            return

        if self._running.is_set():
            dt = sim_value['timestamp'] - self._last_map_state['timestamp']
            # Calculate covered distance since last update with linear interpolation betwee v0 and v1
            ds = (self._last_map_state['speed'] + sim_value['speed'])/2 * dt
            new_distance = self._last_map_state["map_information"]["distance"] + ds

            new_map_state = {"timestamp": sim_value["timestamp"], 
                             "speed": sim_value["speed"], 
                             "map_information": self._map.getMapInformationFromDistance(new_distance)}
            
            with self._last_map_state_lock:
                self._last_map_state = new_map_state

