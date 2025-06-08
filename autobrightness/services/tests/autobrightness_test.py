import unittest
from unittest.mock import Mock
import sys

# Mock dbus module before importing AutoBrightnessService
mock_dbus = Mock()
sys.modules["dbus"] = mock_dbus

from ..autobrightness import AutoBrightnessService


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
        self.service.anim_abort_event = Mock()
        self.service.anim_abort_event.is_set.return_value = False
        self.service.anim_abort_event.wait.return_value = True

        # Mock display object and attributes
        self.mock_display = Mock()
        self.service.display = self.mock_display
        self.mock_display.set_brightness = Mock()
        self.mock_display.max_brightness = 10000
        self.mock_display.brightness = 50

        # Mock display-related attributes
        self.service.brightness_threshold_delta = 5
        self.service.max_brightness = 10000
        self.service.current_brightness = 50
        self.service.current_light_level = 0

        # Setup test parameters
        self.service.user_brightness_bias = 0
        self.service.inhibited_by_powerdevil = False

    def test_recommended_brightness_min_light(self):
        """Test brightness calculation at minimum light level"""
        self.service.current_light_level = 0  # No light
        result = self.service.get_recommended_brightness()

        # Should be at minimum brightness
        self.assertEqual(result, 1000)

    def test_recommended_brightness_max_light(self):
        """Test brightness calculation at maximum light level"""
        self.service.current_light_level = 2000
        result = self.service.get_recommended_brightness()

        # Should be at maximum brightness
        self.assertEqual(result, 8000)

    def test_recommended_brightness_with_bias(self):
        """Test brightness calculation with user bias"""
        self.service.current_light_level = 2000
        bias = 1000

        baseline = self.service.get_recommended_brightness(bias=0)
        result = self.service.get_recommended_brightness(bias=bias)

        self.assertEqual(result - baseline, bias)


if __name__ == "__main__":
    unittest.main()
