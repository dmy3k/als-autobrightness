import dbus


class BrightnessControlDBus:
    def __init__(self) -> None:
        bus = dbus.SessionBus()
        proxy = bus.get_object(
            "org.kde.Solid.PowerManagement",
            "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
        )
        self.interface = dbus.Interface(
            proxy, "org.kde.Solid.PowerManagement.Actions.BrightnessControl"
        )

    @property
    def max_brightness(self):
        return int(self.interface.brightnessMax())

    @property
    def min_brightness(self):
        return int(self.interface.brightnessMin())

    @property
    def brightness(self):
        return int(self.interface.brightness())

    def set_brightness(self, v):
        self.interface.setBrightnessSilent(v)

    def connect_brightness_changed_signal(self, fn: callable):
        self.interface.connect_to_signal("brightnessChanged", fn)
