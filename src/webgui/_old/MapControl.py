import gpxpy
import geopy.distance
import os
import numpy as np
import logging


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