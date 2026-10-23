import io

from PIL import Image

from field_report_builder import photos
from field_report_builder.sample import make_sample_photos


def test_exif_time_and_gps(tmp_path):
    p = photos.read_photo(make_sample_photos(str(tmp_path))[0])
    assert p.taken == "2026-10-15T10:42:05"
    assert (p.latitude, p.longitude) == (34.6834, -82.8374)
    assert photos.taken_label(p) == "10:42 AM"


def test_photo_without_exif_uses_file_time(tmp_path):
    path = tmp_path / "plain.png"
    Image.new("RGB", (40, 30), "gray").save(path)
    p = photos.read_photo(str(path))
    assert p.taken is not None and p.latitude is None
    assert photos.template_caption(p) == "Site photo."


def test_jpeg_bytes_turns_a_sideways_phone_photo_upright(tmp_path):
    path = tmp_path / "sideways.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 CW to display
    Image.new("RGB", (400, 300), "white").save(path, exif=exif)
    out = Image.open(io.BytesIO(photos.jpeg_bytes(str(path), max_px=200)))
    assert out.size == (150, 200)


def test_offline_captions_and_sorting(tmp_path):
    ps = [photos.read_photo(x) for x in reversed(make_sample_photos(str(tmp_path)))]
    assert photos.caption_photos(ps, "notes") == "template"
    assert all(p.caption.startswith("Site photo at 34.68") for p in ps)
    assert [p.taken[11:16] for p in photos.sort_by_time(ps)] == ["10:42", "14:18"]


def test_file_kinds():
    assert photos.is_photo("IMG_0001.HEIC") and photos.is_audio("New Recording 3.m4a")
    assert not photos.is_audio("notes.txt")
