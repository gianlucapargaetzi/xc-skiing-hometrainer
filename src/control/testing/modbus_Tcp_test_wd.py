import serial
import datetime

from pyModbusTCP.client import ModbusClient
from pyModbusTCP import utils 
from time import sleep, time
from threading import Lock, Thread

# Bei Modbus TCP ist die SlaveID immer 0
# max_torque = 30         # %
# max_torque_lock = Lock()
client1 = ModbusClient(host="192.168.200.199", port=502, unit_id=0, auto_open=True)
from flask import Flask, jsonify, request, render_template

# app = Flask(__name__)

# Constants
MIN_VALUE = 10
MAX_VALUE = 100
STEP = 5  # This is the increment/decrement step

# Initialize the variable
# variable_value = 50  # Start with a middle value for demonstration

# @app.route('/')
# def index():
#     return render_template('index.html')

# @app.route('/get_value', methods=['GET'])
# def get_value():
#     with max_torque_lock:
#         json = jsonify({"value": max_torque})
#         print("Torque: ", max_torque)
#     return json

# @app.route('/increment', methods=['POST'])
# def increment():
#     global max_torque
#     global max_torque_lock
#     with max_torque_lock:
#         max_torque = min(max_torque + STEP, MAX_VALUE)
#         print("Torque: ", max_torque)
#         return jsonify({"value": max_torque})

# @app.route('/decrement', methods=['POST'])
# def decrement():
#     global max_torque
#     global max_torque_lock
#     with max_torque_lock:
#         max_torque = max(max_torque - STEP, MIN_VALUE)
#         print("Torque: ", max_torque)
#         return jsonify({"value": max_torque})

# @app.route('/set_to_20', methods=['POST'])
# def set_to_20():
#     global max_torque
#     global max_torque_lock
#     with max_torque_lock:
#         max_torque = 20
#         print("Torque: ", max_torque)
#         return jsonify({"value": max_torque})

# if __name__ == '__main__':
#     app.run(host="0.0.0.0",debug=True)


class GUIBackend(Flask):
    def __init__(self, *args, **kwargs):
        super().__init__(__name__)
        self._max_torque_lock = Lock()
        self._max_torque = 40
        print("Max Torque gesetzt:")

        self.add_url_rule("/", view_func=self.index)
        self.add_url_rule("/set_to_20", view_func=self.set_to_20,  methods=['POST'])
        self.add_url_rule("/decrement", view_func=self.decrement,  methods=['POST'])
        self.add_url_rule("/increment", view_func=self.increment,methods=['POST'])
        self.add_url_rule("/get_value", view_func=self.get_value,methods=['GET'])



    # def __enter__(self):
    #     self._max_torque_lock.acquire()

    # def __exit__(self):
    #     self._max_torque_lock.release()

    @property
    def max_torque(self):
        return self._max_torque

    def index(self):
        return render_template('index.html')

    def set_to_20(self):
        with self._max_torque_lock:
            self._max_torque = 20
            print("Torque: ", self._max_torque)
            return jsonify({"value": self._max_torque})

    def decrement(self):
        with self._max_torque_lock:
            self._max_torque = max(self._max_torque - STEP, MIN_VALUE)
            print("Torque: ", self._max_torque)
            return jsonify({"value": self._max_torque})
        
    def increment(self):
        with self._max_torque_lock:
            self._max_torque = min(self._max_torque + STEP, MAX_VALUE)
            print("Torque: ", self._max_torque)
            return jsonify({"value": self._max_torque})

    def get_value(self):
        with self._max_torque_lock:
            json = jsonify({"value": self._max_torque})
            print("Torque: ", self._max_torque)
        return json

        


def uint16_to_int16(uint16):
    # Assuming the unsigned integer is meant to fit in 32 bits
    if uint16 >= 2**15:
        return uint16- 2**16
    return uint16


def uint32_to_int32(uint32):
    # Assuming the unsigned integer is meant to fit in 32 bits
    if uint32 >= 2**31:
        return uint32 - 2**32
    return uint32


def DriveReset():
    #print("Initialise DriveReset 10.033")
    client1.write_single_register(1032, 1)
    client1.write_single_register(1032, 0)
    client1.write_single_register(1032, 1)

def EnableDisableWatchDog(watchdog):
    #print("Writing WatchDog 06.043      :", watchdog)
    client1.write_single_register(642, watchdog)
    
def toggleWatchDog():
    #print("Writing WatchDog 06.042      :", watchdog)
    client1.write_single_register(641, 0)
    client1.write_single_register(641, 16384)
    

def writeTorque(torque):
    #print("Writing Torque 04.008        :", torque)
    client1.write_single_register(407, torque*100)

