import dbus
from threading import Timer
from functools import partial
import time
from autobrightness.services.abstract import DBusService


class NotificationsDBus(DBusService):
    def __init__(self) -> None:
        super().__init__(dbus.SessionBus)
        self.interface: dbus.Interface | None = None
        self.notif_id: int = 0
        self.notif_timeout: int = 5
        self.notif_shown_at: float = 0
        self.timer: Timer | None = None

    def run(self):
        proxy = self.try_get_object(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
        )
        self.interface = dbus.Interface(proxy, "org.freedesktop.Notifications")

    def stop(self):
        if self.notif_id:
            self.interface.CloseNotification(self.notif_id)

        if self.timer and not self.timer.finished.is_set():
            self.timer.cancel()

    def _validate(self, fn, notif_id, *args):
        if int(notif_id) == self.notif_id:
            self.notif_id = 0
            fn(*args)

    def connect_notif_closed_signal(self, fn):
        bound_fn = partial(self._validate, fn)
        self.interface.connect_to_signal("NotificationClosed", bound_fn)

    def connect_notif_action_signal(self, fn):
        bound_fn = partial(self._validate, fn)
        self.interface.connect_to_signal("ActionInvoked", bound_fn)

    def notify(self, title, body):
        if self.timer and not self.timer.finished.is_set():
            self.timer.cancel()

        self.timer = Timer(1.0, self._notify, args=[title, body])
        self.timer.start()

    def _notify(self, title, body):
        if self.notif_id and time.time() > self.notif_shown_at + self.notif_timeout:
            self.interface.CloseNotification(self.notif_id)

        self.notif_id = self.interface.Notify(
            "autobrightness.service",
            self.notif_id,
            "",
            title,
            body,
            ["undo", "Undo"],
            {"urgency": 1, "resident": False},
            self.notif_timeout * 1000,
        )
        self.notif_shown_at = time.time()
