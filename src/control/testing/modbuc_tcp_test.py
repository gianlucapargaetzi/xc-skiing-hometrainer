import serial
from pyModbusTCP.client import ModbusClient
from time import sleep, time

# Bei Modbus TCP ist die SlaveID immer 0
client1 = ModbusClient(host="192.168.200.199", port=502, unit_id=0, auto_open=True)

def writeTorque(torque):
    print("Writing Torque", torque)
    #client1.write_register(408, torque,1,16, False)
    client1.write_single_register(408, torque*10)

def writeSpeed(speed):
    print("Writing", speed)
    #client1.write_register(117, speed, 1, 16, False)
    client1.write_single_register(117, speed*10)

def writeClockWiseDirection(direction):
    print("Writing Direction", direction)
    #client1.write_register(629,direction,0,16,True)
    client1.write_single_register(629, direction)

def main():

    writeSpeed(100)
    writeTorque(10)
    writeClockWiseDirection(0)

    print("********************************************************************")
    print("---- Initialisierung ")
    print("********************************************************************")
    print("Bitte Seil ganz ausrollen, danach wird die Startposition gesucht")
    eingabe = input("Bitte Taste drücken ")

    # px_out Position ganz ausgezogen
    p12 = client1.read_holding_registers(327,2)
    print("Registers:",p12)

    p1_out = p12[0]
    p2_out = p12[1]
    p_start = ((p1_out+12)*65535)+p2_out

    writeSpeed(50)
    writeTorque(10)
    writeClockWiseDirection(1);
    
    while True:
        p12 = client1.read_holding_registers(327,2)
        p1 = p12[0]
        p2 = p12[1]
        position = (p1*65535)+p2
        speed = client1.read_holding_registers(301,1)[0]/10
        torque = client1.read_holding_registers(419,1)[0]/10

        # Grobpositionierung
        while (position <= p_start):
            print("Speed    :", speed)
            print("Torque   :", torque)
            print("P1       :", p1)
            print("P2       :", p2)
            print("position :",position)
            p12 = client1.read_holding_registers(327,2)
            p1 = p12[0]
            p2 = p12[1]
            position = (p1*65535)+p2
            writeClockWiseDirection(1)

        print("Startposition erreicht")
        startposition = position
        #writeClockWiseDirection(0);
        break

    # Startposition ist n-Umdrehung von voll augewickelt weg
    startposition = (p1-1)*65535+p2

    writeSpeed(800)
    writeTorque(5)


    while True:

        speed = client1.read_holding_registers(301,1)[0]/10
        torque = client1.read_holding_registers(419,1)[0]/10
        p12 = client1.read_holding_registers(327,2)
        p1 = p12[0]
        p2 = p12[1]
        position = (p1*65535)+p2

        print("Speed    :", speed)
        print("Torque   :", torque)
        print("Position :", position)

        if position > startposition : 
            #writeClockWiseDirection(1)
            writeTorque(0)
        else:
            if position < startposition-500:
                writeTorque(50)


if __name__ == '__main__':
    main()

