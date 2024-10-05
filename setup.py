from setuptools import setup, find_packages

setup(
    name="autobrightness",
    author="dmy3k",
    version="0.1.0",
    description="Adjusts screen brighness based on ambient light sensor (ALS)",
    packages=find_packages(exclude=["contrib", "docs"]),
    entry_points={"console_scripts": ["autobrightnesscli = autobrightness.cli:main"]},
)
