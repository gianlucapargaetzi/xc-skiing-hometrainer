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



def writeSpeed(speed):
    print("Writing 110", speed)
    client1.write_bit(110, True, 5)
    print("Writing 103", speed)
    client1.write_register(103, speed, 1, 16, False)

def main():

    while True:
        tstart = time()

        while (time()-tstart) < 10:
            tstart = time()
            speed = client1.read_register(9, 1, 3, True)
            tend = time()
            # revs = client1.read_register(328, 0, 3, False)
            # pos = client1.read_register(329, 0, 3, False)
            print("Reading Frequency", 1/(tend-tstart))

if __name__ == '__main__':
    main()