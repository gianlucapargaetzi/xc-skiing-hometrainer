

import struct
from datetime import datetime

FILE_HDR_SIZE = 14
PROTOCOL_VERSION = 0x10
PROFILE_VERSION = 0x0100

def fit_crc(data):
    crc_table = [
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    ]
    crc = 0
    for b in data:
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ crc_table[b & 0xF]
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ crc_table[(b >> 4) & 0xF]
    return crc

class FitEncoderMinimal:
    def __init__(self):
        self.records = []

    def add_record(self, timestamp, cadence, power, heart_rate, torque):
        ts = int((timestamp - datetime(1989, 12, 31)).total_seconds())
        self.records.append((ts, cadence, power, heart_rate, torque))

    def write(self, file_path):
        out = bytearray()

        # Session message definition (local message type 1)
        out += b'\x41' + b'\x04\x00\x01\x00\x00\x00'
        out += b'\x0D\x00\x01\x02'  # sport (uint8)
        out += b'\x0E\x00\x01\x02'  # sub_sport (uint8)

        # Session data message (sport = 24, sub_sport = 29)
        out += b'\x01'
        out += struct.pack('<B', 24)  # sport = training
        out += struct.pack('<B', 29)  # sub_sport = indoor_skiing

        # Record definition (local message type 0)
        out += b'\x40' + b'\x04\x00\x01\x00\x00\x00'
        out += b'\x05\x00\x04\x86'  # timestamp
        out += b'\x02\x00\x01\x02'  # cadence
        out += b'\x07\x00\x02\x84'  # power
        out += b'\x03\x00\x01\x02'  # heart rate
        out += b'\x31\x00\x01\x02'  # torque

        for r in self.records:
            out += b'\x00'
            out += struct.pack('<IBHB', r[0], r[1], r[2], r[3])
            out += struct.pack('<B', r[4])

        data_size = len(out)
        header = struct.pack('<BBHI4sB', FILE_HDR_SIZE, PROTOCOL_VERSION, PROFILE_VERSION, data_size, b'.FIT', 0x00)
        final = bytearray(header)
        final[-1:] = struct.pack('<B', fit_crc(header[:-1]) & 0xFF)
        final += out
        final += struct.pack('<H', fit_crc(out))

        with open(file_path, 'wb') as f:
            f.write(final)

