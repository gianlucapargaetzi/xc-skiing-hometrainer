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
    #print("Initialise DriveReset 10.033")
    client1.write_single_register(1032, 1)
    client1.write_single_register(1032, 0)

def EnableDisableWatchDog(watchdog):
    #print("Writing WatchDog 06.043      :", watchdog)
    client1.write_single_register(642, watchdog)
    
def writeWatchDog(watchdog):
    #print("Writing WatchDog 06.042      :", watchdog)
    client1.write_single_register(641, watchdog)
    

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

def main():

    # 0 - Position ist auf 1920mm
    # Weg pro Umdrehung 166mm
    # Normalisierter Weg pro Umdrehung 65536
    # Stockhöhe 1450mm
    # Zu fahrender Weg 370mm
    # Normailiserte Weg  = 148838

    pulli_diameter = 40     # mm
    rope_diameter = 3       # mm
    top_position = 1870     # mm
    pole_lenght = 1450      # mm
    dist_par_rev = round((pulli_diameter+rope_diameter)*3.14159)

    print("Distanz pro Umdrehung", dist_par_rev, "mm")

    DriveReset()
    sleep(1)
    DriveReset()
    
    DriveEnable(0)
    writeTorque(0)
    writeSpeed(0)
    writeForwardDirection(0)
    writeReverseDirection(0)
    EnableDisableWatchDog(0)
    DriveReset()


    # Sicherheitseinstellungen vor dem Initialisieren
    
    
    while readHardwareEnabled():
        print("Warten bis Sicherheitsschalter gelöst")
        
    
    print("***************************************************************")
    print("Ziehen sie das Seil ein Stück weit heraus und lassen sie es los")
    print("***************************************************************")
    # Endschalterüberwachung deaktivieren
    EnableDisableForwardLimit(0)

    sleep(5)
    print("Betätigen sie dann beide Sicherheitsschalter.")
    print("das System fährt automatisch an den oberen Anschlag und stopp da")
    
    DriveEnable(1)
    writeForwardDirection(1)
    writeTorque(10)
    writeSpeed(100)

    while not readHardwareEnabled():
        print ("Sicherheitsschalter betätigen")
        

    sleep(1)

    print("Warten auf Anschlag")
    while readSpeed()>0:
        pass

    # Am Anschlag wird das Richtungsbit entfernd
    DriveEnable(0)
    writeForwardDirection(0)

    # Enschalterposition speichern und Endschalter aktivieren
    saveForwardLimitSwitchPosition()    
    EnableDisableForwardLimit(1)
    
    print("Die Sicherheitsschaltung ist kalibriert")
    print("Bitte Sicherheitsschalter lösen")

    while readHardwareEnabled():
        pass

    



    pole_offset = round((top_position-pole_lenght )/dist_par_rev*65536)
    print("Pole Offset", pole_offset)

    zeroposition = readNormalisedPosition()
    stockposition = zeroposition - pole_offset

    print("Kalibrierung der Stockposition - bitte langsam ziehen")
    while (readNormalisedPosition()>stockposition):
        pass


    print("Die Stockposition ist kalibriert")
    print("Bitte Sicherheitsschaltung lösen um System zu aktivieren")

    while readHardwareEnabled():
        pass

    print("Schlaufen halten und Sicherheitsschalter betätigen")

    while not readHardwareEnabled():
        pass

    torque_reference = 20
    EnableDisableForwardLimit(1)
    writeForwardDirection(1)
    writeTorque(torque_reference)
    writeSpeed(2000)

    EnableDisableWatchDog(1)
    DriveEnable(1)

    while True:

        writeWatchDog(0)
        #start = datetime.datetime.now()
        # Prozessdaten lesen
        #print("Position                     :",readNormalisedPosition())
        #print("Speed                        :",readSpeed(),end="\r")
        #print("Load                         :",readLoad())
        print("Power                        :",readPower(),end="\r")
        writeTorque(torque_reference)
        writeWatchDog(16384)

if __name__ == '__main__':
    main()

