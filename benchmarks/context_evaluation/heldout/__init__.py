"""Connect the held-out benchmark loader to the SDK adapter."""

from . import loader
from .sdk_adapter import build_observations

loader.build_observations = build_observations