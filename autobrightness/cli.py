import logging
from autobrightness.services.autobrightness import AutoBrightnessService
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop
import argparse


def main():
    parser = argparse.ArgumentParser("autobrightnesscli")
    parser.add_argument(
        "--default-systemd-cfg",
        action=argparse.BooleanOptionalAction,
        help="Print default systemd config file",
    )
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.default_systemd_cfg:
        from autobrightness.config import default_systemd_cfg

        print(default_systemd_cfg)
        return

    DBusGMainLoop(set_as_default=True)

    service = AutoBrightnessService()

    if args.verbose:
        service.logger.setLevel(logging.DEBUG)

    try:
        loop = GLib.MainLoop()
        service.run()
        loop.run()
    finally:
        service.stop()


if __name__ == "__main__":
    main()
