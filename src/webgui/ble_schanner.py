from bleak import BleakScanner
import asyncio

async def scan():
    devices = await BleakScanner.discover()
    for d in devices:
        print(f"{d.name} ({d.address})")

asyncio.run(scan())
