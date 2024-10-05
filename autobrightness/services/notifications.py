import dbus
from threading import Timer
from functools import partial


class NotificationsDBus:
    def __init__(self) -> None:
        self.interface: dbus.Interface | None = None
        self.notif_id: int = 0
        self.timer: Timer | None = None

    def run(self):
        bus = dbus.SessionBus()
        notif_proxy = bus.get_object(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
        )
        self.interface = dbus.Interface(notif_proxy, "org.freedesktop.Notifications")

    def stop(self):
        if self.notif_id:
            self.interface.CloseNotification(self.notif_id)

        if self.timer and not self.timer.finished.is_set():
            self.timer.cancel()

    def _validate(self, fn, notif_id, *args):
        if int(notif_id) == self.notif_id:
            self.notif_id = 0
            fn()

    def connect_notif_closed_signal(self, fn):
        bound_fn = partial(self._validate, fn)
        self.interface.connect_to_signal("NotificationClosed", bound_fn)

    def notify(self, title, body):
        if self.timer and not self.timer.finished.is_set():
            self.timer.cancel()

        self.timer = Timer(1.0, self._notify, args=[title, body])
        self.timer.start()

    def _notify(self, title, body):
        self.notif_id = self.interface.Notify(
            "autobrightness.service",
            self.notif_id,
            "",
            title,
            body,
            [],
            {"urgency": 1, "resident": True},
            3000,
        )
