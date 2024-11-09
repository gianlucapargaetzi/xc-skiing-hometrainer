import serial
import datetime

from pyModbusTCP.client import ModbusClient
from pyModbusTCP import utils 
from time import sleep, time


# Bei Modbus TCP ist die SlaveID immer 0
client1 = ModbusClient(host="192.168.200.199", port=502, unit_id=0, auto_open=True)

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
    print("Initialise DriveReset 10.033")
    client1.write_single_register(1032, 1)
    client1.write_single_register(1032, 0)

def EnableDisableWatchDog(watchdog):
    print("Writing WatchDog 06.043      :", watchdog)
    client1.write_single_register(642, watchdog)
    
def writeWatchDog(watchdog):
    print("Writing WatchDog 06.042      :", watchdog)
    client1.write_single_register(641, watchdog)
    

def writeTorque(torque):
    print("Writing Torque 04.008        :", torque)
    client1.write_single_register(407, torque*100)

def writeSpeed(speed):
    print("Writing Speed 01.018         :", speed)
    client1.write_single_register(117, speed*10)

def writeClockWiseDirection(direction):
    print("Writing Direction 06.030     :", direction)
    client1.write_single_register(629, direction)

def EnableDisableForwardLimit(flag):
    print("Initialise  12.036           :", flag)
    client1.write_single_register(1235, flag)

def saveForwardLimitSwitchPosition():
    print("Setting 12.010 to Input 1")
    client1.write_single_register(1209, 0)
    sleep(0.1)
    print("Setting 12.010 to Input 1")
    client1.write_single_register(1209, 1)



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

def main():

    EnableDisableWatchDog(0)
    DriveReset()

    # Sicherheitseinstellungen vor dem Initialisieren
    writeTorque(0)
    writeSpeed(0)
    writeClockWiseDirection(0)

    print("Ziehen sie das Seil ein Stück weit heraus und lassen sie es los")
    eingabe = input("Nach dem drücken einer Taste wird die Initialisierungssequenz gestartet")
    
    # Endschalterüberwachung deaktivieren
    EnableDisableForwardLimit(0)

    print("Betätigen sie nun beide Sicherheitsschalter.")
    print("das System fährt automatisch an den oberen Anschlag und stopp da")
    
    writeClockWiseDirection(1)
    writeTorque(5)
    writeSpeed(100)


    while readSpeed()==0:
        print("Warten auf Freigabe")
        sleep(0.5)

    writeClockWiseDirection(1)
    writeTorque(5)
    writeSpeed(100)

    sleep(1)

    while readSpeed()>0:
        print("Warten auf Anschlag")

    # Am Anschlag wird das Richtungsbit entfernd
    writeClockWiseDirection(0)

    # Enschalterposition speichern und Endschalter aktivieren
    saveForwardLimitSwitchPosition()    
    EnableDisableForwardLimit(1)
    
    print("Die Sicherheitsschaltung ist kalibriert")
    eingabe = input("Sie können nun eine Taste drücken und dann den Drive aktivieren")


    EnableDisableForwardLimit(1)
    writeClockWiseDirection(1)
    writeTorque(5)
    writeSpeed(2000)
    EnableDisableWatchDog(1)


    sollwert = 20


    while True:

        writeWatchDog(0)
        #start = datetime.datetime.now()
        # Prozessdaten lesen
        
        writeTorque(20)
        writeWatchDog(16384)

if __name__ == '__main__':
    main()

