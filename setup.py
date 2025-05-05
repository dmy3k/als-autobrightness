from setuptools import setup, find_packages

setup(
    name="autobrightness",
    author="dmy3k",
    version="0.1.2",
    description="Adjusts screen brighness based on ambient light sensor (ALS)",
    packages=find_packages(
        exclude=["contrib", "docs", "autobrightness.services.tests"]
    ),
    install_requires=[
        "dbus-python>=1.3.2",
    ],
    entry_points={"console_scripts": ["autobrightnesscli = autobrightness.cli:main"]},
)
