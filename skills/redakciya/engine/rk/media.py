"""Медиа альбома: фото/видео, сжатие, соотношение сторон, звук у ролика, контакт-лист."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw

VIDEO = (".mp4", ".mov")
TMP = pathlib.Path(tempfile.gettempdir()) / "redakciya"


class MediaError(RuntimeError):
    pass


def videos(paths):
    return [p for p in paths if str(p).lower().endswith(VIDEO)]


def photos(paths):
    return [p for p in paths if not str(p).lower().endswith(VIDEO)]


def shrink(p: pathlib.Path, max_bytes: int, side: int = 2048) -> pathlib.Path:
    """Копия поменьше, если файл тяжелее max_bytes. Оригинал не трогаем."""
    if p.stat().st_size <= max_bytes:
        return p
    TMP.mkdir(exist_ok=True)
    out = TMP / f"{p.stem}-{side}.jpg"
    with Image.open(p) as im:
        im = im.convert("RGB")
        im.thumbnail((side, side))
        im.save(out, "JPEG", quality=86)
    return out


def aspect_ok(p: pathlib.Path, lo: float = 0.4, hi: float = 2.5) -> bool:
    with Image.open(p) as im:
        w, h = im.size
    return lo <= w / h <= hi


def has_audio(p: pathlib.Path) -> bool:
    fp = shutil.which("ffprobe")
    if not fp or not shutil.which("ffmpeg"):
        raise MediaError(f"{pathlib.Path(p).name}: проверить звук нельзя — не найден ffmpeg "
                         "(Mac: brew install ffmpeg; Windows: winget install ffmpeg)")
    kinds = subprocess.run([fp, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True).stdout
    return "audio" in kinds


def ensure_audio(p: pathlib.Path) -> pathlib.Path:
    """Ролик без звука Telegram считает GIF и рвёт альбом — добавляем тихую дорожку."""
    if has_audio(p):
        return p
    ff = shutil.which("ffmpeg")
    TMP.mkdir(exist_ok=True)
    out = TMP / f"{p.stem}-audio.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(p), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-shortest", "-c:v", "copy", "-c:a", "aac", str(out)], check=True)
    return out


def sheet(paths: list[pathlib.Path], out: pathlib.Path, tile=(520, 347)) -> pathlib.Path:
    """Контакт-лист альбома для «Редакции»: номер и имя файла под каждым кадром."""
    cols = 2 if len(paths) <= 4 else 3
    rows = (len(paths) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * (tile[0] + 12), rows * (tile[1] + 12)), "#1C222C")
    draw = ImageDraw.Draw(canvas)
    for i, p in enumerate(paths):
        if str(p).lower().endswith(VIDEO):
            im = Image.new("RGB", tile, "#333333")
        else:
            im = Image.open(p).convert("RGB")
            im.thumbnail(tile)
        x, y = (i % cols) * (tile[0] + 12) + 6, (i // cols) * (tile[1] + 12) + 6
        canvas.paste(im, (x + (tile[0] - im.width) // 2, y + (tile[1] - im.height) // 2))
        draw.text((x + 8, y + tile[1] - 22), f"{i + 1} · {pathlib.Path(p).stem[:40]}", fill="white")
    canvas.save(out, "JPEG", quality=84)
    return out