def writeSpeed(speed):
    #print("Writing Speed 01.018         :", speed)
    client1.write_single_register(117, speed*10)

def DriveEnable(driveenable):
    #print("Writing Drive Enable 06.015     :", driveenable)
    client1.write_single_register(614, driveenable)

def writeForwardDirection(direction):
    #print("Writing Forward Direction 06.030     :", direction)
    client1.write_single_register(629, direction)

def writeReverseDirection(direction):
    #print("Writing Reverse Direction 06.032     :", direction)
    client1.write_single_register(631, direction)

def EnableDisableForwardLimit(flag):
    #print("Initialise  12.036           :", flag)
    client1.write_single_register(1235, flag)

def saveForwardLimitSwitchPosition():
    #print("Setting 12.010 to Input 0")
    client1.write_single_register(1209, 0)
    sleep(0.1)
    #print("Setting 12.010 to Input 1")
    client1.write_single_register(1209, 1)

def driveHealthy():
    sw = client1.read_holding_registers(1000,1)[0]
    if sw==1:
        return True
    else:
        return False
    return False

def driveRunning():
    sw = client1.read_holding_registers(1001,1)[0]
    if sw==1:
        return True
    else:
        return False
    return False


def readHardwareEnabled():
    sw = client1.read_holding_registers(628,1)[0]
    if sw==1:
        return True
    else:
        return False
    return False

def readNormalisedPosition():
    p12 = client1.read_holding_registers(327,2)
    return utils.word_list_to_long(p12)[0]

def readForwardLimitSwitch():
    sw = client1.read_holding_registers(634,1)[0]
    if sw==1:
        return True
    else:
        return False
    return False

def readSpeed():
    speed = uint16_to_int16(client1.read_holding_registers(301,1)[0])/10
    return speed

def readLoad():
    load = uint16_to_int16(client1.read_holding_registers(419,1)[0])/10
    return load

def readPower():
    power = uint16_to_int16(client1.read_holding_registers(502,1)[0])
    return power


