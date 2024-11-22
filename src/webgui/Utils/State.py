from enum import Enum

class ControllerState(Enum):
    UNINITIALIZED=1,
    INITIALIZED=2,
    RUNNING=3,
    PAUSED=4,