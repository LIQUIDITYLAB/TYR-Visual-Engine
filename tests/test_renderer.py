"""End-to-end render tests: real MP4 output, determinism, audio muxing."""

import hashlib
import shutil
import subprocess
import textwrap

import pytest

from tyr.renderer import render

TINY = """\
    video:
      width: 160
      height: 90
      fps: 10
      background: {type: solid, color: "#101018"}
    scenes:
      - name: one
        duration: 0.5
        background:
          type: gradient
          from: "#101018"
          to: "#2a2a44"
        elements:
          - type: text
            text: "TYR"
            x: 80
            y: 45
            font_size: 28
            start: 0
            end: 0.5
            animate: {x: [20, 80]}
          - type: rect
            x: 10
            y: 60
            width: 40
            height: 20
            fill: "#ff5500"
            radius: 4
            start: 0.1
            end: 0.5
      - name: two
        duration: 0.5
        transition_in: fade
        transition_duration: 0.3
        elements:
          - type: ellipse
            x: 100
            y: 20
            width: 40
            height: 40
            fill: "#22d3ee"
            start: 0
            end: 0.5
    """


def _scene(tmp_path):
    p = tmp_path / "tiny.yaml"
    p.write_text(textwrap.dedent(TINY), encoding="utf-8")
    return p


def _is_mp4(path):
    with open(path, "rb") as f:
        header = f.read(12)
    return len(header) == 12 and header[4:8] == b"ftyp"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_produces_valid_mp4(tmp_path):
    out = tmp_path / "out.mp4"
    render(_scene(tmp_path), out, quiet=True)
    assert out.is_file()
    assert out.stat().st_size > 1024
    assert _is_mp4(out)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_is_deterministic(tmp_path):
    scene = _scene(tmp_path)
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    render(scene, a, quiet=True)
    render(scene, b, quiet=True)
    assert _sha256(a) == _sha256(b)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_with_audio_mux(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1", "-c:a", "pcm_s16le", str(wav)],
        check=True,
    )
    out = tmp_path / "with-audio.mp4"
    render(_scene(tmp_path), out, audio_path=wav, quiet=True)
    assert out.is_file() and _is_mp4(out)
    # The muxed file must contain an audio stream.
    probe = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(out), "-map", "0:a",
         "-f", "null", "-"],
        capture_output=True,
    )
    assert probe.returncode == 0
