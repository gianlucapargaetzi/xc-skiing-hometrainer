import logging

# ANSI escape codes for colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

CustomLogger = logging.getLogger("CustomLogger")
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
    

handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter("%(levelname)s: %(message)s"))
CustomLogger.addHandler(handler)
CustomLogger.setLevel(logging.INFO)
