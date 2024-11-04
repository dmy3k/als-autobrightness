import dbus

from autobrightness.services.abstract import DBusService


class SensorProxyDBus(DBusService):
    def __init__(self) -> None:
        super().__init__(dbus.SystemBus)
        self.props: dbus.Interface | None = None
        self.iface: dbus.Interface | None = None
        self.proxy = None

    def run(self):
        self.proxy = self.try_get_object(
            "net.hadess.SensorProxy", "/net/hadess/SensorProxy"
        )
        self.props = dbus.Interface(self.proxy, "org.freedesktop.DBus.Properties")
        self.iface = dbus.Interface(self.proxy, "net.hadess.SensorProxy")

        if not self.has_ambient_light:
            raise RuntimeError("Ambient Light Sensor not available")

        self.iface.ClaimLight()

    def stop(self):
        if self.iface:
            self.iface.ReleaseLight()

    @property
    def has_ambient_light(self):
        v = self.props.Get("net.hadess.SensorProxy", "HasAmbientLight")
        return bool(v)

    def connect_props_changed_signal(self, fn: callable):
        self.props.connect_to_signal("PropertiesChanged", fn, sender_keyword="sender")
