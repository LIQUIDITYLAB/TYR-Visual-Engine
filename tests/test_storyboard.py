"""Tests for scene parsing, validation, and timeline expansion."""

import textwrap

import pytest

from tyr.storyboard import (
    StoryboardError,
    build_timeline,
    element_position,
    load_scene_file,
)


def _write(tmp_path, text):
    p = tmp_path / "scene.yaml"
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


MINIMAL = """\
    video:
      width: 320
      height: 180
      fps: 10
    scenes:
      - name: a
        duration: 1.0
        elements:
          - type: text
            text: "hi"
            x: 160
            y: 90
            start: 0
            end: 1.0
    """


def test_valid_minimal_scene(tmp_path):
    sf = load_scene_file(_write(tmp_path, MINIMAL))
    assert sf.video.width == 320
    assert sf.video.fps == 10.0
    assert len(sf.scenes) == 1
    tl = build_timeline(sf)
    assert tl.total_frames == 10
    assert tl.total_duration == pytest.approx(1.0)
    assert all(c.scene_index == 0 for c in tl.cues)


def test_frame_count_rounding(tmp_path):
    scene = MINIMAL.replace("duration: 1.0", "duration: 2.5")
    sf = load_scene_file(_write(tmp_path, scene))
    assert build_timeline(sf).total_frames == 25


def test_bad_hex_color_rejected(tmp_path):
    scene = MINIMAL.replace('color: "#ffffff"', 'color: "red"')
    # inject a bad color on the text element instead
    scene = MINIMAL.replace('text: "hi"', 'text: "hi"\n            color: "red"')
    with pytest.raises(StoryboardError, match="invalid hex color"):
        load_scene_file(_write(tmp_path, scene))


def test_end_before_start_rejected(tmp_path):
    scene = MINIMAL.replace("end: 1.0", "end: 0.0")
    with pytest.raises(StoryboardError, match="'end'.*must be greater than 'start'"):
        load_scene_file(_write(tmp_path, scene))


def test_end_beyond_scene_duration_rejected(tmp_path):
    scene = MINIMAL.replace("end: 1.0", "end: 5.0")
    with pytest.raises(StoryboardError, match="exceeds scene duration"):
        load_scene_file(_write(tmp_path, scene))


def test_unknown_element_type_rejected(tmp_path):
    scene = MINIMAL.replace('type: text', 'type: star')
    with pytest.raises(StoryboardError, match="unknown element type"):
        load_scene_file(_write(tmp_path, scene))


def test_missing_image_rejected(tmp_path):
    scene = MINIMAL.replace(
        "elements:",
        "elements:\n          - type: image\n            path: nope.png\n"
        "            x: 10\n            y: 10\n            start: 0\n            end: 1.0",
    )
    with pytest.raises(StoryboardError, match="image file not found"):
        load_scene_file(_write(tmp_path, scene))


def test_empty_scenes_rejected(tmp_path):
    scene = "video: {width: 320, height: 180, fps: 10}\nscenes: []\n"
    with pytest.raises(StoryboardError, match="non-empty list"):
        load_scene_file(_write(tmp_path, scene))


def test_fade_longer_than_scene_rejected(tmp_path):
    scene = """\
        video: {width: 320, height: 180, fps: 10}
        scenes:
          - {name: a, duration: 1.0}
          - {name: b, duration: 1.0, transition_in: fade, transition_duration: 2.0}
        """
    with pytest.raises(StoryboardError, match="transition_duration"):
        load_scene_file(_write(tmp_path, scene))


def test_animation_interpolation(tmp_path):
    scene = MINIMAL.replace(
        "end: 1.0", "end: 1.0\n            animate:\n              x: [0, 100]\n              y: [50, 50]"
    )
    sf = load_scene_file(_write(tmp_path, scene))
    el = sf.scenes[0].elements[0]
    assert element_position(el, 0.0) == (0.0, 50.0)
    assert element_position(el, 0.5) == (50.0, 50.0)
    assert element_position(el, 1.0) == (100.0, 50.0)


def test_no_animation_returns_base_position(tmp_path):
    sf = load_scene_file(_write(tmp_path, MINIMAL))
    el = sf.scenes[0].elements[0]
    assert element_position(el, 0.3) == (160.0, 90.0)


def test_fade_transition_produces_blend_cues(tmp_path):
    scene = """\
        video: {width: 320, height: 180, fps: 10}
        scenes:
          - {name: a, duration: 1.0}
          - {name: b, duration: 1.0, transition_in: fade, transition_duration: 0.5}
        """
    sf = load_scene_file(_write(tmp_path, scene))
    tl = build_timeline(sf)
    assert tl.total_frames == 20
    # The first 0.5s of scene b (5 frames @ 10fps) is the cross-fade window.
    # The frame exactly on the boundary is 100% previous scene (alpha 0.0);
    # the following 4 frames blend in.
    window = [c for c in tl.cues if c.scene_index == 1 and c.scene_time < 0.5]
    assert len(window) == 5
    assert window[0].blend_alpha == pytest.approx(0.0)
    blended = [c for c in window if c.blend_alpha > 0]
    assert len(blended) == 4
    assert all(c.prev_scene_index == 0 for c in blended)
    assert blended[0].blend_alpha == pytest.approx(0.2)
    assert blended[-1].blend_alpha == pytest.approx(0.8)


def test_missing_file_raises(tmp_path):
    with pytest.raises(StoryboardError, match="not found"):
        load_scene_file(tmp_path / "does-not-exist.yaml")
