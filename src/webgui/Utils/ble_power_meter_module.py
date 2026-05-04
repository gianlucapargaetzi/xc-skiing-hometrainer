# Utils/ble_power_meter_module.py

import struct
import threading

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib


BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
ADVERTISING_IFACE = "org.bluez.LEAdvertisement1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"

# FTMS UUIDs
FITNESS_MACHINE_SERVICE_UUID = "1826"
FITNESS_MACHINE_FEATURE_UUID = "2ACC"
ROWER_DATA_UUID = "2AD1"
FITNESS_MACHINE_CONTROL_POINT_UUID = "2AD9"

# Device Information Service
DEVICE_INFO_SERVICE_UUID = "180A"
MANUFACTURER_NAME_UUID = "2A29"
MODEL_NUMBER_UUID = "2A24"
FIRMWARE_REVISION_UUID = "2A26"


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class FailedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.Failed"


class Application(dbus.service.Object):
    def __init__(self, bus, path="/org/ble/ftms"):
        self.path = path
        self.services = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for char in service.characteristics:
                response[char.get_path()] = char.get_properties()
        return response


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary=True, path_base="/org/ble/ftms"):
        self.path = f"{path_base}/service{index}"
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        super().__init__(bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": dbus.Boolean(self.primary),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + f"/char{index}"
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.notifying = False
        super().__init__(bus, self.path)

    def get_properties(self):
        return {
            GATT_CHARACTERISTIC_IFACE: {
                "UUID": self.uuid,
                "Service": self.service.get_path(),
                "Flags": dbus.Array(self.flags, signature="s"),
                "Notifying": dbus.Boolean(self.notifying),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHARACTERISTIC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHARACTERISTIC_IFACE]

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        raise NotSupportedException()

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        raise NotSupportedException()

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="", out_signature="")
    def StartNotify(self):
        raise NotSupportedException()

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="", out_signature="")
    def StopNotify(self):
        raise NotSupportedException()

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class StaticReadCharacteristic(Characteristic):
    def __init__(self, bus, index, uuid, value_bytes, service):
        super().__init__(bus, index, uuid, ["read"], service)
        self._value = bytes(value_bytes)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self._value, signature="y")


class FitnessMachineFeatureCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, FITNESS_MACHINE_FEATURE_UUID, ["read"], service)

    def _value(self):
        # 8 Bytes little-endian.
        # Konservativer Start: keine Features behaupten, die wir noch nicht bedienen.
        return (0).to_bytes(8, byteorder="little", signed=False)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self._value(), signature="y")


class RowerDataCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, ROWER_DATA_UUID, ["read", "notify"], service)
        self._lock = threading.Lock()
        self._metrics = {
            "stroke_rate_spm": 0.0,
            "stroke_count": 0,
            "total_distance_m": 0.0,
            "pace_s_per_500": 0,
            "avg_pace_s_per_500": 0,
            "power_w": 0,
            "avg_power_w": 0,
            "hr_bpm": 0,
            "elapsed_s": 0,
            "running": False,
        }

    def set_metrics(
        self,
        *,
        stroke_rate_spm,
        stroke_count,
        total_distance_m,
        pace_s_per_500,
        avg_pace_s_per_500,
        power_w,
        avg_power_w,
        hr_bpm,
        elapsed_s,
        running,
    ):
        with self._lock:
            self._metrics["stroke_rate_spm"] = max(0.0, float(stroke_rate_spm))
            self._metrics["stroke_count"] = self._clamp_int(stroke_count, 0, 0xFFFF)
            self._metrics["total_distance_m"] = max(0.0, float(total_distance_m))
            self._metrics["pace_s_per_500"] = self._clamp_int(pace_s_per_500, 0, 0xFFFF)
            self._metrics["avg_pace_s_per_500"] = self._clamp_int(avg_pace_s_per_500, 0, 0xFFFF)
            self._metrics["power_w"] = self._clamp_int(power_w, -32768, 32767)
            self._metrics["avg_power_w"] = self._clamp_int(avg_power_w, -32768, 32767)
            self._metrics["hr_bpm"] = self._clamp_int(hr_bpm, 0, 255)
            self._metrics["elapsed_s"] = self._clamp_int(elapsed_s, 0, 0xFFFF)
            self._metrics["running"] = bool(running)

        GLib.idle_add(self._emit_value_changed)

    def reset(self):
        self.set_metrics(
            stroke_rate_spm=0,
            stroke_count=0,
            total_distance_m=0,
            pace_s_per_500=0,
            avg_pace_s_per_500=0,
            power_w=0,
            avg_power_w=0,
            hr_bpm=0,
            elapsed_s=0,
            running=False,
        )

    def _build_value(self):
        with self._lock:
            m = dict(self._metrics)

        # Flags:
        # bit 2  Total Distance present
        # bit 3  Instantaneous Pace present
        # bit 4  Average Pace present
        # bit 5  Instantaneous Power present
        # bit 6  Average Power present
        # bit 9  Heart Rate present
        # bit 11 Elapsed Time present
        flags = (
            (1 << 2)
            | (1 << 3)
            | (1 << 4)
            | (1 << 5)
            | (1 << 6)
            | (1 << 9)
            | (1 << 11)
        )

        stroke_rate_half_spm = self._clamp_int(round(m["stroke_rate_spm"] * 2.0), 0, 255)
        stroke_count = self._clamp_int(m["stroke_count"], 0, 0xFFFF)
        total_distance = self._clamp_int(round(m["total_distance_m"]), 0, 0xFFFFFF)
        inst_pace = self._clamp_int(m["pace_s_per_500"], 0, 0xFFFF)
        avg_pace = self._clamp_int(m["avg_pace_s_per_500"], 0, 0xFFFF)
        inst_power = self._clamp_int(m["power_w"], -32768, 32767)
        avg_power = self._clamp_int(m["avg_power_w"], -32768, 32767)
        hr = self._clamp_int(m["hr_bpm"], 0, 255)
        elapsed = self._clamp_int(m["elapsed_s"], 0, 0xFFFF)

        payload = bytearray()
        payload += struct.pack("<H", flags)
        payload += struct.pack("<B", stroke_rate_half_spm)
        payload += struct.pack("<H", stroke_count)
        payload += bytes([
            total_distance & 0xFF,
            (total_distance >> 8) & 0xFF,
            (total_distance >> 16) & 0xFF,
        ])
        payload += struct.pack("<H", inst_pace)
        payload += struct.pack("<H", avg_pace)
        payload += struct.pack("<h", inst_power)
        payload += struct.pack("<h", avg_power)
        payload += struct.pack("<B", hr)
        payload += struct.pack("<H", elapsed)

        return bytes(payload)

    def _emit_value_changed(self):
        if not self.notifying:
            return False

        value = dbus.Array(self._build_value(), signature="y")
        self.PropertiesChanged(
            GATT_CHARACTERISTIC_IFACE,
            {"Value": value},
            [],
        )
        return False

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array(self._build_value(), signature="y")

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="", out_signature="")
    def StartNotify(self):
        self.notifying = True
        self._emit_value_changed()

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False

    @staticmethod
    def _clamp_int(value, lo, hi):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0
        return max(lo, min(value, hi))


class FitnessMachineControlPointCharacteristic(Characteristic):
    def __init__(self, bus, index, service):
        super().__init__(bus, index, FITNESS_MACHINE_CONTROL_POINT_UUID, ["write", "indicate"], service)
        self._last_response = bytes([0x80, 0x00, 0x01])

    def _emit_response(self):
        if not self.notifying:
            return False

        value = dbus.Array(self._last_response, signature="y")
        self.PropertiesChanged(
            GATT_CHARACTERISTIC_IFACE,
            {"Value": value},
            [],
        )
        return False

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        if len(value) < 1:
            raise FailedException("Leerer Control-Point-Write")

        opcode = int(value[0])

        # Minimal-ACK:
        # 0x80 = Response Code
        # <opcode>
        # 0x01 = Success
        self._last_response = bytes([0x80, opcode, 0x01])
        GLib.idle_add(self._emit_response)

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="", out_signature="")
    def StartNotify(self):
        self.notifying = True

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False


class FitnessMachineService(Service):
    def __init__(self, bus, index, path_base="/org/ble/ftms"):
        super().__init__(bus, index, FITNESS_MACHINE_SERVICE_UUID, primary=True, path_base=path_base)

        self.feature_char = FitnessMachineFeatureCharacteristic(bus, 0, self)
        self.rower_data_char = RowerDataCharacteristic(bus, 1, self)
        self.control_point_char = FitnessMachineControlPointCharacteristic(bus, 2, self)

        self.add_characteristic(self.feature_char)
        self.add_characteristic(self.rower_data_char)
        self.add_characteristic(self.control_point_char)


