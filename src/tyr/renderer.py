"""Headless frame renderer (Pillow) and MP4 encoder (ffmpeg).

Rendering is fully deterministic: the same scene file always yields the same
pixel data, and frames are encoded with single-threaded libx264 so repeated
renders are byte-identical.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .schema import (
    BackgroundSpec,
    EllipseElement,
    ImageElement,
    RectElement,
    Scene,
    SceneFile,
    TextElement,
)
from .storyboard import FrameCue, Timeline, build_timeline, element_position, is_active

_TEXT_ANCHORS = {
    "center": "mm",
    "topleft": "lt",
    "topright": "rt",
    "bottomleft": "lb",
    "bottomright": "rb",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def _check_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError(
            "ffmpeg was not found on PATH. Install it (e.g. 'apt install ffmpeg') "
            "to render video."
        )
    return exe


class Renderer:
    """Renders every frame of a timeline with Pillow and encodes to MP4."""

    def __init__(self, scene_file: SceneFile):
        self.scene_file = scene_file
        self.video = scene_file.video
        self._bg_cache: dict[tuple, Image.Image] = {}
        self._font_cache: dict[tuple, ImageFont.FreeTypeFont] = {}
        self._image_cache: dict[str, Image.Image] = {}

    # -- backgrounds ----------------------------------------------------
    def _background(self, spec: BackgroundSpec) -> Image.Image:
        key = (spec.type, spec.color, spec.from_color, spec.to_color,
               spec.direction, self.video.width, self.video.height)
        if key not in self._bg_cache:
            w, h = self.video.width, self.video.height
            if spec.type == "gradient":
                self._bg_cache[key] = self._gradient(spec, w, h)
            else:
                self._bg_cache[key] = Image.new("RGB", (w, h), _hex_to_rgb(spec.color))
        return self._bg_cache[key].copy()

    @staticmethod
    def _gradient(spec: BackgroundSpec, w: int, h: int) -> Image.Image:
        c0 = _hex_to_rgb(spec.from_color)
        c1 = _hex_to_rgb(spec.to_color)
        # Render a 256-step strip, then scale: fast and banding-free enough.
        n = 256
        if spec.direction == "horizontal":
            strip = Image.new("RGB", (n, 1))
            px = strip.load()
            for i in range(n):
                k = i / (n - 1)
                px[i, 0] = tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))  # type: ignore
            return strip.resize((w, h), Image.BILINEAR)
        strip = Image.new("RGB", (1, n))
        px = strip.load()
        for i in range(n):
            k = i / (n - 1)
            px[0, i] = tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))  # type: ignore
        return strip.resize((w, h), Image.BILINEAR)

    # -- resources ------------------------------------------------------
    def _font(self, el: TextElement):
        key = (el.font_path, el.font_size)
        if key not in self._font_cache:
            if el.font_path:
                font = ImageFont.truetype(el.font_path, el.font_size)
            else:
                # Pillow's built-in bitmap/vector default; deterministic.
                font = ImageFont.load_default(size=el.font_size)
            self._font_cache[key] = font
        return self._font_cache[key]

    def _image(self, path: str) -> Image.Image:
        if path not in self._image_cache:
            self._image_cache[path] = Image.open(path).convert("RGBA")
        return self._image_cache[path]

    # -- frame rendering ------------------------------------------------
    def render_scene_frame(self, scene_index: int, scene_time: float) -> Image.Image:
        scene: Scene = self.scene_file.scenes[scene_index]
        spec = scene.background or self.video.background
        frame = self._background(spec).convert("RGBA")
        draw = ImageDraw.Draw(frame)

        for el in scene.elements:
            if not is_active(el, scene_time):
                continue
            x, y = element_position(el, scene_time)
            if isinstance(el, TextElement):
                draw.text(
                    (x, y),
                    el.text,
                    font=self._font(el),
                    fill=_hex_to_rgb(el.color) + (255,),
                    anchor=_TEXT_ANCHORS[el.anchor],
                )
            elif isinstance(el, RectElement):
                box = [x, y, x + el.width, y + el.height]
                fill = _hex_to_rgb(el.fill) + (255,)
                if el.radius > 0:
                    draw.rounded_rectangle(box, radius=el.radius, fill=fill)
                else:
                    draw.rectangle(box, fill=fill)
            elif isinstance(el, EllipseElement):
                draw.ellipse([x, y, x + el.width, y + el.height],
                             fill=_hex_to_rgb(el.fill) + (255,))
            elif isinstance(el, ImageElement):
                src = self._image(el.path)
                w = el.width if el.width is not None else src.width
                h = el.height if el.height is not None else src.height
                if el.width is not None and el.height is None:
                    h = src.height * (el.width / src.width)
                elif el.height is not None and el.width is None:
                    w = src.width * (el.height / src.height)
                img = src.resize((round(w), round(h)), Image.LANCZOS)
                px, py = (x - w / 2, y - h / 2) if el.anchor == "center" else (x, y)
                frame.alpha_composite(img, (round(px), round(py)))
        return frame.convert("RGB")

    def render_frame(self, cue: FrameCue) -> Image.Image:
        current = self.render_scene_frame(cue.scene_index, cue.scene_time)
        if cue.blend_alpha > 0 and cue.prev_scene_index is not None:
            prev = self.render_scene_frame(cue.prev_scene_index, cue.prev_scene_time)
            return Image.blend(prev, current, cue.blend_alpha)
        return current

    # -- encoding -------------------------------------------------------
    def encode(self, timeline: Timeline, output: Path,
               audio_path: Optional[Path] = None, quiet: bool = False) -> None:
        ffmpeg = _check_ffmpeg()
        w, h, fps = self.video.width, self.video.height, self.video.fps
        fps_arg = str(int(fps)) if float(fps).is_integer() else repr(float(fps))

        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}", "-framerate", fps_arg, "-i", "-",
        ]
        if audio_path is not None:
            if not audio_path.is_file():
                raise RuntimeError(f"audio file not found: {audio_path}")
            cmd += ["-i", str(audio_path)]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-threads", "1",  # single thread: deterministic output
        ]
        if audio_path is not None:
            cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
        else:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart", str(output)]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        assert proc.stdin is not None
        total = timeline.total_frames
        try:
            for n, cue in enumerate(timeline.cues):
                proc.stdin.write(self.render_frame(cue).tobytes())
                if not quiet and (n + 1) % max(1, total // 20) == 0:
                    print(f"\r  frame {n + 1}/{total}", end="", file=sys.stderr, flush=True)
        except BrokenPipeError as exc:
            _, err = proc.communicate()
            raise RuntimeError(
                f"ffmpeg died while receiving frames: {err.decode(errors='replace')}"
            ) from exc
        # communicate() flushes and closes stdin itself.
        _, err = proc.communicate()
        if not quiet:
            print(file=sys.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace')}")


def render(scene_path: str | Path, output_path: str | Path,
           audio_path: Optional[str | Path] = None, quiet: bool = False) -> Path:
    """Full pipeline: load scene file -> timeline -> frames -> MP4.

    Returns the output path. Raises :class:`StoryboardError` for bad scene
    files and :class:`RuntimeError` for ffmpeg/audio problems.
    """
    from .storyboard import load_scene_file  # local import: cheap, avoids cycles

    scene_file = load_scene_file(scene_path)
    timeline = build_timeline(scene_file)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio = Path(audio_path) if audio_path else None
    Renderer(scene_file).encode(timeline, out, audio_path=audio, quiet=quiet)
    return out
