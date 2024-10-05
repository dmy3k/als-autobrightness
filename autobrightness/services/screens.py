import logging
import dbus
import weakref


class ScreenBrightnessDBus:
    def __init__(self, name: str, mngr: "ScreensDbus"):
        self.name = name
        self.mngr = mngr
        self.bus = dbus.SessionBus()

        self.proxy = self.bus.get_object(
            "org.kde.Solid.PowerManagement",
            f"/org/kde/ScreenBrightness/{self.name}",
        )

        self.propsIface = dbus.Interface(self.proxy, "org.freedesktop.DBus.Properties")
        self.brightnessIface = dbus.Interface(
            self.proxy, "org.kde.ScreenBrightness.Display"
        )

        self.max_brightness = int(
            self.proxy.Get("org.kde.ScreenBrightness.Display", "MaxBrightness")
        )
        self.is_internal = bool(
            self.proxy.Get("org.kde.ScreenBrightness.Display", "IsInternal")
        )

    @property
    def brightness(self):
        v = self.proxy.Get("org.kde.ScreenBrightness.Display", "Brightness")
        return int(v)

    def set_brightness(self, value: int):
        try:
            self.brightnessIface.SetBrightness(value, 1)
        except dbus.exceptions.DBusException as e:
            if (
                e.get_dbus_name() == "org.freedesktop.DBus.Error.UnknownObject"
                and self.mngr is not None
            ):
                self.mngr.discover()
            else:
                raise

    def connect_brightness_changed_signal(self, fn: callable):
        self.propsIface.connect_to_signal("PropertiesChanged", fn)


class ScreensDbus:
    def __init__(self) -> None:
        self._display: ScreenBrightnessDBus | None = None
        self.on_internal_display_change: callable | None = None

        self.logger = logging.getLogger(__name__)
        ch = logging.StreamHandler()
        self.logger.addHandler(ch)
        self.logger.setLevel(logging.INFO)

    def run(self):
        self.bus = dbus.SessionBus()
        self.proxy = self.bus.get_object(
            "org.kde.Solid.PowerManagement",
            "/org/kde/ScreenBrightness",
        )
        self.discover()

        self.interface = dbus.Interface(self.proxy, "org.kde.ScreenBrightness")
        self.interface.connect_to_signal("DisplayAdded", self.on_display_added)
        self.interface.connect_to_signal("DisplayRemoved", self.on_display_removed)

    def discover(self):
        all_names = self.proxy.Get("org.kde.ScreenBrightness", "DisplaysDBusNames")
        for name in all_names:
            displ = ScreenBrightnessDBus(str(name), weakref.proxy(self))
            if displ.is_internal:
                self.internal_display = displ
                break
        else:
            self.internal_display = None

    @property
    def internal_display(self):
        return self._display

    @internal_display.setter
    def internal_display(self, value: ScreenBrightnessDBus | None):
        self._display = value
        try:
            if callable(self.on_internal_display_change):
                self.on_internal_display_change(value)
        except Exception as e:
            self.logger.exception(e)

    def on_display_added(self, value, **kw):
        if not self.internal_display:
            added_displ = ScreenBrightnessDBus(str(value), weakref.proxy(self))
            if added_displ.is_internal:
                self.internal_display = added_displ

    def on_display_removed(self, value, **kw):
        name = str(value)
        if self.internal_display and name == self.internal_display.name:
            self.internal_display = None
