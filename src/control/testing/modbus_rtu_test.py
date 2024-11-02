import serial
import minimalmodbus

from time import sleep, time

client1 = minimalmodbus.Instrument('/dev/ttyACM0', 1, debug=False)  # port name, slave address (in decimal)
client1.serial.baudrate = 115200  # baudrate
client1.serial.bytesize = 8
client1.serial.parity   = serial.PARITY_NONE
client1.serial.stopbits = 1
client1.serial.timeout  = 1      # seconds
client1.address         = 1        # this is the slave address number
client1.mode = minimalmodbus.MODE_RTU # rtu or ascii mode
client1.clear_buffers_before_each_transaction = False

def writeTorque(torque):
    print("Writing Torque 407")
    client1.write_register(408, torque,1,16, False)

def writeSpeed(speed):
    print("Writing 117", speed)
    client1.write_register(117, speed, 1, 16, False)

def writeClockWiseDirection(direction):
    print("Writing 629", direction)
    client1.write_register(629,direction,0,16,True)

def main():

    #writeTorque(10)

    print("********************************************************************")
    print("---- Initialisierung ")
    print("********************************************************************")
    writeClockWiseDirection(0);
    print("Bitte Seil ganz ausrollen, danach wird die Startposition gesucht")
    eingabe = input("Bitte Taste drücken ")

    # px_out Position ganz ausgezogen
    p1_out = client1.read_register(327,0,3,False)
    p2_out = client1.read_register(328,0,3,False)
    p_start = ((p1_out+11)*65535)+p2_out

    writeSpeed(50
               )
    writeTorque(10)
    writeClockWiseDirection(1);
    
    while True:
        p1 = client1.read_register(327,0,3,False)
        p2 = client1.read_register(328,0,3,False)
        position = (p1*65535)+p2
        speed = client1.read_register(9,1,3,True)
        torque = client1.read_register(419,1,3,True)

        # Grobpositionierung
        while (position <= p_start):
            print("Speed    :", speed)
            print("Torque   :", torque)
            print("P1       :", p1)
            print("P2       :", p2)
            print("position :",position)
            p1 = client1.read_register(327,0,3,False)
            p2 = client1.read_register(328,0,3,False)
            position = (p1*65535)+p2
            writeClockWiseDirection(1)

        print("Startposition erreicht")
        startposition = position
        writeClockWiseDirection(0);
        break

    # Startposition ist n-Umdrehung von voll augewickelt weg
    startposition = (p1-2)*65535+p2

    writeSpeed(1200)
    writeTorque(10)

    while True:

        speed = client1.read_register(9,1,3,True)
        torque = client1.read_register(419,1,3,True)
        p1 = client1.read_register(327,0,3,False)
        p2 = client1.read_register(328,0,3,False)
        position = (p1*65535)+p2

        print("Speed    :", speed)
        print("Torque   :", torque)
        print("Position :", position)

        if position < startposition : 
            writeClockWiseDirection(1);
        else:
            writeClockWiseDirection(0);

if __name__ == '__main__':
    main()

