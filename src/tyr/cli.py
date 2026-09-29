"""Command line interface: ``tyr render`` and ``tyr validate``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .renderer import render
from .storyboard import StoryboardError, build_timeline, load_scene_file


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        scene_file = load_scene_file(args.scene)
    except StoryboardError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    timeline = build_timeline(scene_file)
    v = scene_file.video
    print(f"OK: {args.scene}")
    print(f"  {v.width}x{v.height} @ {v.fps} fps, "
          f"{len(scene_file.scenes)} scene(s), "
          f"{timeline.total_frames} frames ({timeline.total_duration:.2f}s)")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    try:
        out = render(args.scene, args.output, audio_path=args.audio, quiet=args.quiet)
    except (StoryboardError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    size_kb = out.stat().st_size / 1024
    print(f"wrote {out} ({size_kb:.0f} KB)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tyr",
        description="TYR Visual Engine: deterministic scene files in, MP4 out.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pv = sub.add_parser("validate", help="check a scene file without rendering")
    pv.add_argument("scene", help="path to a YAML scene file")
    pv.set_defaults(func=_cmd_validate)

    pr = sub.add_parser("render", help="render a scene file to MP4")
    pr.add_argument("scene", help="path to a YAML scene file")
    pr.add_argument("-o", "--output", required=True, help="output MP4 path")
    pr.add_argument("--audio", default=None,
                    help="optional audio file to mux onto the output")
    pr.add_argument("--quiet", action="store_true", help="suppress progress output")
    pr.set_defaults(func=_cmd_render)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
