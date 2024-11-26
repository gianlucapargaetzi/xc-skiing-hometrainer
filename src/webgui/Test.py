import serial
import datetime

from pyModbusTCP.client import ModbusClient
from pyModbusTCP import utils 
from time import sleep, time
from threading import Lock, Thread

# Bei Modbus TCP ist die SlaveID immer 0
client1 = ModbusClient(host="192.168.200.199", port=502, unit_id=0, auto_open=True)
from flask import Flask, jsonify, request, render_template

from BasicWebGUI import Backend
from IntensityController.IntervallIntensityController import IntervallIntensityController
from IntensityController.SimpleIntensityController import SimpleIntensityController
from ValueHandler.Scope import Scope
from Utils.CustomLogger import Logger
from time import sleep
from threading import Thread
from flask import jsonify, request
import datetime


import numpy as np


# Constants
MIN_VALUE = 10
MAX_VALUE = 100
STEP = 5  # This is the increment/decrement step

def uint16_to_int16(uint16):
    if uint16 >= 2**15:
        return uint16- 2**16
    return uint16


def uint32_to_int32(uint32):
    if uint32 >= 2**31:
        return uint32 - 2**32
    return uint32


def DriveReset():
    #print("Initialise DriveReset 10.033")
    client1.write_single_register(1032, 1)
    client1.write_single_register(1032, 0)
    client1.write_single_register(1032, 1)

def EnableDisableWatchDog(watchdog):
    client1.write_single_register(642, watchdog)
    
def toggleWatchDog():
    client1.write_single_register(641, 0)
    client1.write_single_register(641, 16384)
    

def writeTorque(torque):
    client1.write_single_register(407, torque*100)

def writeSpeed(speed):
    client1.write_single_register(117, speed*10)

def DriveEnable(driveenable):
    client1.write_single_register(614, driveenable)

def writeForwardDirection(direction):
    client1.write_single_register(629, direction)

def writeReverseDirection(direction):
    client1.write_single_register(631, direction)

def EnableDisableForwardLimit(flag):
    client1.write_single_register(1235, flag)

def saveForwardLimitSwitchPosition():
    client1.write_single_register(1209, 0)
    sleep(0.1)
    client1.write_single_register(1209, 1)

def driveHealthy():
    sw = client1.read_holding_registers(1000,1)[0]

    if sw is None:
        return False
    
    if sw==1:
        return True
    
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

def wait_for_drive():
    print("***************************************************************")
    print("Wait until Drive is ready")
    print("***************************************************************")
    while not driveHealthy():
        print("Drive is not ready", end="\r")
        DriveReset()
    print("---------------------------------------------------------------")
    print("Drive is ready")
    print("---------------------------------------------------------------")


def wait_for_sto_OFF():
    print("***************************************************************")
    print("Wait until STO is released")
    print("***************************************************************")
    while readHardwareEnabled():
        print("Please release the STO", end="\r")
    print("---------------------------------------------------------------")
    print("STO is released")
    print("---------------------------------------------------------------")

def wait_for_sto_ON():
    print("***************************************************************")
    print("Wait until STO is ON")
    print("***************************************************************")

    while not readHardwareEnabled():
        print ("Pleas push both STO's",end="\r")
    print("---------------------------------------------------------------")
    print("STO is ON")
    print("---------------------------------------------------------------")    


def calibrate_end_position():
    print("***************************************************************")
    print("Finding end position")
    print("***************************************************************")
    sleep(1)
    DriveEnable(1)
    writeForwardDirection(1)
    writeTorque(5)  # Min Torque
    writeSpeed(100)

    sleep(0.5)

    while readSpeed() > 0:
        pass

    DriveEnable(0)
    writeForwardDirection(0)
    saveForwardLimitSwitchPosition()
    EnableDisableForwardLimit(1)
    print("---------------------------------------------------------------")
    print("End position calibrated")
    print("---------------------------------------------------------------")



