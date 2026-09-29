# TYR Visual Engine

A programmable video generation engine that turns structured scene
descriptions into rendered MP4 video.

V1 pipeline:

```
scene.yaml → Storyboard (parse + validate + frame timeline) → Renderer (Pillow frames → ffmpeg) → MP4
```

V1 starts with a deterministic storyboard and renderer. AI-generated scene
code ("Prompt → Director → …") is a later step and is **not** part of V1.

## Requirements

- Python 3.11+
- `ffmpeg` on `PATH` (system package, e.g. `apt install ffmpeg`)
- No network access needed at render time.

## Install

```bash
pip install -e .
# or: pip install -e ".[dev]"   # includes pytest
```

This installs the `tyr` command.

## Usage

```bash
# Check a scene file without rendering
tyr validate examples/demo.yaml

# Render to MP4
tyr render examples/demo.yaml -o out.mp4

# Render with an audio track muxed on
tyr render examples/demo.yaml -o out.mp4 --audio music.mp3
```

`python -m tyr` works the same as the `tyr` command.

## Scene file schema (YAML)

```yaml
video:
  width: 1280          # px, positive int
  height: 720          # px, positive int
  fps: 30              # frames per second, positive number
  background:          # default background for all scenes (optional)
    type: solid        # "solid" | "gradient"
    color: "#0a0a0f"   # for solid
    # from: "#0a0a0f"  # for gradient
    # to: "#1a1a2e"    # for gradient
    # direction: vertical  # "vertical" | "horizontal"

scenes:
  - name: intro
    duration: 3.0                 # seconds, > 0
    transition_in: fade           # "cut" (default) | "fade" — from previous scene
    transition_duration: 0.5      # seconds; must be shorter than both adjacent scenes
    background:                  # optional per-scene override (same shape as above)
      type: gradient
      from: "#0a0a0f"
      to: "#23233a"
    elements:
      - type: text               # "text" | "rect" | "ellipse" | "image"
        text: "Hello"
        x: 640                   # anchor point; with anchor: center this is the middle
        y: 360
        anchor: center           # "center" | "topleft" | "topright" | "bottomleft" | "bottomright"
        font_size: 64
        color: "#ffffff"
        # font_path: assets/font.ttf   # optional custom font (relative to scene file)
        start: 0.0               # visible from (scene-local seconds, inclusive)
        end: 3.0                 # visible until (exclusive, <= scene duration)
        animate:                 # optional linear position animation over [start, end]
          x: [-200, 640]

      - type: rect               # x, y = top-left corner
        x: 100
        y: 500
        width: 220
        height: 120
        fill: "#ff5500"
        radius: 12               # rounded corners (rect only, optional)
        start: 0.5
        end: 2.5

      - type: ellipse            # x, y = top-left of bounding box
        x: 1000
        y: 120
        width: 140
        height: 140
        fill: "#22d3ee"
        start: 1.0
        end: 3.0

      - type: image              # path relative to the scene file
        path: assets/badge.png
        x: 1120
        y: 600
        width: 120               # optional; keeps aspect if only one side given
        anchor: center           # "center" | "topleft"
        start: 1.0
        end: 3.0
```

Notes:

- Colors are `#rgb` or `#rrggbb`.
- Elements draw in list order (later = on top).
- `fade` cross-fades from a frozen last frame of the previous scene into the
  current one over `transition_duration`.
- Rendering is deterministic: same scene file → byte-identical MP4
  (single-threaded libx264, no timestamps, no randomness). Custom fonts are
  fine but must be present on every machine for cross-machine determinism.

## Determinism

No wall-clock reads, no unseeded randomness anywhere in the pipeline.
`tests/test_renderer.py` asserts that two consecutive renders of the same
scene are byte-identical.

## Development

```bash
python -m pytest
```

## Scope

This repository is standalone. It does not modify or depend on
`upgraded-octo-tribble`, `autonomous-trading-lab`, or `glowing-guacamole`.
