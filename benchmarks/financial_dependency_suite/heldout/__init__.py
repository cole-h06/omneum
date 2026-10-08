"""Install the current SDK boundary without modifying the frozen harness.

The manifest pins loader.py and runner.py alongside dataset artifacts. The
runner keeps its frozen import; only the occurrence-to-SDK adapter changes.
"""
from . import loader
from .sdk_adapter import build_observations

loader.build_observations = build_observations
