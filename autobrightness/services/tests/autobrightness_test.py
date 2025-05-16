import unittest
from unittest.mock import Mock
import sys

# Mock dbus module before importing AutoBrightnessService
mock_dbus = Mock()
sys.modules["dbus"] = mock_dbus

import time
from ..autobrightness import AutoBrightnessService, Reading


class TestAutoBrightnessService(unittest.TestCase):
    def setUp(self):
        # Setup mock dbus
        self.mock_session = Mock()
        mock_dbus.SessionBus.return_value = self.mock_session

        self.mock_proxy = Mock()
        self.mock_session.get_object.return_value = self.mock_proxy

        self.mock_interface = Mock()
        self.mock_proxy.get_dbus_method.return_value = self.mock_interface

        mock_dbus.Interface.return_value = self.mock_interface

        # Initialize service with mocked dependencies
        self.service = AutoBrightnessService()

        # Make the mock behave like the number 5 in comparisons and arithmetic
        type(self.service).step = property(lambda _: 5)

        # Mock threading events
        self.service.stop_event = Mock()
        self.service.stop_event.is_set.return_value = False
        self.service.light_event = Mock()
        self.service.light_event.is_set.return_value = False
        self.service.light_event.wait.return_value = True

        # Mock display object and attributes
        self.mock_display = Mock()
        self.service.display = self.mock_display
        self.mock_display.set_brightness = Mock()
        self.mock_display.max_brightness = 100
        self.mock_display.brightness = 50

        # Mock display-related attributes
        self.service.brightness_threshold_delta = 5
        self.service.max_brightness = 100
        self.service.current_brightness = 50
        self.service.lights = []
        self.service.twa = 0

        # Setup test parameters
        self.service.max_illuminance = 2000
        self.service.fps = 5
        self.service.avg_period = 1.0
        self.service.light_timeout = 1.0
        self.service.brightness_power = 1.0
        self.service.user_brightness_bias = 0
        self.service.inhibited_by_powerdevil = False

    def test_time_weighted_average_constant(self):
        """Test TWA calculation with constant light level"""
        now = time.time()
        self.service.lights = [
            Reading(ts=now - 2, val=100),
            Reading(ts=now - 1, val=100),
            Reading(ts=now, val=100),
        ]

        result = self.service.calc_time_weighted_avg()
        self.assertEqual(result, 100)

    def test_time_weighted_average_varying(self):
        """Test TWA calculation with varying light levels"""
        now = time.time()
        self.service.lights = [
            Reading(ts=now - 2, val=100),
            Reading(ts=now - 1, val=200),
            Reading(ts=now, val=300),
        ]

        result = self.service.calc_time_weighted_avg()
        # Average should be weighted by time intervals
        self.assertAlmostEqual(result, 200.0)

    def test_recommended_brightness_min_light(self):
        """Test brightness calculation at minimum light level"""
        self.service.twa = 0  # No light
        self.service.update_brightness_map()
        result = self.service.get_recommended_brightness()

        # Should be at minimum brightness
        self.assertEqual(result, self.service.light_to_brightness_map[0][0])

    def test_recommended_brightness_max_light(self):
        """Test brightness calculation at maximum light level"""
        self.service.twa = self.service.max_illuminance
        result = self.service.get_recommended_brightness()

        # Should be at maximum brightness
        self.assertEqual(result, self.service.max_brightness)

    def test_recommended_brightness_with_bias(self):
        """Test brightness calculation with user bias"""
        self.service.twa = self.service.max_illuminance // 2
        bias = 10

        baseline = self.service.get_recommended_brightness(bias=0)
        result = self.service.get_recommended_brightness(bias=bias)

        # Result should be baseline + bias, but not exceed max_brightness
        expected = min(baseline + bias, self.service.max_brightness)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
