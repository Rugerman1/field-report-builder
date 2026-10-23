"""Photo EXIF (time taken, GPS) and photo captions.

Phone photos carry the time they were taken and, usually, where.  The time
orders the photos in the report; the GPS fixes the site location for the
weather lookup.  Captions come from Claude looking at a downsized copy of
the photo, or from a plain template when there is no key.
"""

from __future__ import annotations

import datetime as dt
import io
import os

from PIL import Image, ImageOps

from . import claude
from .model import Photo

try:  # iPhone HEIC photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus", ".flac", ".wma", ".amr", ".3gp", ".mp4"}

EXIF_IFD = 0x8769
GPS_IFD = 0x8825


def is_photo(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in PHOTO_EXTS


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def _dms(value, ref) -> float | None:
    try:
        d, m, s = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    if str(ref).upper() in ("S", "W"):
        deg = -deg
    return round(deg, 6)


def read_photo(path: str) -> Photo:
    photo = Photo(path=path)
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            sub = exif.get_ifd(EXIF_IFD)
            stamp = sub.get(36867) or sub.get(36868) or exif.get(306)  # DateTimeOriginal, Digitized, DateTime
            if stamp:
                try:
                    photo.taken = dt.datetime.strptime(str(stamp).strip("\x00 "), "%Y:%m:%d %H:%M:%S").isoformat()
                except ValueError:
                    pass
            gps = exif.get_ifd(GPS_IFD)
            if gps and 2 in gps and 4 in gps:
                photo.latitude = _dms(gps[2], gps.get(1, "N"))
                photo.longitude = _dms(gps[4], gps.get(3, "E"))
    except (OSError, ValueError):
        pass
    if photo.taken is None:
        try:
            photo.taken = dt.datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0).isoformat()
        except OSError:
            pass
    return photo


def jpeg_bytes(path: str, max_px: int = 1600, quality: int = 85) -> bytes:
    """Upright (EXIF-rotated), downsized JPEG for the report and for Claude."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()


def taken_label(photo: Photo) -> str:
    if not photo.taken:
        return ""
    t = dt.datetime.fromisoformat(photo.taken)
    return t.strftime("%I:%M %p").lstrip("0")


def template_caption(photo: Photo) -> str:
    if photo.latitude is not None and photo.longitude is not None:
        return f"Site photo at {photo.latitude:.5f}, {photo.longitude:.5f}."
    return "Site photo."


CAPTION_SYSTEM = (
    "You caption photos for a construction inspector's daily work report. Write one factual sentence, "
    "at most 25 words, describing the work, equipment, materials or condition visible. Use the "
    "inspector's notes only to name things you can actually see (for example the station or the "
    "structure); never claim anything the photo does not show. No opening like 'This photo shows'. "
    "No em dashes."
)


def caption_with_claude(photo: Photo, notes: str) -> str:
    content = [
        claude.image_block(jpeg_bytes(photo.path, max_px=1024, quality=80)),
        {"type": "text", "text": (f"Photo taken at {taken_label(photo) or 'an unknown time'}.\n"
                                  f"Inspector's notes for the day:\n{notes[:4000]}")},
    ]
    resp = claude.call([{"role": "user", "content": content}], CAPTION_SYSTEM, max_tokens=120)
    text = claude.text_of(resp).strip().strip('"')
    if not text:
        raise claude.ClaudeError("Empty caption")
    return text


def caption_photos(photos: list[Photo], notes: str, overwrite: bool = False, progress=None) -> str:
    """Caption every photo without one.  Returns 'claude', 'template' or 'mixed'."""
    sources = set()
    use_claude = claude.api_key() is not None
    for i, photo in enumerate(photos):
        if progress:
            progress(f"Captioning photo {i + 1} of {len(photos)}")
        if photo.caption and not overwrite:
            continue
        if use_claude:
            try:
                photo.caption = caption_with_claude(photo, notes)
                sources.add("claude")
                continue
            except (claude.ClaudeError, OSError):
                pass
        photo.caption = template_caption(photo)
        sources.add("template")
    if len(sources) > 1:
        return "mixed"
    return sources.pop() if sources else "none"


def sort_by_time(photos: list[Photo]) -> list[Photo]:
    return sorted(photos, key=lambda p: (p.taken or "9999", p.path))
