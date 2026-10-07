from threading import Lock
import configparser
import os

import logging


def find_files(directory: str, file_ending: str):
    """Returns a list of all .ini files in the specified directory."""
    ini_files = [file for file in os.listdir(directory) if file.endswith(file_ending)]
    return ini_files


class UserConfig:
    def __init__(self, file_path):
        self._file_path: str = None
        if not os.path.exists(file_path):
            logging.log(logging.ERROR, f"File '{file_path}' does not exist!")
            return
        
        self._file_path = file_path

    @property
    def file_name(self) -> str:
        if self._file_path is None:
            return None
        return self._file_path.split("/")[-1]

    @property
    def json(self) -> dict:
        pass

    @json.setter
    def json(self, json: dict):
        pass
        

class GeneralConfig:
    _instance = None
    _config_file = None

    def __new__(cls, config_file='config.ini'):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._config_file = os.path.abspath(config_file)

                if not os.path.exists(cls._config_file):
                    logging.log(logging.ERROR, f"Config File '{cls._config_file}' does not exist!")
                    cls._config_file = None
                    
        return cls._instance

    
    @property
    def mounting_height(cls) -> float:
        try:
            return float(cls._get('MECHANICS', 'mounting_height'))
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None
        
    @mounting_height.setter
    def mounting_height(cls, mounting_height: float): 
        try:
            cls._set('MECHANICS', 'mounting_height', str(mounting_height))
        except Exception as e:
            logging.log(logging.ERROR, str(e))

    @property
    def pulley_diameter(cls) -> float:
        try:
            return float(cls._get('MECHANICS', 'pulley_diameter'))
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None
        
    @pulley_diameter.setter
    def pulley_diameter(cls, pulley_diameter: float): 
        try:
            cls._set('MECHANICS', 'pulley_diameter', str(pulley_diameter))
        except Exception as e:
            logging.log(logging.ERROR, str(e))

    @property
    def controller_ip_address(cls) -> str:
        try:
            return str(cls._get('COMMUNICATION', 'controller_ip_address'))
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None
        
    @controller_ip_address.setter
    def controller_ip_address(cls, controller_ip_address: float): 
        try:
            cls._set('COMMUNICATION', 'controller_ip_address', str(controller_ip_address))
        except Exception as e:
            logging.log(logging.ERROR, str(e))

    @property
    def controller_slave_id(cls) -> str:
        try:
            return int(cls._get('COMMUNICATION', 'controller_slave_id'))
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None
        
    @controller_slave_id.setter
    def controller_slave_id(cls, controller_slave_id: int): 
        try:
            cls._set('COMMUNICATION', 'controller_slave_id', str(controller_slave_id))
        except Exception as e:
            logging.log(logging.ERROR, str(e))

    @property
    def profile_directory(cls) -> str:
        try:
            return os.path.expanduser(cls._get('USER_DATA', 'profile_directory'))
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None

    @property
    def profile_list(cls) -> str:
        try:
            dir = os.path.expanduser(cls._get('USER_DATA', 'profile_directory'))
            return find_files(dir, '.ini')
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None

    @property
    def map_directory(cls) -> str:
        try:
            return os.path.expanduser(cls._get('USER_DATA', 'map_directory'))
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None

    @property
    def map_list(cls) -> str:
        try:
            dir = os.path.expanduser(cls._get('USER_DATA', 'map_directory'))
            return find_files(dir, '.gpx')
        except Exception as e:
            logging.log(logging.ERROR, str(e))
            return None

    def _get(cls, section, key):

        return config.get(section, key)

    def _set(cls, section, key, value):
        """Set a configuration value and update the config file."""
        if cls._config_file is None:
            return None
        config = configparser.ConfigParser()
        config.read(cls._config_file)

        if not config.has_section(section):
            config.add_section(section)
        config.set(section, key, value)
        with open(cls._config_file, 'w') as configfile:
            config.write(configfile)
    





# Example Usage in main module
if __name__ == "__main__":
    config = Config()
    print(config.get("Settings", "username"))
    config.set("Settings", "username", "new_user123")
    print(config.get("Settings", "username"))