if __name__ == '__main__':
    
    app = Backend(__name__)
    # sic = SimpleIntensityController()
    ic = IntervallIntensityController()
    scope = Scope()


    def thread():
        pulli_diameter = 40             # mm
        rope_diameter = 3               # mm
        top_position = 1860             # mm
        pole_length = 1425              # mm
        swing_length = 1100             # mm
        swing_start_max_torque_pml = 200 # %
        swing_end_max_torque_pml = 500   # %
        dist_par_rev = round((pulli_diameter + rope_diameter) * 3.14159)
        min_torque_pct = 10             # % Minimales Drehmomemnt

        # fs_curve als array
        s = np.linspace(0, 1000, 1000)  # Normalisierte Weg-Daten (0 bis 100)
        f_pull = np.zeros_like(s)
        f_warp = np.zeros_like(s)
        f_pull[:swing_start_max_torque_pml-1]=(1/swing_start_max_torque_pml*s[:swing_start_max_torque_pml-1])*100
        f_pull[swing_start_max_torque_pml:swing_end_max_torque_pml-1]=1*100
        f_pull[swing_end_max_torque_pml:]=(-1/swing_end_max_torque_pml*s[swing_end_max_torque_pml:]+2)*100
        f_warp[:]=f_pull[:]*0.5


        # Initialisiere und konfiguriere
        wait_for_drive()
        DriveEnable(0)
        writeTorque(0)
        writeSpeed(0)
        writeForwardDirection(0)
        writeReverseDirection(0)
        EnableDisableWatchDog(0)

        wait_for_sto_OFF()

        # Sicherheitsvorkehrungen und Kalibrierung des Endschalters
        print("***************************************************************")
        print("Pull the rope out about 50cm, then push both STO's")
        print("***************************************************************")
        EnableDisableForwardLimit(0)
        wait_for_sto_ON()
        calibrate_end_position()

        # Berechnungen der Pole-Positionen und Drehmomentfaktoren
        pole_offset = round((top_position - pole_length) / dist_par_rev * 65536)
        abs_zero_position = readNormalisedPosition()
        pole_zero_position = abs_zero_position - pole_offset

        print("Pole Offset:", pole_offset)
        print("Pole Zero Position:", pole_zero_position)

        start_max_torque_position = pole_zero_position - round(swing_start_max_torque_pml / dist_par_rev * 65536)
        end_max_torque_position = pole_zero_position - round(swing_end_max_torque_pml / dist_par_rev * 65536)
        end_swing_position = pole_zero_position - round(swing_length / dist_par_rev * 65536)

        print("Start Max Torque Position:", start_max_torque_position)
        print("End Max Torque Position:", end_max_torque_position)
        print("End Swing Position:", end_swing_position)

        # Positionierung des Pole-Zero
        print("***************************************************************")
        print("Finding the Pole Zero position")
        print("***************************************************************")
        while readNormalisedPosition() > pole_zero_position:
            print("Please pull the rope slowly until the pole position is found", end="\r")

        print("This is the Pole Zero position")
        print("***************************************************************")
        print("The Training can start")
        print("***************************************************************")
        print("Please hold the rope, then push both STO's")

        #wait_for_sto_ON()

        EnableDisableForwardLimit(1)
        writeForwardDirection(1)
        writeTorque(min_torque_pct)
        writeSpeed(2000)
        EnableDisableWatchDog(1)
        DriveEnable(1)

        # Initialisierung der Leistungsmessungen und des Sequenzstatus
        actual_dir = old_dir = True
        sequence_start_time = sequence_end_time = int(datetime.datetime.now().timestamp() * 1000)
        sequence_freq = 0
        torque_scale_factor = 0
        act_torque_pct = min_torque_pct
        ic_torque = 0

        #while readHardwareEnabled():
        while True:
            # Toggle Watchdog zu Beginn und Ende der Schleife
            toggleWatchDog()

            # Lese aktuelle Position und Geschwindigkeit
            actual_position = readNormalisedPosition()
            actual_speed = readSpeed()
            power = readPower()
            actual_dir = actual_speed > 0  # True für Wickeln, False für Zug

            # Frequenzberechnung, wenn sich die Richtung ändert
            if old_dir and not actual_dir:
                # Zug beginnt
                sequence_end_time = sequence_start_time
                sequence_start_time = int(datetime.datetime.now().timestamp() * 1000)
                sequence_freq = 60000 / (sequence_start_time - sequence_end_time)
                ic_torque = ic.getIntensity()
                print("Frequenz in Hub/min:", sequence_freq, " - Belastung [%]:",ic_torque )
                old_dir = actual_dir
            elif not old_dir and actual_dir:
                # Wickeln beginnt
                old_dir = actual_dir

            # Aktualisiere minimale und maximale Leistung
                # Berechnung des Scale-Faktors basierend auf Position

            pos_rel_zero = (100/(end_swing_position-abs_zero_position)) * (actual_position-abs_zero_position)
            pos_rel_pole = (1000/(end_swing_position-pole_zero_position)) * (actual_position-pole_zero_position)

            if pos_rel_pole>=0:
                torque_scale_factor=f_pull[round(pos_rel_pole)]
            else:
                torque_scale_factor=0
                        
            act_torque_pct = round(min_torque_pct + ((ic_torque - min_torque_pct) * torque_scale_factor / 100))
 
            writeTorque(act_torque_pct)

            arr = np.array([pos_rel_zero, actual_speed, act_torque_pct, power, act_torque_pct])
            scope.evaluateValue(arr)

        # wird das Training gestoppt so werden ein paar Parameter im Drive zurückgesetzt,
        # damit nichts ungewolltes passiert
        DriveEnable(0)
        writeSpeed(0)
        writeTorque(0)
        EnableDisableWatchDog(0)
    

    t = Thread(target=thread)
    t.start()
    app.run(host="0.0.0.0",debug=False)
