import pysoem  # or pyEtherCAT depending on the library you're using
import time

# Create an EtherCAT master instance
master = pysoem.Master()
master.close()

master.open('eth0')

# Configure the network interface and initialize EtherCAT

if master.config_init() > 0:
    for device in master.slaves:
        print(f'Found Device {device.name}')
else:
    print('no device found')


# Assuming the ASD75 is found, get its slave object
# In most cases, the ASD75 will be the first or second slave device
slave = master.slaves[0]  # Adjust the index based on your network configuration

# For PT Mode the following lines are important

# Servo Mode 4=PT
#slave.sdo_write(0x6060,0x00,(4).to_bytes(1, byteorder='little', signed=False))

# Minimu Torque
#slave.sdo_write(0x6071,0x00,(50).to_bytes(2, byteorder='little', signed=False)) # Target Torque

# So wird der DRive eingeschaltet
#slave.sdo_write(0x6040,0x00,(0b0000000000000110).to_bytes(2, byteorder='little', signed=False)) # Enable Voltage / Quick Stop 
#slave.sdo_write(0x6040,0x00,(0b0000000000000111).to_bytes(2, byteorder='little', signed=False)) # Servo ON
#slave.sdo_write(0x6040,0x00,(0b0000000000001111).to_bytes(2, byteorder='little', signed=False)) # Operation Enable


#Servo Mode=3
slave.sdo_write(0x6060,0x00,(3).to_bytes(1, byteorder='little', signed=False))

#Maximales Drehmoment
slave.sdo_write(0x6072,0x00,(50).to_bytes(2, byteorder='little', signed=False)) # Drehmoment Sollwert

#Damit der Drive beim ziehen keinen Fehler macht, muss Out of Controll Protection abgeschaltet werden
slave.sdo_write(0x2006,0x21,(0).to_bytes(2, byteorder='little', signed=False)) # Drehmoment Sollwert



#Drehzahlosollwert
drehzahl=100
velocity=round(1310720/600*drehzahl)
print ("Velocity", velocity)
slave.sdo_write(0x60FF,0x00,(velocity).to_bytes(4, byteorder='little', signed=True)) # Drehzal Sollwert

status = slave.sdo_read(0x60FF,0)
print("60FF Speed:", status)


# So wird der DRive eingeschaltet
slave.sdo_write(0x6040,0x00,(0b0000000000000110).to_bytes(2, byteorder='little', signed=False)) # Enable Voltage / Quick Stop 
slave.sdo_write(0x6040,0x00,(0b0000000000000111).to_bytes(2, byteorder='little', signed=False)) # Servo ON
slave.sdo_write(0x6040,0x00,(0b0000000000001111).to_bytes(2, byteorder='little', signed=False)) # Operation Enable


start_time = time.time()  # Zeitpunkt, an dem die Schleife beginnt
duration = 60  # Dauer in Sekunden

# Schleife läuft solange, wie 60 Sekunden vergangen sind
while time.time() - start_time < duration:

    # Read the status or check if the drive started
    status = int.from_bytes(slave.sdo_read(0x2000,0x01), byteorder='little', signed=False)
    print("C00.00 Control Mode:", status)

    status = int.from_bytes(slave.sdo_read(0x2000,0x02), byteorder='little', signed=False)
    print("C00.01 Drehrichtung [0=CCW/1=CW]:", status)

    status = int.from_bytes(slave.sdo_read(0x2001,0x14), byteorder='little', signed=False)
    print("C01.13 Quelle Drehzahl:", status)

    status = int.from_bytes(slave.sdo_read(0x2040,0x01), byteorder='little', signed=False)
    print("U40.00 Soll-Drehzahl:", status)

    status = int.from_bytes(slave.sdo_read(0x2003,0x22), byteorder='little', signed=False)
    print("C03.21 Soll-Drehzahl:", status)

    status = int.from_bytes(slave.sdo_read(0x2001,0x18), byteorder='little', signed=False)
    print("C01.18 Torque Feed Forward Gain:", status)


    status = int.from_bytes(slave.sdo_read(0x2040,0x02), byteorder='little', signed=False)
    print("U40.01 Ist-Drehzahl:", status)

    status = int.from_bytes(slave.sdo_read(0x2001,0x17), byteorder='little', signed=False)
    print("C01.16 Quelle Drehmoment:", status)

    status = int.from_bytes(slave.sdo_read(0x2040,0x03), byteorder='little', signed=False)
    print("U40.02 Soll-Drehmoment:", status)

    status = int.from_bytes(slave.sdo_read(0x2040,0x04), byteorder='little', signed=False)
    print("U40.03 Ist-Drehmoment:", status)

    status = int.from_bytes(slave.sdo_read(0x6071,0x00), byteorder='little', signed=False)
    print("Torquer Reference:", status)
    

    # geprüft

    status = int.from_bytes(slave.sdo_read(0x6040,0), byteorder='little', signed=False)
    print("6040 Control Word:", status)

    status = int.from_bytes(slave.sdo_read(0x6041,0), byteorder='little', signed=False)
    print("6041 Status Word:", status)

    status = int.from_bytes(slave.sdo_read(0x6060,0), byteorder='little', signed=False)
    print("6060 Operation Mode:", status)

    status = int.from_bytes(slave.sdo_read(0x60FF,0), byteorder='little', signed=True)
    print("60FF Speed:", status)

    status = int.from_bytes(slave.sdo_read(0x607F,0), byteorder='little', signed=True)
    print("607F Max. Speed:", status)

    status = slave.sdo_read(0x6064,0)
    print("6064 Position:", status)

    time.sleep(5)

# Drive abschalten
slave.sdo_write(0x6040,0x00,(0).to_bytes(2, byteorder='little', signed=False))


# Disconnect after communication
master.close()

