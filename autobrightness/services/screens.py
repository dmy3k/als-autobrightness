import dbus
from autobrightness.services.abstract import DBusService
import glob


class LoginSessDbus(DBusService):
    def __init__(self) -> None:
        super().__init__(dbus.SystemBus)
        self.max_brightness = 0
        self.device_name = None

    def run(self):
        self.proxy = self.try_get_object(
            "org.freedesktop.login1",
            "/org/freedesktop/login1/session/auto",
        )
        self.iface = dbus.Interface(self.proxy, "org.freedesktop.login1.Session")

        p = glob.glob("/sys/class/backlight/*/max_brightness")[0]
        self.device_name = p.rsplit("/", 2)[1]
        with open(p, "r") as fh:
            self.max_brightness = int(fh.read().strip())

    def set_brightness(self, value):
        if int(value) >= 0:
            self.iface.SetBrightness("backlight", self.device_name, value)

    def get_brightness(self):
        with open(f"/sys/class/backlight/{self.device_name}/brightness") as fh:
            return int(fh.read().strip())


class ScreensDbus(DBusService):
    def __init__(self) -> None:
        super().__init__(dbus.SessionBus)
        self.login1 = LoginSessDbus()
        self.max_brightness = 100
        self.brightness_step = 1
        self._cached_brightness = None

    def run(self):
        self.proxy = self.try_get_object(
            "org.gnome.SettingsDaemon.Power",
            "/org/gnome/SettingsDaemon/Power",
        )
        self.proxy.connect_to_signal(
            "PropertiesChanged", self._on_brightness_change, sender_keyword="sender"
        )
        self.props = dbus.Interface(self.proxy, "org.freedesktop.DBus.Properties")

        self.login1.run()
        self.max_brightness = self.login1.max_brightness

    @property
    def brightness(self):
        # return int(self.props.Set("org.gnome.SettingsDaemon.Power.Screen", "Brightness"))
        if self._cached_brightness is None:
            self._cached_brightness = self.login1.get_brightness()
        return self._cached_brightness

    def set_brightness(self, value):
        # self.props.Set("org.gnome.SettingsDaemon.Power.Screen", "Brightness", value)
        self.login1.set_brightness(value)

    def _on_brightness_change(self, source, value, *args, **kw):
        if source == "org.gnome.SettingsDaemon.Power.Screen":
            self._cached_brightness = None

    def connect_props_changed_signal(self, fn: callable):
        self.proxy.connect_to_signal("PropertiesChanged", fn, sender_keyword="sender")
