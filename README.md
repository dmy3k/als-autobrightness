# Adaptive brightness service

Adaptive brightness service for laptops running KDE 6.

Ongoing [merge request](https://invent.kde.org/plasma/powerdevil/-/merge_requests/199) will land adaptive brightness into `PowerDevil`. Until then current app aims to deliver similar functionality.

## Highlights

- Minimal number of dependencies
- Requires ambient light sensor (ALS)
- Efficient, utilizes sensor signals via dbus (no sensor polling)
- Uses [time weighted average](https://www.timescale.com/blog/what-time-weighted-averages-are-and-why-you-should-care/) to smooth out brigtness changes
- Runs unpriviledged
- Allows end-user to set brightness to the liking (offsetting adaptive brightness)
- Tested with Fedora 40, KDE Plasma 6.2

## Prerequisites

Make sure your device has the sensor before proceeding with setup.
Check packages below are installed (should be included in most distros)

```bash
sudo dnf install iio-sensor-proxy python3-dbus
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

### Similar projects

- https://github.com/danielztolnai/zendisplay/tree/master
- https://github.com/mikhail-m1/illuminanced
- https://github.com/taotien/framework_toolbox/tree/master
