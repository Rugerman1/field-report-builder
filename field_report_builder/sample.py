"""The example day the window opens with, and sample photos for the self-test and docs."""

from __future__ import annotations

import os

from .model import Report

SAMPLE_TRANSCRIPT = (
    "October 15th, Highway 93 widening near Clemson. Weather was clear and cool in the morning, warming up "
    "after lunch. Palmetto Site Works had a foreman, four laborers and two operators on site for eight hours. "
    "Upstate Concrete had three finishers for six hours. Equipment on site: one CAT 320 excavator working all "
    "day, one skid steer, and a smooth drum roller that sat idle most of the day. Excavated and backfilled the "
    "storm drain trench from station 12+50 to 14+00, about 150 linear feet of 24 inch RCP installed. Poured "
    "the curb and gutter on the east side, about 18 cubic yards. Received six loads of number 57 stone. Ran a "
    "slump test on the second truck, four inch slump, and made one set of cylinders. Nuclear gauge density "
    "tests on the trench backfill all passed. Lost about an hour in the morning waiting on the first concrete "
    "truck. Found an unmarked water line at station 13+20, contractor stopped and called the utility, we need "
    "an RFI. Trench box was in place all day, one worker without a vest, talked to the foreman about it. Tom "
    "Reed from the county came by at 2 PM to look at the drainage."
)


def example_report() -> Report:
    return Report(
        project="SC 93 Widening, Phase 2", contract_no="P-0293-24", location="Clemson, SC",
        latitude=34.6834, longitude=-82.8374, contractor="Palmetto Site Works",
        inspector="Tyler Bowles", report_date="2026-10-15", report_no="42", transcript=SAMPLE_TRANSCRIPT,
    )


def make_sample_photos(folder: str) -> list[str]:
    """Draw two simple placeholder 'site photos' with EXIF time and GPS."""
    from PIL import Image, ImageDraw, ImageFont

    os.makedirs(folder, exist_ok=True)
    specs = [
        ("trench.jpg", "2026:10:15 10:42:05", (135, 180, 220), (120, 95, 70), "Storm drain trench, Sta. 13+00"),
        ("curb.jpg", "2026:10:15 14:18:40", (150, 190, 230), (165, 165, 160), "Curb and gutter pour, east side"),
    ]
    paths = []
    for name, when, sky, ground, label in specs:
        im = Image.new("RGB", (1200, 900), sky)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 480, 1200, 900], fill=ground)
        d.polygon([(0, 640), (1200, 560), (1200, 620), (0, 720)], fill=(90, 90, 90))
        d.rectangle([760, 380, 1000, 520], fill=(235, 170, 30))
        d.rectangle([700, 330, 790, 400], fill=(235, 170, 30))
        d.line([(860, 380), (1040, 250), (1120, 420)], fill=(60, 60, 60), width=14)
        try:
            font = ImageFont.load_default(size=38)
        except TypeError:  # Pillow < 10.1
            font = ImageFont.load_default()
        d.text((40, 40), "SAMPLE PHOTO", fill=(20, 20, 20), font=font)
        d.text((40, 90), label, fill=(20, 20, 20), font=font)
        exif = Image.Exif()
        exif[0x0110] = "Sample"
        exif.get_ifd(0x8769)[36867] = when
        gps = exif.get_ifd(0x8825)
        gps[1], gps[2], gps[3], gps[4] = "N", (34.0, 41.0, 0.24), "W", (82.0, 50.0, 14.64)
        path = os.path.join(folder, name)
        im.save(path, quality=88, exif=exif)
        paths.append(path)
    return paths
