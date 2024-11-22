import logging
from BasicWebGUI import BackendNode, Backend

from threading import Event
# ANSI escape codes for colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"


# Custom logging formatter with color
class ColoredFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno == logging.DEBUG:
            record.msg = BLUE + record.msg + RESET
        elif record.levelno == logging.INFO:
            record.msg = GREEN + record.msg + RESET
        elif record.levelno == logging.WARNING:
            record.msg = YELLOW + record.msg + RESET
        elif record.levelno == logging.ERROR:
            record.msg = RED + record.msg + RESET
        elif record.levelno == logging.CRITICAL:
            record.msg = RED + record.msg + RESET
        return super().format(record)

class Logger(BackendNode):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized') or not self._initialized:
            super().__init__(node_name="Logger", update_interval=None)
            self._logger = logging.getLogger("CustomLogger")
            self._handler = logging.StreamHandler()
            self._handler.setFormatter(ColoredFormatter("%(levelname)s: %(message)s"))
            self._logger.addHandler(self._handler)
            self._logger.setLevel(logging.INFO)
            self._initialized = True

    def publish(self, log_level, msg):
        Backend().publish("logging", {"log_level": log_level, "msg": msg})

    def info(self, msg):
        self._logger.info(msg)
        self.publish("INFO", msg)

    def debug(self, msg):
        self._logger.debug(msg)
        self.publish("DEBUG", msg)
    
    def warning(self, msg):
        self._logger.warning(msg)
        self.publish("WARNING", msg)

    def critical(self, msg):
        self._logger.critical(msg)
        self.publish("CRITICAL", msg)

    def error(self, msg):
        self._logger.error(msg)
        self.publish("ERROR", msg)

        