
import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
ADVERTISING_IFACE = 'org.bluez.LEAdvertisement1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHARACTERISTIC_IFACE = 'org.bluez.GattCharacteristic1'

CYCLING_POWER_SERVICE_UUID = '1818'
CYCLING_POWER_MEASUREMENT_UUID = '2A63'


class PowerMeasurementCharacteristic(dbus.service.Object):
    def __init__(self, bus, index, service):
        self.path = service.path + f'/char{index}'
        self.bus = bus
        self.uuid = CYCLING_POWER_MEASUREMENT_UUID
        self.service = service
        self.notifying = False
        self.current_power = 0
        self.current_cadence = 90  # default testwert

        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHARACTERISTIC_IFACE: {
                'UUID': self.uuid,
                'Service': self.service.get_path(),
                'Flags': ['notify'],
                'Notifying': self.notifying,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def _build_notify_value(self):
        # Flags: Bit 0 = Power present, Bit 1 = Cadence present → 0x0003
        flags = 0x0003
        power = max(-32768, min(32767, int(self.current_power)))  # signed 16-bit
        cadence = max(0, min(254, int(self.current_cadence)))     # 1 byte unsigned

        # Byte-Array (Little Endian): Flags (2), Power (2), Cadence (1)
        value = [
            flags & 0xFF,
            (flags >> 8) & 0xFF,
            power & 0xFF,
            (power >> 8) & 0xFF,
            cadence
        ]
        return dbus.Array(value, signature='y')

    def send_power(self):
        if not self.notifying:
            return True

        value = self._build_notify_value()

        # sende Notification über PropertiesChanged
        self.PropertiesChanged(
            GATT_CHARACTERISTIC_IFACE,
            {'Value': value},
            []
        )
        return True  # GLib.timeout_add erwartet True für Wiederholung

    def set_power(self, watts):
        self.current_power = watts

    def set_cadence(self, rpm):
        self.current_cadence = rpm

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        GLib.timeout_add(1000, self.send_power)  # alle 1 Sekunde senden

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature='', out_signature='')
    def StopNotify(self):
        self.notifying = False

    @dbus.service.signal(dbus_interface='org.freedesktop.DBus.Properties',
                         signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class PowerMeterService(dbus.service.Object):
    def __init__(self, bus, index):
        self.path = f'/org/ble/powermeter/service{index}'
        self.bus = bus
        self.uuid = CYCLING_POWER_SERVICE_UUID
        self.primary = True
        self.characteristics = [PowerMeasurementCharacteristic(bus, 0, self)]
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)


class PowerMeterAdvertisement(dbus.service.Object):
    PATH = '/org/ble/advertisement0'

    def __init__(self, bus):
        self.bus = bus
        dbus.service.Object.__init__(self, bus, self.PATH)

    def get_path(self):
        return dbus.ObjectPath(self.PATH)

    @dbus.service.method('org.freedesktop.DBus.Properties',
                         in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != ADVERTISING_IFACE:
            raise dbus.exceptions.DBusException("Invalid interface")
        return {
            'Type': 'peripheral',
            'LocalName': 'X-Ski Sensor',
            'ServiceUUIDs': [CYCLING_POWER_SERVICE_UUID],
            'IncludeTxPower': True
        }

    @dbus.service.method(ADVERTISING_IFACE)
    def Release(self):
        print('Advertisement released')

class BLEPowerServer:
    def __init__(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        adapter = '/org/bluez/hci0'
        self.app = Application(self.bus)
        self.ad = PowerMeterAdvertisement(self.bus)
        self.service_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter), GATT_MANAGER_IFACE)
        self.ad_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter), LE_ADVERTISING_MANAGER_IFACE)
        self.char = self.app.services[0].characteristics[0]

    def start(self):
        self.service_manager.RegisterApplication(self.app.get_path(), {},
                                                 reply_handler=lambda: print('✅ GATT application registered'),
                                                 error_handler=lambda e: print(f'❌ Failed to register application: {e}'))
        self.ad_manager.RegisterAdvertisement(self.ad.get_path(), {},
                                              reply_handler=lambda: print('✅ Advertisement registered'),
                                              error_handler=lambda e: print(f'❌ Failed to register advertisement: {e}'))
        GLib.MainLoop().run()

    def set_power(self, watts):
        self.char.set_power(watts)

    def set_cadence(self, rpm):
        self.char.set_cadence(rpm)



class Application(dbus.service.Object):
    PATH_BASE = '/org/ble/powermeter'

    def __init__(self, bus):
        self.path = self.PATH_BASE
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        self.add_service(PowerMeterService(bus, 0))

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for char in service.characteristics:
                response[char.get_path()] = char.get_properties()
        return response
