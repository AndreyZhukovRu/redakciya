import shutil
import subprocess

import pytest
from PIL import Image

from rk import media


def img(tmp, name, w, h):
    p = tmp / name
    Image.new("RGB", (w, h), "white").save(p)
    return p


def test_split(tmp_path):
    ps = [tmp_path / "a.jpg", tmp_path / "b.MP4"]
    assert media.photos(ps) == [ps[0]] and media.videos(ps) == [ps[1]]


def test_aspect(tmp_path):
    assert media.aspect_ok(img(tmp_path, "a.jpg", 1000, 500))
    assert not media.aspect_ok(img(tmp_path, "b.jpg", 3000, 1000))


def test_shrink(tmp_path):
    p = img(tmp_path, "big.png", 5000, 3000)
    s = media.shrink(p, 1, 2048)
    assert s != p and max(Image.open(s).size) == 2048
    assert media.shrink(p, 10**9) == p


def test_sheet(tmp_path):
    ps = [img(tmp_path, f"{i}.jpg", 800, 600) for i in range(5)]
    out = media.sheet(ps, tmp_path / "sheet.jpg")
    assert out.exists() and Image.open(out).size[0] > 1000


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
def test_ensure_audio(tmp_path):
    v = tmp_path / "mute.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1", str(v)], check=True)
    out = media.ensure_audio(v)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout
    assert "audio" in probe
    assert media.ensure_audio(out) == out


def test_ensure_audio_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(media.MediaError, match="ffmpeg"):
        media.ensure_audio(tmp_path / "x.mp4")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
def test_has_audio(tmp_path):
    v = tmp_path / "mute.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1", str(v)], check=True)
    assert media.has_audio(v) is False
    assert media.has_audio(media.ensure_audio(v)) is True
