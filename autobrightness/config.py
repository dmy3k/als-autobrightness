default_systemd_cfg = """
[Unit]
Description=Autobrightness - adjusts screen brighness based on ambient light sensor (ALS)
StartLimitIntervalSec=30
StartLimitBurst=10

[Service]
ExecStart=python %h/.local/bin/autobrightnesscli
Restart=on-failure
RestartSec=5
TimeoutStopSec=10
CPUQuota=5%

[Install]
WantedBy=default.target
"""
