from collections import namedtuple
from autobrightness.services.brightness import BrightnessControlDBus
from autobrightness.services.illuminance import SensorProxyDBus
from autobrightness.services.notifications import NotificationsDBus

import logging
import time

from math import ceil, copysign as cpsign
from threading import Thread, Event

Reading = namedtuple("Reading", ["ts", "val"])


class AutoBrightnessService:
    def __init__(self) -> None:
        self.brightness_dbus = BrightnessControlDBus()
        self.brightness_dbus.connect_brightness_changed_signal(
            self.handle_brightness_change
        )

        self.sensor_proxy_dbus = SensorProxyDBus()
        self.sensor_proxy_dbus.connect_props_changed_signal(
            self.handle_sensor_props_change
        )
        self.notif_dbus = NotificationsDBus()
        self.notif_dbus.connect_notif_closed_signal(self.handle_brightness_bias_clear)

        # brightness curve
        self.brightness_adjust = 0.75
        self.brightness_power = 1 / (2**self.brightness_adjust)

        # illuminance (lux) corresponding to full brightness
        self.max_illuminance = 2114

        self.max_brightness = self.brightness_dbus.max_brightness
        self.min_brightness = round(self.brightness_dbus.max_brightness * 0.1)
        self.current_brightness = self.brightness_dbus.brightness

        self.fps = 40
        self.brightness_range = self.max_brightness - self.min_brightness
        self.step = ceil(self.brightness_range / 100)
        self.threshold_delta = round(self.brightness_range * 0.05)

        self.user_brightness_bias = 0
        self.anim_bright_target = None

        self.lights = []
        self.twa = -1

        self.avg_period = 10.0
        self.light_timeout = 5.0

        self.logger = logging.getLogger(__name__)

        ch = logging.StreamHandler()
        self.logger.addHandler(ch)
        self.logger.setLevel(logging.INFO)

        self.light_event = Event()
        self.stop_event = Event()
        self.anim_thread = Thread(target=self.animate_brightness)
        self.anim_thread.start()

    def get_recommended_brightness(self, bias=0):
        ratio = self.twa / self.max_illuminance
        adjusted_ratio = ratio**self.brightness_power
        v = round(adjusted_ratio * self.brightness_range + self.min_brightness) + bias
        return max(min(v, self.max_brightness), self.min_brightness)

    def calc_time_weighted_avg(self):
        if len(self.lights) > 1:
            weighted_sums = []
            for i, x in enumerate(self.lights):
                if i > 0:
                    prev = self.lights[i - 1]
                    weighted_sums.append(((x.val + prev.val) / 2) * (x.ts - prev.ts))

            t_all = [x.ts for x in self.lights]
            return sum(weighted_sums) / (max(t_all) - min(t_all))
        else:
            return self.lights[0].val

    def report_light_level(self, value=None):
        now = time.time()

        if value:
            self.lights.append(Reading(ts=now, val=value))
        elif self.lights and now - self.lights[-1].ts > self.light_timeout:
            self.lights = [Reading(ts=now, val=self.lights[-1].val)]
            self.logger.debug("light_timeout")
        else:
            return

        ref_t = now - self.avg_period
        self.lights = [x for x in self.lights if x.ts > ref_t] or self.lights[-1:]
        next_twa = round(self.calc_time_weighted_avg())
        twa_diff = abs(next_twa - self.twa)
        self.twa = next_twa

        if twa_diff > 1:
            self.light_event.set()

        self.logger.debug(f"light_level={value}, light_avg={self.twa}")

    def animate_brightness(self):
        while not self.stop_event.is_set():
            signaled = self.light_event.wait(self.light_timeout)
            self.light_event.clear()

            if self.twa < 0:
                continue

            is_dynamic_light = len(self.lights) > 1

            if not signaled and is_dynamic_light:
                self.report_light_level()
                continue

            target = self.get_recommended_brightness(bias=self.user_brightness_bias)
            start = self.current_brightness
            delta = target - start

            step_time = 1 / self.fps if is_dynamic_light else 0.1

            if abs(delta) > self.threshold_delta:
                steps = ceil(abs(delta) / self.step)

                if steps:
                    self.logger.debug(
                        f"animate_brightness: {start=}, {target=}, {delta=}, {steps=}"
                    )
                    self.anim_bright_target = target

                for i in range(1, steps + 1):
                    if self.light_event.is_set():
                        break

                    b = start + round(i * cpsign(self.step, delta))

                    if (delta > 0 and b >= target) or (delta < 0 and b <= target):
                        self.brightness_dbus.set_brightness(target)
                        time.sleep(step_time)
                        break
                    else:
                        self.brightness_dbus.set_brightness(b)
                        time.sleep(step_time)

    def handle_brightness_bias_clear(self):
        self.user_brightness_bias = 0
        target = self.get_recommended_brightness()
        self.brightness_dbus.set_brightness(target)
        self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

    def handle_brightness_change(self, value, **kw):
        b = int(value)

        if not self.anim_bright_target:
            unbiased_target = self.get_recommended_brightness()
            self.user_brightness_bias = b - unbiased_target

            if self.user_brightness_bias:
                p = self.user_brightness_bias / self.max_brightness
                self.notif_dbus.notify(
                    "Brightness set manually",
                    f"Automatic brightness curve will be offset by {p:+.0%}. Close notification to revert",
                )
                self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

        if self.anim_bright_target and b == self.anim_bright_target:
            self.anim_bright_target = None
            self.logger.debug("animate_brightness: end")

        self.current_brightness = b

    def handle_sensor_props_change(self, source, changedProps, invalidatedProps, **kw):
        if source == "net.hadess.SensorProxy":
            if "LightLevel" in changedProps:
                val = int(changedProps["LightLevel"])
                self.report_light_level(val)

    def dispose(self):
        self.sensor_proxy_dbus.dispose()
        self.notif_dbus.dispose()

        self.stop_event.set()
        self.light_event.set()
        self.anim_thread.join()
