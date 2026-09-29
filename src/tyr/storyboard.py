"""Parse, validate, and expand scene files into a deterministic frame timeline.

No wall-clock time, no randomness: the same scene file always produces the
same :class:`Timeline`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from .schema import (
    VALID_ANCHORS,
    VALID_DIRECTIONS,
    VALID_ELEMENT_TYPES,
    VALID_TRANSITIONS,
    AnimationSpec,
    BackgroundSpec,
    Element,
    EllipseElement,
    ImageElement,
    RectElement,
    Scene,
    SceneFile,
    TextElement,
    VideoSpec,
)


class StoryboardError(ValueError):
    """Raised when a scene file is invalid. The message names the location."""


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _fail(ctx: str, msg: str) -> None:
    raise StoryboardError(f"{ctx}: {msg}")


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _req(mapping: dict, key: str, ctx: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        _fail(ctx, f"missing required key '{key}'")
    return mapping[key]


def _color(value: Any, ctx: str) -> str:
    if not isinstance(value, str) or not _HEX_COLOR.match(value):
        _fail(ctx, f"invalid hex color {value!r} (expected '#rgb' or '#rrggbb')")
    return value


def _pos_num(value: Any, ctx: str, name: str) -> float:
    if not _is_num(value) or value <= 0:
        _fail(ctx, f"'{name}' must be a positive number, got {value!r}")
    return float(value)


def _parse_background(raw: Any, ctx: str) -> BackgroundSpec:
    if raw is None:
        return BackgroundSpec()
    if not isinstance(raw, dict):
        _fail(ctx, "background must be a mapping")
    btype = raw.get("type", "solid")
    if btype not in ("solid", "gradient"):
        _fail(ctx, f"background type must be 'solid' or 'gradient', got {btype!r}")
    direction = raw.get("direction", "vertical")
    if direction not in VALID_DIRECTIONS:
        _fail(ctx, f"background direction must be one of {VALID_DIRECTIONS}")
    return BackgroundSpec(
        type=btype,
        color=_color(raw.get("color", "#000000"), ctx + ".color"),
        from_color=_color(raw.get("from", "#000000"), ctx + ".from"),
        to_color=_color(raw.get("to", "#ffffff"), ctx + ".to"),
        direction=direction,
    )


def _parse_animation(raw: Any, ctx: str) -> Optional[AnimationSpec]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _fail(ctx, "'animate' must be a mapping like {x: [from, to]}")
    spec: dict[str, tuple[float, float]] = {}
    for axis in ("x", "y"):
        if axis in raw:
            pair = raw[axis]
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or not all(_is_num(v) for v in pair)
            ):
                _fail(ctx, f"'animate.{axis}' must be a [from, to] number pair")
            spec[axis] = (float(pair[0]), float(pair[1]))
    if not spec:
        _fail(ctx, "'animate' must define at least one of 'x', 'y'")
    return AnimationSpec(**spec)


def _parse_element(raw: dict, ctx: str, scene_duration: float, base_dir: Path) -> Element:
    kind = _req(raw, "type", ctx)
    if kind not in VALID_ELEMENT_TYPES:
        _fail(ctx, f"unknown element type {kind!r} (expected one of {VALID_ELEMENT_TYPES})")

    start = raw.get("start", 0.0)
    end = _req(raw, "end", ctx)
    if not _is_num(start) or start < 0:
        _fail(ctx, f"'start' must be >= 0, got {start!r}")
    if not _is_num(end) or end <= start:
        _fail(ctx, f"'end' ({end!r}) must be greater than 'start' ({start!r})")
    if end > scene_duration:
        _fail(ctx, f"'end' ({end!r}) exceeds scene duration ({scene_duration})")
    animate = _parse_animation(raw.get("animate"), ctx + ".animate")

    def num(key: str, default: Any = 0.0) -> float:
        v = raw.get(key, default)
        if not _is_num(v):
            _fail(ctx, f"'{key}' must be a number, got {v!r}")
        return float(v)

    if kind == "text":
        text = _req(raw, "text", ctx)
        if not isinstance(text, str):
            _fail(ctx, f"'text' must be a string, got {text!r}")
        anchor = raw.get("anchor", "center")
        if anchor not in VALID_ANCHORS:
            _fail(ctx, f"'anchor' must be one of {VALID_ANCHORS}, got {anchor!r}")
        font_size = raw.get("font_size", 48)
        if not _is_num(font_size) or int(font_size) <= 0:
            _fail(ctx, f"'font_size' must be a positive number, got {font_size!r}")
        font_path = raw.get("font_path")
        if font_path is not None:
            p = (base_dir / str(font_path)).resolve()
            if not p.is_file():
                _fail(ctx, f"font_path not found: {font_path!r}")
            font_path = str(p)
        return TextElement(
            kind=kind,
            start=float(start),
            end=float(end),
            animate=animate,
            text=text,
            x=num("x"),
            y=num("y"),
            anchor=anchor,
            font_size=int(font_size),
            color=_color(raw.get("color", "#ffffff"), ctx + ".color"),
            font_path=font_path,
        )

    if kind in ("rect", "ellipse"):
        width = _pos_num(raw.get("width"), ctx, "width")
        height = _pos_num(raw.get("height"), ctx, "height")
        fill = _color(raw.get("fill", "#ffffff"), ctx + ".fill")
        cls = RectElement if kind == "rect" else EllipseElement
        kwargs: dict[str, Any] = {}
        if kind == "rect":
            radius = raw.get("radius", 0.0)
            if not _is_num(radius) or radius < 0:
                _fail(ctx, f"'radius' must be >= 0, got {radius!r}")
            kwargs["radius"] = float(radius)
        return cls(
            kind=kind,
            start=float(start),
            end=float(end),
            animate=animate,
            x=num("x"),
            y=num("y"),
            width=width,
            height=height,
            fill=fill,
            **kwargs,
        )

    # kind == "image"
    rel = _req(raw, "path", ctx)
    if not isinstance(rel, str):
        _fail(ctx, f"'path' must be a string, got {rel!r}")
    resolved = (base_dir / rel).resolve()
    if not resolved.is_file():
        _fail(ctx, f"image file not found: {rel!r} (resolved against scene file directory)")
    width = raw.get("width")
    height = raw.get("height")
    for label, v in (("width", width), ("height", height)):
        if v is not None and (not _is_num(v) or v <= 0):
            _fail(ctx, f"'{label}' must be a positive number, got {v!r}")
    anchor = raw.get("anchor", "center")
    if anchor not in ("center", "topleft"):
        _fail(ctx, f"image 'anchor' must be 'center' or 'topleft', got {anchor!r}")
    return ImageElement(
        kind=kind,
        start=float(start),
        end=float(end),
        animate=animate,
        path=str(resolved),
        x=num("x"),
        y=num("y"),
        width=float(width) if width is not None else None,
        height=float(height) if height is not None else None,
        anchor=anchor,
    )


def _parse_scene(raw: dict, index: int, base_dir: Path) -> Scene:
    ctx = f"scenes[{index}]"
    if not isinstance(raw, dict):
        _fail(ctx, "each scene must be a mapping")
    name = raw.get("name", f"scene-{index}")
    if not isinstance(name, str):
        _fail(ctx, f"'name' must be a string, got {name!r}")
    duration = raw.get("duration")
    if not _is_num(duration) or duration <= 0:
        _fail(ctx, f"'duration' must be a positive number, got {duration!r}")
    duration = float(duration)

    transition_in = raw.get("transition_in", "cut")
    if transition_in not in VALID_TRANSITIONS:
        _fail(ctx, f"'transition_in' must be one of {VALID_TRANSITIONS}, got {transition_in!r}")
    td = raw.get("transition_duration", 0.5)
    if not _is_num(td) or td <= 0:
        _fail(ctx, f"'transition_duration' must be a positive number, got {td!r}")
    td = float(td)
    if transition_in == "fade" and index > 0 and td >= duration:
        _fail(ctx, f"'transition_duration' ({td}) must be shorter than the scene duration ({duration})")

    elements_raw = raw.get("elements", [])
    if not isinstance(elements_raw, list):
        _fail(ctx, "'elements' must be a list")
    elements = tuple(
        _parse_element(e, f"{ctx}.elements[{i}]", duration, base_dir)
        for i, e in enumerate(elements_raw)
    )
    return Scene(
        name=name,
        duration=duration,
        transition_in=transition_in,
        transition_duration=td,
        background=_parse_background(raw.get("background"), ctx + ".background"),
        elements=elements,
    )


def load_scene_file(path: str | Path) -> SceneFile:
    """Read a YAML scene file, validate it fully, and return a :class:`SceneFile`.

    Raises :class:`StoryboardError` on any problem. Image/font paths in the
    file are resolved relative to the scene file's directory.
    """
    path = Path(path)
    if not path.is_file():
        raise StoryboardError(f"scene file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise StoryboardError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise StoryboardError(f"{path}: top level must be a mapping")

    video_raw = raw.get("video", {})
    if not isinstance(video_raw, dict):
        raise StoryboardError("video: must be a mapping")
    vctx = "video"
    width = video_raw.get("width", 1280)
    height = video_raw.get("height", 720)
    fps = video_raw.get("fps", 30)
    for label, v in (("width", width), ("height", height)):
        if not _is_num(v) or int(v) <= 0:
            raise StoryboardError(f"{vctx}: '{label}' must be a positive integer, got {v!r}")
    if not _is_num(fps) or fps <= 0:
        raise StoryboardError(f"{vctx}: 'fps' must be a positive number, got {fps!r}")
    video = VideoSpec(
        width=int(width),
        height=int(height),
        fps=float(fps),
        background=_parse_background(video_raw.get("background"), vctx + ".background"),
    )

    scenes_raw = raw.get("scenes")
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise StoryboardError("'scenes' must be a non-empty list")
    base_dir = path.parent.resolve()
    scenes = tuple(_parse_scene(s, i, base_dir) for i, s in enumerate(scenes_raw))

    # Cross-check fade durations against the *previous* scene too.
    for i in range(1, len(scenes)):
        s = scenes[i]
        if s.transition_in == "fade" and s.transition_duration >= scenes[i - 1].duration:
            raise StoryboardError(
                f"scenes[{i}]: 'transition_duration' ({s.transition_duration}) must be "
                f"shorter than the previous scene's duration ({scenes[i - 1].duration})"
            )
    return SceneFile(video=video, scenes=scenes)


@dataclass(frozen=True)
class FrameCue:
    """Everything the renderer needs for one output frame."""

    index: int
    time: float  # seconds from the start of the video
    scene_index: int
    scene_time: float  # seconds from the start of the scene
    blend_alpha: float = 0.0  # >0 during a fade: weight of the *current* scene
    prev_scene_index: Optional[int] = None
    prev_scene_time: float = 0.0


@dataclass(frozen=True)
class Timeline:
    scene_file: SceneFile
    fps: float
    total_frames: int
    total_duration: float
    cues: tuple[FrameCue, ...]


def build_timeline(scene_file: SceneFile) -> Timeline:
    """Expand a validated scene file into a deterministic per-frame timeline."""
    fps = scene_file.video.fps
    boundaries: list[float] = [0.0]
    for s in scene_file.scenes:
        boundaries.append(boundaries[-1] + s.duration)
    total_duration = boundaries[-1]
    total_frames = int(round(total_duration * fps))

    cues: list[FrameCue] = []
    eps = 1e-9
    for i in range(total_frames):
        t = i / fps
        # Find the scene containing t.
        j = 0
        while j < len(scene_file.scenes) - 1 and t >= boundaries[j + 1] - eps:
            j += 1
        scene = scene_file.scenes[j]
        scene_time = t - boundaries[j]
        cue = FrameCue(index=i, time=t, scene_index=j, scene_time=scene_time)
        if (
            j > 0
            and scene.transition_in == "fade"
            and scene_time < scene.transition_duration - eps
        ):
            prev = scene_file.scenes[j - 1]
            cue = FrameCue(
                index=i,
                time=t,
                scene_index=j,
                scene_time=scene_time,
                blend_alpha=scene_time / scene.transition_duration,
                prev_scene_index=j - 1,
                # Frozen frame: middle of the previous scene's last frame.
                prev_scene_time=prev.duration - 0.5 / fps,
            )
        cues.append(cue)
    return Timeline(
        scene_file=scene_file,
        fps=fps,
        total_frames=total_frames,
        total_duration=total_duration,
        cues=tuple(cues),
    )


def is_active(el: Element, t: float) -> bool:
    """True if the element is visible at scene-local time ``t``."""
    return el.start <= t < el.end


def element_position(el: Element, t: float) -> tuple[float, float]:
    """Interpolated ``(x, y)`` of an element at scene-local time ``t``."""
    x = float(getattr(el, "x", 0.0))
    y = float(getattr(el, "y", 0.0))
    anim = el.animate
    if anim is None:
        return (x, y)
    span = el.end - el.start
    k = 0.0 if span <= 0 else min(1.0, max(0.0, (t - el.start) / span))
    if anim.x is not None:
        x = anim.x[0] + (anim.x[1] - anim.x[0]) * k
    if anim.y is not None:
        y = anim.y[0] + (anim.y[1] - anim.y[0]) * k
    return (x, y)
