from collections import namedtuple
from autobrightness.services.screens import ScreensDbus, ScreenBrightnessDBus
from autobrightness.services.illuminance import SensorProxyDBus
from autobrightness.services.notifications import NotificationsDBus

import logging
import time
import dbus

from math import ceil, copysign as cpsign
from threading import Thread, Event


Reading = namedtuple("Reading", ["ts", "val"])


class AutoBrightnessService:
    def __init__(self) -> None:
        # brightness curve
        self.brightness_adjust = 0.75
        self.brightness_power = 1 / (2**self.brightness_adjust)

        # illuminance (lux) corresponding to full brightness
        self.max_illuminance = 2114

        self.display: ScreenBrightnessDBus | None = None
        self.max_brightness = 0
        self.min_brightness = 0
        self.current_brightness = 0

        self.fps = 20
        self.avg_period = 10.0
        self.light_timeout = 1.0

        self.user_brightness_bias = 0
        self.inhibited_by_powerdevil = False
        self.anim_bright_target = None

        self.lights = []
        self.twa = -1

        self.logger = logging.getLogger(__name__)

        self.light_event = Event()
        self.stop_event = Event()
        self.anim_thread = Thread(target=self.animate_brightness)

        self.screens_dbus = ScreensDbus()
        self.sensor_proxy_dbus = SensorProxyDBus()
        self.notif_dbus = NotificationsDBus()

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

        self.report_light_level(self.sensor_proxy_dbus.light_level)

    def stop(self):
        self.sensor_proxy_dbus.stop()
        self.notif_dbus.stop()

        self.stop_event.set()
        self.light_event.set()

        if self.anim_thread.is_alive():
            self.anim_thread.join()

    def on_screens_change(self, display: ScreenBrightnessDBus):
        if display:
            self.display = display
            self.max_brightness = self.display.max_brightness
            self.min_brightness = round(self.display.max_brightness * 0.05)
            self.current_brightness = self.display.brightness
            self.display.connect_brightness_changed_signal(
                self.handle_brightness_change
            )
            self.logger.debug("Built-in display is enabled")
        else:
            self.display = None
            self.max_brightness = 0
            self.min_brightness = 0
            self.current_brightness = 0

            self.lights = []
            self.light_event.set()
            self.logger.debug("Built-in display is disabled")

    @property
    def brightness_range(self):
        return self.max_brightness - self.min_brightness

    @property
    def step(self):
        return ceil(self.brightness_range / (self.fps * self.avg_period))

    @property
    def brightness_threshold_delta(self):
        return round(self.brightness_range * 0.05)

    def get_recommended_brightness(self, bias=0):
        if not self.brightness_range or self.twa < 0:
            return self.current_brightness

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

    def report_light_level(self, value: int):
        now = time.time()

        if self.lights and now - self.lights[-1].ts >= self.light_timeout:
            value = self.lights[-1].val

        self.lights.append(Reading(ts=now, val=value))

        ref_t = now - self.avg_period
        self.lights = [x for x in self.lights if x.ts > ref_t] or self.lights[-1:]
        prev_twa = self.twa
        self.twa = round(self.calc_time_weighted_avg())

        if abs(self.twa - prev_twa) > 1 or prev_twa < 0:
            self.light_event.set()

        self.logger.debug(f"light_level={value}, light_avg={self.twa}")

    def animate_brightness(self):
        while not self.stop_event.is_set():
            try:
                avg_changing = self.lights and self.twa != self.lights[-1].val
                timeout = self.light_timeout if avg_changing else 30.0

                signaled = self.light_event.wait(timeout)
                self.light_event.clear()

                if self.twa < 0 or self.inhibited_by_powerdevil:
                    continue

                if not signaled:
                    self.report_light_level(self.sensor_proxy_dbus.light_level)

                target = self.get_recommended_brightness(bias=self.user_brightness_bias)
                start = self.current_brightness
                delta = target - start

                if abs(delta) > self.brightness_threshold_delta:
                    frames = ceil(abs(delta) / self.step)
                    frame_time = round(1 / min(frames, self.fps), 2)
                    self.anim_bright_target = target

                    self.logger.debug(
                        f"animate_brightness: {start=}, {target=}, {frames=}, {frame_time=}"
                    )

                    for i in range(1, frames + 1):
                        if self.light_event.is_set() or self.stop_event.is_set():
                            self.anim_bright_target = None
                            break

                        b = start + round(i * cpsign(self.step, delta))

                        if (delta > 0 and b >= target) or (delta < 0 and b <= target):
                            self.display.set_brightness(target)
                            break
                        else:
                            self.display.set_brightness(b)
                            time.sleep(frame_time)
            except dbus.exceptions.DBusException as e:
                self.logger.exception(e)
                time.sleep(self.light_timeout)

    def handle_brightness_bias_clear(self, action, *args):
        if action == "undo":
            self.user_brightness_bias = 0
            target = self.get_recommended_brightness()
            self.display.set_brightness(target)
            self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

    def handle_brightness_change(self, source, value, *args, **kw):
        b = int(value["Brightness"]) if "Brightness" in value else None
        if b is None:
            return

        if self.anim_bright_target and b == self.anim_bright_target:
            self.anim_bright_target = None
            self.logger.debug("animate_brightness: end")

        if not self.anim_bright_target:
            prev_bias = self.user_brightness_bias
            self.user_brightness_bias = b - self.get_recommended_brightness()

            # heuristics around powerdevil behaviour dimming screen on idle timeout
            # do not show notifications when dimming takes place
            # https://github.com/KDE/powerdevil/blob/bfa2cf691acf37b60541cc61ae11e0fad7c0f816/daemon/actions/bundled/dimdisplay.cpp#L74
            brightness_ratio = round(b / self.current_brightness, 2)

            if brightness_ratio == 0.3 and self.user_brightness_bias < prev_bias:
                self.inhibited_by_powerdevil = True
                self.logger.debug(f"inhibited_by_powerdevil=True")

            elif brightness_ratio == 3.33 and self.user_brightness_bias > prev_bias:
                self.inhibited_by_powerdevil = False
                self.logger.debug(f"inhibited_by_powerdevil=False")

            elif abs(self.user_brightness_bias) >= self.brightness_threshold_delta:
                p = self.user_brightness_bias / self.max_brightness
                self.notif_dbus.notify(
                    "Brightness set manually",
                    f"Adaptive brightness curve is offset by {p:+.0%}",
                )
                self.logger.debug(f"user_brightness_bias={self.user_brightness_bias}")

        self.current_brightness = b

    def handle_sensor_props_change(self, source, changedProps, invalidatedProps, **kw):
        if source == "net.hadess.SensorProxy" and self.display:
            if "LightLevel" in changedProps:
                val = int(changedProps["LightLevel"])
                self.report_light_level(val)
