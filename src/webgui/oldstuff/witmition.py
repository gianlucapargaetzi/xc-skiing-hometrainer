import pywitmotion as wit
import bluetooth

# set your device's address
imu = "53:E3:DE:24:A9:34"

# Create the client socket
socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
socket.connect((imu, 1))

msgs_num = 0
while msgs_num < 100:
    data = socket.recv(1024)
    # split the data into messages
    data = data.split(b'U') 
    for msg in data:
        q = wit.get_quaternion(msg)
        # q = wit.get_magnetic(msg)
        # q = wit.get_angle(msg)
        # q = wit.get_gyro(msg)
        # q = wit.get_acceleration(msg)
        if q is not None:
            msgs_num = msgs_num+1
            print(q)
socket.close()