class DeviceInformationService(Service):
    def __init__(self, bus, index, path_base="/org/ble/ftms"):
        super().__init__(bus, index, DEVICE_INFO_SERVICE_UUID, primary=False, path_base=path_base)
        self.add_characteristic(StaticReadCharacteristic(bus, 0, MANUFACTURER_NAME_UUID, b"x-ski.ch", self))
        self.add_characteristic(StaticReadCharacteristic(bus, 1, MODEL_NUMBER_UUID, b"x-ski-v1", self))
        self.add_characteristic(StaticReadCharacteristic(bus, 2, FIRMWARE_REVISION_UUID, b"0.1-ftms", self))


class FTMSAdvertisement(dbus.service.Object):
    PATH = "/org/ble/ftms/advertisement0"

    def __init__(self, bus, local_name="x-ski FTMS"):
        self.bus = bus
        self.local_name = local_name
        super().__init__(bus, self.PATH)

    def get_path(self):
        return dbus.ObjectPath(self.PATH)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != ADVERTISING_IFACE:
            raise InvalidArgsException()

        return {
            "Type": "peripheral",
            "LocalName": self.local_name,
            "ServiceUUIDs": dbus.Array([FITNESS_MACHINE_SERVICE_UUID], signature="s"),
            "IncludeTxPower": dbus.Boolean(True),
        }

    @dbus.service.method(ADVERTISING_IFACE, in_signature="", out_signature="")
    def Release(self):
        print("FTMS advertisement released")


class BLEPowerServer:
    """
    Beibehaltener Klassenname für Kompatibilität mit BLEManager.
    Intern ist das jetzt ein FTMS-Rower-Server.
    """

    def __init__(self, adapter="hci0", local_name="x-ski FTMS"):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        self.adapter_path = f"/org/bluez/{adapter}"
        self.local_name = local_name

        self.app = Application(self.bus)
        self.ftms_service = FitnessMachineService(self.bus, 0)
        self.devinfo_service = DeviceInformationService(self.bus, 1)
        self.app.add_service(self.ftms_service)
        self.app.add_service(self.devinfo_service)

        self.ad = FTMSAdvertisement(self.bus, local_name=self.local_name)

        adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path)
        self.service_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
        self.ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)

        self.mainloop = None

    def start(self):
        self.service_manager.RegisterApplication(
            self.app.get_path(),
            {},
            reply_handler=lambda: print("✅ FTMS GATT application registered"),
            error_handler=lambda e: print(f"❌ Failed to register FTMS application: {e}")
        )
        self.ad_manager.RegisterAdvertisement(
            self.ad.get_path(),
            {},
            reply_handler=lambda: print(f"✅ FTMS advertisement registered ({self.local_name})"),
            error_handler=lambda e: print(f"❌ Failed to register FTMS advertisement: {e}")
        )

        self.mainloop = GLib.MainLoop()
        self.mainloop.run()

    def reset(self):
        self.ftms_service.rower_data_char.reset()

    def update_rower_metrics(
        self,
        *,
        stroke_rate_spm,
        stroke_count,
        total_distance_m,
        pace_s_per_500,
        avg_pace_s_per_500,
        power_w,
        avg_power_w,
        hr_bpm,
        elapsed_s,
        running,
    ):
        self.ftms_service.rower_data_char.set_metrics(
            stroke_rate_spm=stroke_rate_spm,
            stroke_count=stroke_count,
            total_distance_m=total_distance_m,
            pace_s_per_500=pace_s_per_500,
            avg_pace_s_per_500=avg_pace_s_per_500,
            power_w=power_w,
            avg_power_w=avg_power_w,
            hr_bpm=hr_bpm,
            elapsed_s=elapsed_s,
            running=running,
        )

    # Rückwärtskompatibilität
    def set_power(self, watts):
        self.update_rower_metrics(
            stroke_rate_spm=0,
            stroke_count=0,
            total_distance_m=0,
            pace_s_per_500=0,
            avg_pace_s_per_500=0,
            power_w=watts,
            avg_power_w=watts,
            hr_bpm=0,
            elapsed_s=0,
            running=False,
        )

    def set_cadence(self, rpm):
        self.update_rower_metrics(
            stroke_rate_spm=rpm,
            stroke_count=0,
            total_distance_m=0,
            pace_s_per_500=0,
            avg_pace_s_per_500=0,
            power_w=0,
            avg_power_w=0,
            hr_bpm=0,
            elapsed_s=0,
            running=False,
        )