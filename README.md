# Adaptive brightness service

Adaptive brightness service for laptops running linux with KDE 6 desktop.
The project serves the purpose during the absense of official support in KWin or PowerDevil.

## Highlights

- Minimal number of dependencies
- Requires ambient light sensor (ALS)
- Efficient, utilizes sensor signals via dbus (no sensor polling)
- Uses [time weighted average](https://www.timescale.com/blog/what-time-weighted-averages-are-and-why-you-should-care/) to smooth out brigtness changes
- Runs unpriviledged
- Allows end-user to set brightness to the liking (offsetting adaptive brightness)
- Tested with Fedora 40-42, KDE Plasma 6.2-6.3

## Prerequisites

Make sure your device has the sensor before proceeding with setup.
Check packages below are installed (should be pre-installed in most distros)

```bash
sudo dnf install iio-sensor-proxy python3-pip python3-dbus git
systemctl status iio-sensor-proxy.service
```

## Install

```bash
pip install -U git+https://github.com/dmy3k/als-autobrightness.git@main

# Setup as service
autobrightnesscli --default-systemd-cfg > ~/.config/systemd/user/autobrightness.service
systemctl --user enable --now autobrightness

# Verify service is running
systemctl --user status autobrightness

# Get logs (e.g for bugreport)
journalctl --user -u autobrightness
```

## Uninstall

```bash
# Disable and remove systemd service
systemctl --user disable --now autobrightness
rm ~/.config/systemd/user/autobrightness.service

# Uninstall package
pip uninstall autobrightness
```

## References

### Outstanding issues and merge requests
- PowerDevil - [Automatic screen brightness based on ambient light](https://invent.kde.org/plasma/powerdevil/-/issues/21)
- Kwin - [automatic brightness adjustment](https://invent.kde.org/plasma/kwin/-/merge_requests/5876)

### Similar projects

- https://github.com/danielztolnai/zendisplay/tree/master
- https://github.com/mikhail-m1/illuminanced
- https://github.com/taotien/framework_toolbox/tree/master
