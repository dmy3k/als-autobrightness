from functools import cached_property
import logging
from typing import Union
import dbus
import time


class DBusService:
    def __init__(self, dbus_class: Union[dbus.SystemBus, dbus.SessionBus]) -> None:
        self.dbus_class = dbus_class
        self.logger = logging.getLogger(__name__)

    @cached_property
    def bus(self):
        return self.dbus_class()

    def try_get_object(self, name: str, path: str):
        while True:
            try:
                return self.bus.get_object(name, path)
            except dbus.exceptions.DBusException as e:
                if e.get_dbus_name() == "org.freedesktop.DBus.Error.ServiceUnknown":
                    self.logger.info(f"Waiting for {name} to appear")
                    time.sleep(1)
                else:
                    raise
