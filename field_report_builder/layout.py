"""What goes on the page, shared by the Word and PDF exports.

The layout follows the usual DOT inspector's daily report: job header,
weather, contractor forces, equipment, work performed, then the shorter
sections, photos, and a signature block for the inspector and the
reviewing engineer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import TEXT_SECTIONS, Report
from .photos import sort_by_time, taken_label

TITLE = "DAILY WORK REPORT"


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list[str]]
    widths: list[float]  # fractions of the text width
    empty: str = "None reported."


@dataclass
class Bullets:
    title: str
    items: list[str]
    empty: str = "None reported."


def _f(v, fmt="{:.0f}", unit=""):
    return "" if v is None else fmt.format(v) + unit


def header_rows(r: Report) -> list[list[tuple[str, str]]]:
    d = r.date
    return [
        [("Project", r.project), ("Contract no.", r.contract_no)],
        [("Location", r.location), ("Date", f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}, {d.year}")],
        [("Prime contractor", r.contractor), ("Report no.", r.report_no)],
        [("Inspector", r.inspector), ("Workers on site", str(r.total_workers()) if r.crews else "")],
    ]


def weather_table(r: Report) -> Table:
    w = r.weather
    rows = [[
        w.conditions_am, w.conditions_pm,
        _f(w.temp_7am_f, unit=" F"), _f(w.temp_noon_f, unit=" F"), _f(w.temp_4pm_f, unit=" F"),
        (f"{w.temp_high_f:.0f} / {w.temp_low_f:.0f} F" if w.temp_high_f is not None and w.temp_low_f is not None
         else ""),
        _f(w.precip_in, "{:.2f}", " in"), _f(w.wind_max_mph, unit=" mph"),
    ]]
    if not any(rows[0]):
        rows = []
    return Table("Weather", ["AM", "PM", "7 AM", "Noon", "4 PM", "High / low", "Precip.", "Wind"], rows,
                 [0.17, 0.17, 0.09, 0.09, 0.09, 0.15, 0.12, 0.12], empty="Not recorded.")


def sections(r: Report) -> list[Table | Bullets]:
    out: list[Table | Bullets] = []
    out.append(Table("Contractor forces", ["Contractor", "Classification", "No.", "Hours"],
                     [[c.contractor, c.trade, str(c.count), f"{c.hours:g}" if c.hours else ""] for c in r.crews],
                     [0.42, 0.34, 0.1, 0.14]))
    out.append(Table("Equipment", ["Description", "No.", "Status", "Hours"],
                     [[e.description, str(e.count), e.status, f"{e.hours:g}" if e.hours else ""]
                      for e in r.equipment],
                     [0.52, 0.1, 0.2, 0.18]))
    out.append(Table("Work performed", ["Description", "Location", "Quantity"],
                     [[w.description, w.location, w.quantity] for w in r.work], [0.58, 0.24, 0.18]))
    for key, title in TEXT_SECTIONS:
        out.append(Bullets(title, list(getattr(r, key))))
    remarks = [x for x in (r.weather.observed and f"Weather on site: {r.weather.observed}", r.remarks) if x]
    out.append(Bullets("Remarks", remarks, empty="None."))
    return out


def report_photos(r: Report):
    """(number, photo, caption line) for every included photo, in time order."""
    items = []
    for i, p in enumerate(sort_by_time([p for p in r.photos if p.include]), start=1):
        when = taken_label(p)
        line = f"Photo {i}." + (f" {when}." if when else "") + (f" {p.caption}" if p.caption else "")
        items.append((i, p, line))
    return items


def weather_source_note(r: Report) -> str:
    if r.weather.source and r.latitude is not None and r.longitude is not None:
        return f"Weather from {r.weather.source} for {r.latitude:.4f}, {r.longitude:.4f}."
    return ""


SIGNATURES = [("Inspector", "inspector"), ("Reviewed by (Resident Engineer)", None)]
