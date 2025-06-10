from autobrightness.services.screens import ScreensDbus, ScreenBrightnessDBus
from autobrightness.services.illuminance import SensorProxyDBus
from autobrightness.services.notifications import NotificationsDBus

import logging
import time
import dbus

from math import ceil, copysign as cpsign
from threading import Thread, Event


class AutoBrightnessService:
    def __init__(self) -> None:
        self.display: ScreenBrightnessDBus | None = None
        self.max_brightness = 0
        self.current_brightness = 0
        self.current_light_level = 0

        self.user_brightness_bias = 0
        self.inhibited_by_powerdevil = False
        self.anim_bright_target = None
        self.anim_step = 1

        self.logger = logging.getLogger(__name__)

        self.light_event = Event()
        self.stop_event = Event()
        self.anim_abort_event = Event()
        self.anim_thread = Thread(target=self.animate_brightness)

        self.screens_dbus = ScreensDbus()
        self.sensor_proxy_dbus = SensorProxyDBus()
        self.notif_dbus = NotificationsDBus()

        # Windows 11-style overlapping buckets for hysteresis
        # Each tuple: (lower_bound, upper_bound, brightness_percent)
        self.brightness_buckets = [
            (0, 10, 10),
            (5, 50, 20),
            (40, 300, 30),
            (150, 400, 40),
            (250, 650, 50),
            (450, 2000, 75),
            (1000, 10000, 100),
        ]

        # Start with brigtness close to 50%
        i = len(self.brightness_buckets) - 1
        while i >= 0:
            l, u, val = self.brightness_buckets[i]
            if val <= 50:
                self.current_bucket_idx = i
                break
            i -= 1

    def run(self):
        self.sensor_proxy_dbus.run()
        self.sensor_proxy_dbus.connect_props_changed_signal(
            self.handle_sensor_props_change
        )

        self.screens_dbus.on_internal_display_change = self.on_screens_change
        self.screens_dbus.run()

        self.notif_dbus.run()
        self.notif_dbus.connect_notif_action_signal(self.handle_brightness_bias_clear)

        self.anim_thread.start()

    def stop(self):
        self.sensor_proxy_dbus.stop()
        self.notif_dbus.stop()

        self.stop_event.set()
        self.anim_abort_event.set()
        self.light_event.set()

        if self.anim_thread.is_alive():
            self.anim_thread.join()

    def on_screens_change(self, display: ScreenBrightnessDBus):
        if display:
            self.display = display
            self.max_brightness = self.display.max_brightness
            self.current_brightness = self.display.brightness
            self.anim_step = self.max_brightness * 0.005
            self.display.connect_brightness_changed_signal(
                self.handle_brightness_change
            )
            self.report_light_level(self.sensor_proxy_dbus.light_level)
            self.logger.debug(
                f"Display '{self.display.label}' is enabled, max_brightness={self.max_brightness}"
            )
        else:
            self.display = None
            self.max_brightness = 0
            self.current_brightness = 0
            self.anim_step = 1

            if self.anim_bright_target is not None:
                self.anim_abort_event.set()
            self.light_event.set()
            self.logger.debug("Built-in display is disabled")

    def get_recommended_brightness(self, bias=0):
        if not self.max_brightness:
            return self.current_brightness

        lux = self.current_light_level
        idx = self.current_bucket_idx

        # Move up if lux >= upper_bound of current bucket
        while (
            idx < len(self.brightness_buckets) - 1
            and lux >= self.brightness_buckets[idx][1]
        ):
            idx += 1
        # Move down if lux < lower_bound of current bucket
        while idx > 0 and lux < self.brightness_buckets[idx][0]:
            idx -= 1

        self.current_bucket_idx = idx
        percent = self.brightness_buckets[idx][2]
        value = round(self.max_brightness * percent / 100)
        value = max(min(value + bias, self.max_brightness), 0)
        return value

    def report_light_level(self, value: int):
        self.current_light_level = value

        if self.anim_bright_target is not None:
            # abort any ongoing brigtness animation
            # as target brightness bucket might be changed
            self.anim_abort_event.set()

        self.light_event.set()
        self.logger.debug(f"light_level={value}")

    def wait_recommended_brightness(self):
        while not self.stop_event.is_set():
            signaled = self.light_event.wait(60)
            self.light_event.clear()

            if not self.display:
                continue

            recomm_brightness = self.current_brightness
            bucket_changed = True

            # debounce frequent bucket changes
            while bucket_changed:
                recomm_brightness = self.get_recommended_brightness(
                    bias=self.user_brightness_bias
                )
                bucket_changed = recomm_brightness != self.current_brightness

                if signaled and bucket_changed and self.anim_bright_target is None:
                    if self.light_event.wait(1.0):
                        self.light_event.clear()
                        self.logger.debug(f"debounced")
                        continue

                break

            self.logger.debug(f"{recomm_brightness=}, {signaled=}, {bucket_changed=}")

            if self.anim_bright_target is not None:
                # resume interrupted brightness animation
                return recomm_brightness

            if bucket_changed and not self.inhibited_by_powerdevil:
                return recomm_brightness

        return self.current_brightness

    def animate_brightness(self):
        while not self.stop_event.is_set():
            try:
                target = self.wait_recommended_brightness()

                start = self.current_brightness
                delta = target - start
                frame_count = ceil(abs(delta) / self.anim_step)
                if frame_count < 1:
                    continue

                self.anim_bright_target = target

                self.logger.debug(f"{start=}, {target=}, {frame_count=}")
                self.anim_abort_event.clear()

                for i in range(1, frame_count + 1):
                    if self.anim_abort_event.is_set() or self.stop_event.is_set():
                        self.logger.debug(f"aborted animation")
                        break

                    b = start + round(i * cpsign(self.anim_step, delta))

                    if (delta > 0 and b >= target) or (delta < 0 and b <= target):
                        self.display.set_brightness(target)
                        break
                    else:
                        self.display.set_brightness(b)
                        time.sleep(0.05)  # 20 fps

            except dbus.exceptions.DBusException as e:
                self.logger.exception(e)
                time.sleep(1.0)

    def handle_brightness_bias_clear(self, action, *args):
        if action == "undo":
            self.user_brightness_bias = 0
            if self.display:
                target = self.get_recommended_brightness()
                self.display.set_brightness(target)
            self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

    def handle_brightness_change(self, source, value, *args, **kw):
        b = int(value["Brightness"]) if "Brightness" in value else None
        if b is None:
            return

        if self.anim_bright_target is None:
            prev_bias = self.user_brightness_bias
            self.user_brightness_bias = b - self.get_recommended_brightness()

            # heuristics around powerdevil behaviour dimming screen on idle timeout
            # do not show notifications when dimming takes place
            # https://github.com/KDE/powerdevil/blob/bfa2cf691acf37b60541cc61ae11e0fad7c0f816/daemon/actions/bundled/dimdisplay.cpp#L74
            brightness_ratio = (
                round(b / self.current_brightness, 2) if self.current_brightness else 0
            )

            if brightness_ratio == 0.3 and self.user_brightness_bias < prev_bias:
                self.inhibited_by_powerdevil = True
                self.logger.debug(f"inhibited_by_powerdevil=True")

            elif brightness_ratio == 3.33 and self.user_brightness_bias > prev_bias:
                self.inhibited_by_powerdevil = False
                self.logger.debug(f"inhibited_by_powerdevil=False")

            elif self.user_brightness_bias != prev_bias:
                p = self.user_brightness_bias / self.max_brightness
                self.notif_dbus.notify(
                    "Brightness set manually",
                    f"Adaptive brightness curve is offset by {p:+.0%}",
                )
                self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

        elif b == self.anim_bright_target:
            self.anim_bright_target = None
            self.logger.debug("animate_brightness: end")

        self.current_brightness = b

    def handle_sensor_props_change(self, source, changedProps, invalidatedProps, **kw):
        if source == "net.hadess.SensorProxy" and self.display:
            if "LightLevel" in changedProps:
                val = int(changedProps["LightLevel"])
                self.report_light_level(val)
