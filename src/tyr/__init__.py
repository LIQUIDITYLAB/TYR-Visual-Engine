"""TYR Visual Engine — deterministic, headless video generation.

Scene description (YAML) in, MP4 out. See README.md for the schema.
"""

__version__ = "0.1.0"

from .renderer import render
from .storyboard import StoryboardError, build_timeline, load_scene_file

__all__ = ["__version__", "render", "load_scene_file", "build_timeline", "StoryboardError"]
