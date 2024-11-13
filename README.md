# How to install the Software for XC-FIT v1.0
## Prerequisites
This Project was designed to be run on a Raspberry Pi 5 using the provided Raspberry Pi OS.

The Software was tested with Kernel 6.6

## Install the Software Stack
To install the GUI and control backend, follow the steps below.
1. Clone this repository
    ```
    git clone https://github.com/gianlucapargaetzi/xc-skiing-hometrainer.git
    ```

2. The python sources are running in a virtual environment, which needs to be installed.
    ```
    cd <cloned-repository>/scripts
    ./install_environment.sh
    ```

3. From now on, if you want to work with any xc-skiing sources, make sure your environment is activated.
    ```
    source <cloned-repository>/.venv/bin/activate
    ```
    > You should see a **(.venv)** prefixing your console commands

4. Start the User Interface
    ```
    cd <cloned-repository>/src/webgui
    python3 WebGUIBackend.py
    ```
5. Open the GUI in your browser at `127.0.0.1:5000`

# Code Structure
## Overview
The Code is structured as followed, providing a set of simple Interface to extend the functionality in the future:
```mermaid
classDiagram
class HardwareController {
    +init() bool
    +start() bool
    +stop() bool
    +register_value_handler(ValueHandler) bool
    +set_controller(IntensityController) bool
    -_state: ControllerState
    -_intensity_lock: Lock
    -_hw: MotorControlInterface
    -_thread: Thread
    -_run()
    -_value_handlers: list[ValueHandler]
}

HardwareController --> MotorControlInterface 
HardwareController --> IntensityController

IntensityController <|.. SimpleIntensityController
IntensityController <|.. IntervallController
IntensityController <|.. MapController

ValueHandler <|.. DigitalTwin
ValueHandler <|.. Scope
HardwareController --> ValueHandler

MotorControlInterface <|-- NidecM751TCP 
NidecM751TCP --|> ModbusClient

MapController ..> DigitalTwin

class SimpleIntensityController {
    +set_intensity(float): bool
}

class IntensityController {
    <<interface>>
    +start() bool*
    +stop() bool*
    +get_intensity() float*
    -_update() void*

    -_data_lock : Lock
    -_last_intensity : float
    -_update_thread : Thread
}

class SimpleIntensityController {
    <<singleton>>
}

class IntervallController {
    <<singleton>>
}

class MapController {
    <<singleton>>
    +sim_callback(SimValueStruct) bool
    -_trigger_update : Event
    -_last_sim_data : SimValueStruct
    -_sim_data_lock : Lock

}

class Scope {
    <<singleton>>
}

class DigitalTwin {
    <<singleton>>

}

class ValueHandler {
    <<abstract>>
    +start() bool*
    +stop() bool*
    +reset()*
    +evaluate_values(ValueStruct)*
    -_update() void*



    -_data_lock : Lock
    -_last_data : ValueStruct
    -_trigger_update : Event
    -_update_thread : Thread
}

class MotorControlInterface {
    <<interface>>
    +program(SystemSpecificatons)*
    +setup()*
    +start()* bool
    +stop()* bool
    +triggerWatchdog()* bool
    +set_target_torque(float)* bool
    +set_target_velocity(float)* bool
    +get_actual_torque()* float
    +get_actual_velocity()* float
    +get_actural_position()* int
    +get_errors()* int
    +read(**kwargs)* list[int]
    +write(**kwargs)* bool
}

class BTHeartRateMonitor {
    <<singleton>>
    +discover()
    +start(str) bool
    +stop
}






Config *-- Config








class WebGUIBackend {
    <<singleton>>
}
Flask <|-- WebGUIBackend
SocketIO <|-- WebGUIBackend

class Config {
    <<singleton>>
    -_instance : Config
    -_config_file : str
    -_instance : Lock
    -_get(str section, str key) str
    -_set_(str section, str key, str value)
}


```

## Quick Explanation
### Value Handlers
**evaluate_values** uses *_data_lock* to pass newest drive values to the ValueHandler class and then triggers the *_trigger_update*-Event.
The *_update_thread* (which is running *_update()*) waits for that event to start processing and publishing to SocketIO. *_update_thread* should be registered using SocketIO().start_background_task(_update())

### Intensity Controllers
#### Simple
This is a simple interface object allowing to asynchronosly set and get intensity values in a thread safe manner. Both **get_intensity** and **set_intensity** use *_data_lock* to read / write *_last_intensity*
#### Intervall
This is an "auto-update" object. The thread *_update_thread* (which is running *_update()*) sets the intensity internally and periodically (with specified intervall) from a training programm file in a thread safe manner using *_data_lock* and publishes it to SocketIO. The intensity can be read asychronously with **get_intensity**, which is also using *_data_lock*. *_update_thread* should be registeret using SocketIO().start_background_task(_update())

#### Map
This controller is the most complicated, but works quite similar to the Value Handlers.
**sim_callback** is registered with the DigitalTwin. Once the DigitalTwin calculated a new value, it executes **sim_callback** of the Map Controller, which sets *_last_sim_data* using *_sim_data_lock* and triggers *_trigger_update*
The running *_update_thread* (waiting for *_trigger_update*) then recalculates the intensity, sets *_last_intensity* using *_data_lock* and publishes it to SocketIO. The data can be read thread safe using **get_intensity**. *_update_thread* should be registeret using SocketIO().start_background_task(_update())






```mermaid
sequenceDiagram
    WebGUIBackend->>HardwareController: Initialize
    activate HardwareController
    HardwareController->>MotorControlInterface : Set Homing Parameters
        activate MotorControlInterface
    loop ReadInterval
        HardwareController->>MotorControlInterface : Request Current

        MotorControlInterface-->>HardwareController : Return Current


        break Current > Threshold
            HardwareController->>MotorControlInterface : Request Home Position
            MotorControlInterface-->>HardwareController : Return Home Position
        end
        deactivate MotorControlInterface
    end

    HardwareController-->>WebGUIBackend: Return Success
    deactivate HardwareController



    WebGUIBackend->>HardwareController : Start
    activate HardwareController
    HardwareController-->>WebGUIBackend : Return Success

    loop ReadInterval
    HardwareController->>MotorControlInterface : Request Values
    activate MotorControlInterface
    activate IntensityController
    MotorControlInterface-->>HardwareController : Return Values
    deactivate MotorControlInterface


    HardwareController->>ValueHandler : Trigger Evaluation with new Values
    activate ValueHandler
    deactivate IntensityController
    HardwareController->>IntensityController : Request Intensity
    activate IntensityController
    IntensityController-->>HardwareController : Return Intensity
    deactivate IntensityController
    deactivate ValueHandler
    end

    WebGUIBackend->>HardwareController : Stop
    HardwareController-->>WebGUIBackend : Return Success
    deactivate HardwareController



```

