"""Data model for TYR scene descriptions.

A scene file is YAML (see ``examples/demo.yaml`` and ``README.md`` for the
full schema). This module holds the immutable dataclasses; parsing and
validation live in :mod:`tyr.storyboard`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VALID_TRANSITIONS = ("cut", "fade")
VALID_ELEMENT_TYPES = ("text", "rect", "ellipse", "image")
VALID_ANCHORS = ("center", "topleft", "topright", "bottomleft", "bottomright")
VALID_DIRECTIONS = ("vertical", "horizontal")


@dataclass(frozen=True)
class BackgroundSpec:
    """Scene or video background: a solid color or a two-stop gradient."""

    type: str = "solid"  # "solid" | "gradient"
    color: str = "#000000"
    from_color: str = "#000000"
    to_color: str = "#ffffff"
    direction: str = "vertical"  # "vertical" | "horizontal"


@dataclass(frozen=True)
class VideoSpec:
    width: int = 1280
    height: int = 720
    fps: float = 30.0
    background: BackgroundSpec = field(default_factory=BackgroundSpec)


@dataclass(frozen=True)
class AnimationSpec:
    """Linear interpolation of an element's position over its active window."""

    x: Optional[tuple[float, float]] = None  # (from, to)
    y: Optional[tuple[float, float]] = None


@dataclass(frozen=True)
class Element:
    kind: str
    start: float  # seconds, scene-local, inclusive
    end: float  # seconds, scene-local, exclusive
    animate: Optional[AnimationSpec] = None


@dataclass(frozen=True)
class TextElement(Element):
    text: str = ""
    x: float = 0.0
    y: float = 0.0
    anchor: str = "center"  # which point of the text box sits at (x, y)
    font_size: int = 48
    color: str = "#ffffff"
    font_path: Optional[str] = None  # custom TTF/OTF; default is Pillow's built-in


@dataclass(frozen=True)
class RectElement(Element):
    x: float = 0.0  # top-left corner
    y: float = 0.0
    width: float = 100.0
    height: float = 100.0
    fill: str = "#ffffff"
    radius: float = 0.0  # corner radius; 0 = sharp corners


@dataclass(frozen=True)
class EllipseElement(Element):
    x: float = 0.0  # top-left of bounding box
    y: float = 0.0
    width: float = 100.0
    height: float = 100.0
    fill: str = "#ffffff"


@dataclass(frozen=True)
class ImageElement(Element):
    path: str = ""  # resolved to an absolute path at load time
    x: float = 0.0
    y: float = 0.0
    width: Optional[float] = None  # omit to keep native size / aspect
    height: Optional[float] = None
    anchor: str = "center"


@dataclass(frozen=True)
class Scene:
    name: str
    duration: float  # seconds
    transition_in: str = "cut"  # transition from the previous scene
    transition_duration: float = 0.5
    background: Optional[BackgroundSpec] = None  # defaults to video background
    elements: tuple[Element, ...] = ()


@dataclass(frozen=True)
class SceneFile:
    video: VideoSpec
    scenes: tuple[Scene, ...]