if __name__ == '__main__':
    # 0 - Position ist auf 1920mm
    # Weg pro Umdrehung 166mm
    # Normalisierter Weg pro Umdrehung 65536
    # Stockhöhe 1450mm
    # Zu fahrender Weg 370mm
    # Normailiserte Weg  = 148838
    # global app
    # def thread():
    #     app.run(host="0.0.0.0",debug=True)

    # t = Thread(target=thread)

    # t.start()
    
    app = GUIBackend()

    def thread():
        pulli_diameter = 40     # mm
        rope_diameter = 3       # mm
        top_position = 1860     # mm
        pole_lenght = 1450      # mm
        dist_par_rev = round((pulli_diameter+rope_diameter)*3.14159)

        min_torque = 5          # %

        swing_lenght_dist = 1000     # mm
        start_max_torque = 200   # mm
        end_max_torque = 500     # mm

        print("***************************************************************")
        print("Wait until Drive is ready")
        print("***************************************************************")

        while not driveHealthy():
            print("Drive is not ready",end="\r")
            DriveReset()

        print("---------------------------------------------------------------")
        print("Drive is ready")
        print("---------------------------------------------------------------")

        DriveEnable(0)
        writeTorque(0)
        writeSpeed(0)
        writeForwardDirection(0)
        writeReverseDirection(0)
        EnableDisableWatchDog(0)
        DriveReset()


        # Sicherheitseinstellungen vor dem Initialisieren

        print("***************************************************************")
        print("Wait until STO is released")
        print("***************************************************************")

        while readHardwareEnabled():
            print("Please release the STO",end="\r")

        print("---------------------------------------------------------------")
        print("STO is released")
        print("---------------------------------------------------------------")
            

        print("***************************************************************")
        print("Pull the rope out abouth 50cm")
        print("Then push both STO's and the rope will be moved in automatically")
        print("to the top limit")
        print("***************************************************************")
        # Endschalterüberwachung deaktivieren
        EnableDisableForwardLimit(0)

        DriveEnable(1)
        writeForwardDirection(1)
        writeTorque(min_torque)
        writeSpeed(100)

        print("***************************************************************")
        print("Wait until STO is ON")
        print("***************************************************************")

        while not readHardwareEnabled():
            print ("Pleas push both STO's",end="\r")

        print("---------------------------------------------------------------")
        print("STO is ON")
        print("---------------------------------------------------------------")    

        sleep(1)

        print("***************************************************************")
        print("Finding endposition")
        print("***************************************************************")

        while readSpeed()>0:
            pass

        # Am Anschlag wird das Richtungsbit entfernd
        DriveEnable(0)
        writeForwardDirection(0)

        # Enschalterposition speichern und Endschalter aktivieren
        saveForwardLimitSwitchPosition()    
        EnableDisableForwardLimit(1)

        print("---------------------------------------------------------------")
        print("Endposition calibrated")
        print("---------------------------------------------------------------")    


        print("***************************************************************")
        print("Wait until STO is released")
        print("***************************************************************")

        while readHardwareEnabled():
            print("Please release the STO",end="\r")

        print("---------------------------------------------------------------")
        print("STO is released")
        print("---------------------------------------------------------------")

        pole_offset = round((top_position-pole_lenght )/dist_par_rev*65536)
        print("Pole Offset                   :", pole_offset)

        abs_zero_position = readNormalisedPosition()
        pole_zero_position = abs_zero_position - pole_offset
        print("Pole Zero Position            :",  pole_zero_position)

        start_max_torque_position = pole_zero_position - round(start_max_torque/dist_par_rev*65536)
        print("Start Max. Torque Position    : ", start_max_torque_position)
        end_max_torque_positition = pole_zero_position - round(end_max_torque/dist_par_rev*65536)
        print("End Max. Torque Position      : ", end_max_torque_positition)
        end_swing_position = pole_zero_position - round(swing_lenght_dist/dist_par_rev*65536)
        print("End Swing Position            : ", end_swing_position)

        scale_factor_up = (pole_zero_position-start_max_torque_position)/100
        print("Scale Factor Up               : ", scale_factor_up )
        scale_factor_down = (end_max_torque_positition-end_swing_position)/100
        print("Scale Factor Down             : ", scale_factor_down )



        print("***************************************************************")
        print("Finding the Pole Zero position")
        print("***************************************************************")
        while (readNormalisedPosition()>pole_zero_position):
            print("Please pull the rope slowly until the pole possitio is found",end="\r")

        print("---------------------------------------------------------------")
        print("This is the Pole Zero position")
        print("---------------------------------------------------------------")


        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("The Training can start")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        print("***************************************************************")
        print("Pleas Hold the rope, then push both STO's")
        print("***************************************************************")

        while not readHardwareEnabled():
            print ("Pleas push both STO's",end="\r")

        print("---------------------------------------------------------------")
        print("STO is ON - Training has started")
        print("---------------------------------------------------------------")    

        torque_reference = 20
        EnableDisableForwardLimit(1)
        writeForwardDirection(1)
        writeTorque(torque_reference)
        writeSpeed(2000)

        EnableDisableWatchDog(1)
        DriveEnable(1)

        min_power=0
        max_power=0

        sequence_running = False
        actual_dir = True
        old_dir = True
        sequence_start_time = int(datetime.datetime.now().timestamp()*1000)
        sequence_end_time =  int(datetime.datetime.now().timestamp()*1000)
        sequence_freq =0



        while readHardwareEnabled():

            scale_factor = 0

            toggleWatchDog()

            actual_position = readNormalisedPosition()
            actual_speed = readSpeed()

            if actual_speed < 0:
                actual_dir=False    # Zug
            else:
                actual_dir=True     # Wickeln

            if old_dir and not actual_dir:
                # Zug beginnt
                sequence_end_time=sequence_start_time
                sequence_start_time = int(datetime.datetime.now().timestamp()*1000)
                sequence_freq=1/((sequence_start_time-sequence_end_time)/1000)*60
                print("Frequenz in Hub/min:",sequence_freq)
                old_dir = actual_dir

            if not old_dir and actual_dir:
                # Wickeln beginnt
                old_dir = actual_dir

            toggleWatchDog()
                

            power =  readPower()
            if power < min_power:
                min_power=power
            if power > max_power:
                max_power=power

            if actual_position >= pole_zero_position:
                scale_factor = 0

            if actual_position < pole_zero_position and actual_position >=  start_max_torque_position:
                scale_factor = round(100-(actual_position-start_max_torque_position)/scale_factor_up)

            if actual_position < start_max_torque_position and actual_position >=  end_max_torque_positition:
                scale_factor = 100
            
            if actual_position < end_max_torque_positition and actual_position >=  end_swing_position:
                scale_factor = round(actual_position-end_swing_position)/scale_factor_down


            toggleWatchDog()

            # Ein bisschen Sicherheit
            if scale_factor < 0:
                scale_factor=0

            if scale_factor > 100:
                scale_factor = 100

            with app._max_torque_lock:
                act_torque = round(min_torque+(app.max_torque-min_torque)/100*scale_factor)
                writeTorque(act_torque)

            toggleWatchDog()


        EnableDisableWatchDog(0)

    t = Thread(target=thread)
    t.start()
    app.run(host="0.0.0.0",debug=False)


