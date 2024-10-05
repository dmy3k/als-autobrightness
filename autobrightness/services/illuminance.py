import dbus


class SensorProxyDBus:
    def __init__(self) -> None:
        bus = dbus.SystemBus()
        proxy = bus.get_object("net.hadess.SensorProxy", "/net/hadess/SensorProxy")

        self.props = dbus.Interface(proxy, "org.freedesktop.DBus.Properties")
        self.iface = dbus.Interface(proxy, "net.hadess.SensorProxy")
        self.iface.ClaimLight()

    def dispose(self):
        self.iface.ReleaseLight()

    def connect_props_changed_signal(self, fn: callable):
        self.props.connect_to_signal("PropertiesChanged", fn, sender_keyword="sender")
