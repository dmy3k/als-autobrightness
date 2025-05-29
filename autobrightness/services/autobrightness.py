from collections import namedtuple
from autobrightness.services.screens import ScreensDbus
from autobrightness.services.illuminance import SensorProxyDBus
from autobrightness.services.notifications import NotificationsDBus

import logging
import time
import dbus
from gi.repository import Gio

from math import ceil, copysign as cpsign
from threading import Thread, Event


Reading = namedtuple("Reading", ["ts", "val"])


class AutoBrightnessService:
    def __init__(self) -> None:
        # brightness curve
        self.brightness_adjust = 0.75
        self.brightness_power = 1 / (2**self.brightness_adjust)

        # illuminance (lux) corresponding to max brightness
        self.max_illuminance = 2114

        self.light_to_brightness_map = []

        self.avg_period = 3.0

        self.user_brightness_bias = 0
        self.idle_brightness_percent = 0
        self.idle_dimmed = False
        self.anim_bright_target = None

        self.lights: list[Reading] = []
        self.twa = -1
        self.moving_window_start_at = time.time()
        self.event_timeout_count = 0

        self.logger = logging.getLogger(__name__)

        self.light_event = Event()
        self.stop_event = Event()
        self.brightness_event = Event()
        self.anim_thread = Thread(target=self.animate_brightness)

        self.screens_dbus = ScreensDbus()
        self.sensor_proxy_dbus = SensorProxyDBus()
        self.notif_dbus = NotificationsDBus()

    def run(self):
        self.sensor_proxy_dbus.run()
        self.sensor_proxy_dbus.connect_props_changed_signal(
            self.handle_sensor_props_change
        )

        self.screens_dbus.run()
        self.screens_dbus.connect_props_changed_signal(self.handle_brightness_change)
        self.brightness_threshold_delta = round(self.screens_dbus.max_brightness * 0.04)

        self.notif_dbus.run()
        self.notif_dbus.connect_notif_action_signal(self.handle_brightness_bias_clear)

        self.anim_thread.start()
        self.report_light_level(self.sensor_proxy_dbus.light_level)

        step = round(self.screens_dbus.max_brightness * 0.02)
        min_b = step * 4
        self.light_to_brightness_map = [
            (x, self.brightness_to_light(x))
            for x in range(min_b, (self.screens_dbus.max_brightness + step), step)
        ]
        self.logger.debug(f"{self.light_to_brightness_map=}")

        pwr_settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.power")

        if pwr_settings["idle-dim"]:
            self.idle_brightness_percent = pwr_settings["idle-brightness"]

        if pwr_settings["ambient-enabled"]:
            pwr_settings["ambient-enabled"] = False
            self.logger.debug('Setting "ambient-enabled" to False')

    def stop(self):
        self.sensor_proxy_dbus.stop()
        self.notif_dbus.stop()

        self.stop_event.set()
        self.light_event.set()

        if self.anim_thread.is_alive():
            self.anim_thread.join()

    def get_recommended_brightness(self, bias=0):
        value = self.screens_dbus.brightness

        if not self.screens_dbus.max_brightness or self.twa < 0:
            return value

        for br, illum in self.light_to_brightness_map:
            if self.twa <= illum:
                value = br
                break
        else:
            value = self.screens_dbus.max_brightness

        return min(value + bias, self.screens_dbus.max_brightness)

    def brightness_to_light(self, brightness: int):
        adj_ratio = brightness / self.screens_dbus.max_brightness
        ratio = adj_ratio ** (1 / self.brightness_power)
        light_level = round(self.max_illuminance * ratio)
        return max(min(light_level, self.max_illuminance), 0)

    def report_light_level(self, value: int):
        self.lights.append(Reading(ts=time.time(), val=value))
        self.logger.debug(f"light_level={value}")

    def calc_time_weighted_avg(self):
        value = 0

        if len(self.lights) > 1:
            weighted_sums = []
            for i, x in enumerate(self.lights):
                if i > 0:
                    prev = self.lights[i - 1]
                    weighted_sums.append(((x.val + prev.val) / 2) * (x.ts - prev.ts))

            t_all = [x.ts for x in self.lights]
            value = sum(weighted_sums) / (max(t_all) - min(t_all))
        elif self.lights:
            value = self.lights[0].val
        else:
            value = self.sensor_proxy_dbus.light_level

        return round(value)

    def wait_recommended_brightness(self):
        signaled = self.light_event.wait(self.light_event_timeout)
        self.light_event.clear()

        if not signaled:
            # window timeout reached
            self.report_light_level(self.sensor_proxy_dbus.light_level)

        self.twa = self.calc_time_weighted_avg()
        recomm_brightness = self.get_recommended_brightness(
            bias=self.user_brightness_bias
        )
        bright_diff = abs(recomm_brightness - self.screens_dbus.brightness)
        updated = bright_diff > self.brightness_threshold_delta and not self.idle_dimmed

        if not signaled or (updated and self.event_timeout_count > 1):
            t = self.lights[-1].ts - self.avg_period / 2
            self.lights = [Reading(ts=t, val=self.twa)]
            self.moving_window_start_at = time.time()
            self.event_timeout_count = 1 if updated else self.event_timeout_count + 1

        self.logger.debug(
            f"twa={self.twa}, {bright_diff=}, {recomm_brightness=}, {signaled=}, {updated=}"
        )

        if updated:
            return recomm_brightness

    @property
    def light_event_timeout(self):
        if self.screens_dbus.brightness < 0:  # display is turned off, pause
            return 60

        timeout = min(60, self.avg_period * self.event_timeout_count)
        return max(0.01, self.moving_window_start_at + timeout - time.time())

    def animate_brightness(self):
        while not self.stop_event.is_set():
            try:
                target = self.wait_recommended_brightness()
                if target is None:
                    continue

                start = self.screens_dbus.brightness
                delta = target - start

                if abs(delta) >= self.brightness_threshold_delta:
                    step = self.screens_dbus.brightness_step
                    frame_count = ceil(abs(delta) / step)
                    frame_time = max(round(self.avg_period / frame_count, 2), 0.02)

                    self.logger.debug(
                        f"{start=}, {target=}, {frame_count=}, {frame_time=}"
                    )

                    for i in range(1, frame_count + 1):
                        if self.light_event.is_set() or self.stop_event.is_set():
                            self.anim_bright_target = None
                            break

                        b = start + round(i * cpsign(step, delta))
                        self.anim_bright_target = b

                        if (delta > 0 and b >= target) or (delta < 0 and b <= target):
                            self.screens_dbus.set_brightness(target)
                            self.anim_bright_target = None
                            self.logger.debug(f"end_animation")
                            break
                        else:
                            self.screens_dbus.set_brightness(b)

                            signaled = self.brightness_event.wait(frame_time)
                            if not signaled:
                                self.logger.debug(f"timed out waiting reply from dbus")
                                continue

                            time.sleep(frame_time)

            except dbus.exceptions.DBusException as e:
                self.logger.exception(e)
                time.sleep(1.0)

    def handle_brightness_bias_clear(self, action, *args):
        if action == "undo":
            self.user_brightness_bias = 0
            self.light_event.set()
            self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

    def handle_brightness_change(self, source, value, *args, **kw):
        if source != "org.gnome.SettingsDaemon.Power.Screen":
            return

        percent = int(value["Brightness"]) if "Brightness" in value else None
        if percent is None or percent < 0:
            return

        current_value = self.screens_dbus.brightness

        if self.anim_bright_target and current_value == self.anim_bright_target:
            self.brightness_event.set()

        elif not self.anim_bright_target:
            recommended_brightness = self.get_recommended_brightness()

            # skip notifications when dimming takes place due to idle timeout
            if (
                not self.idle_dimmed
                and recommended_brightness > current_value
                and self.idle_brightness_percent
                and percent == self.idle_brightness_percent
            ):
                self.idle_dimmed = True
                self.logger.debug("dim-idle")

            elif (
                self.idle_dimmed
                and self.idle_brightness_percent
                and percent > self.idle_brightness_percent
            ):
                self.idle_dimmed = False
                self.logger.debug("undim-idle")

            elif current_value - recommended_brightness != self.user_brightness_bias:
                self.user_brightness_bias = current_value - recommended_brightness

                if abs(self.user_brightness_bias) >= self.brightness_threshold_delta:
                    p = self.user_brightness_bias / self.screens_dbus.max_brightness
                    self.notif_dbus.notify(
                        "Brightness set manually",
                        f"Adaptive brightness curve is offset by {p:+.0%}",
                    )
                    self.logger.debug(
                        f"user_brightness_bias={self.user_brightness_bias}"
                    )

    def handle_sensor_props_change(self, source, changedProps, invalidatedProps, **kw):
        if source == "net.hadess.SensorProxy" and "LightLevel" in changedProps:
            if self.screens_dbus.brightness < 0:
                self.logger.debug("built-in display is disabled")
                return

            val = int(changedProps["LightLevel"])
            self.report_light_level(val)
            self.light_event.set()
