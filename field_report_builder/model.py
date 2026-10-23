"""The daily report and everything that goes into it.

A report is saved as plain JSON (`.frb.json`) so it can be reopened, edited
and exported again.  Photo and memo paths are stored as given; the files
themselves are not copied.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field, fields

TEXT_SECTIONS = [
    ("materials", "Materials received"),
    ("tests", "Tests and inspections"),
    ("visitors", "Visitors"),
    ("issues", "Delays, problems and RFIs"),
    ("safety", "Safety"),
]


@dataclass
class CrewRow:
    contractor: str = ""
    trade: str = ""
    count: int = 0
    hours: float = 0.0


@dataclass
class EquipmentRow:
    description: str = ""
    count: int = 1
    status: str = "Working"  # Working, Idle or Down
    hours: float = 0.0


@dataclass
class WorkItem:
    description: str = ""
    location: str = ""
    quantity: str = ""


@dataclass
class Photo:
    path: str = ""
    taken: str | None = None  # ISO local time from EXIF
    latitude: float | None = None
    longitude: float | None = None
    caption: str = ""
    include: bool = True


@dataclass
class Weather:
    conditions_am: str = ""
    conditions_pm: str = ""
    temp_high_f: float | None = None
    temp_low_f: float | None = None
    temp_7am_f: float | None = None
    temp_noon_f: float | None = None
    temp_4pm_f: float | None = None
    precip_in: float | None = None
    wind_max_mph: float | None = None
    observed: str = ""  # what the inspector said about the weather
    source: str = ""

    def summary(self) -> str:
        parts = []
        if self.conditions_am or self.conditions_pm:
            if self.conditions_am == self.conditions_pm or not self.conditions_pm:
                parts.append(self.conditions_am)
            else:
                parts.append(f"AM {self.conditions_am}, PM {self.conditions_pm}")
        if self.temp_high_f is not None and self.temp_low_f is not None:
            parts.append(f"high {self.temp_high_f:.0f} F, low {self.temp_low_f:.0f} F")
        if self.precip_in is not None:
            parts.append(f"precip {self.precip_in:.2f} in")
        if self.wind_max_mph is not None:
            parts.append(f"wind to {self.wind_max_mph:.0f} mph")
        return "; ".join(p for p in parts if p)


@dataclass
class Report:
    project: str = ""
    contract_no: str = ""
    location: str = ""
    latitude: float | None = None
    longitude: float | None = None
    contractor: str = ""
    inspector: str = ""
    report_date: str = field(default_factory=lambda: dt.date.today().isoformat())
    report_no: str = ""
    weather: Weather = field(default_factory=Weather)
    crews: list[CrewRow] = field(default_factory=list)
    equipment: list[EquipmentRow] = field(default_factory=list)
    work: list[WorkItem] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    visitors: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    safety: list[str] = field(default_factory=list)
    remarks: str = ""
    transcript: str = ""
    memos: list[str] = field(default_factory=list)
    photos: list[Photo] = field(default_factory=list)

    @property
    def date(self) -> dt.date:
        return dt.date.fromisoformat(self.report_date)

    def total_workers(self) -> int:
        return sum(c.count for c in self.crews)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Report":
        d = dict(d)
        known = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in known}
        d["weather"] = _build(Weather, d.get("weather") or {})
        d["crews"] = [_build(CrewRow, r) for r in d.get("crews", [])]
        d["equipment"] = [_build(EquipmentRow, r) for r in d.get("equipment", [])]
        d["work"] = [_build(WorkItem, r) for r in d.get("work", [])]
        d["photos"] = [_build(Photo, r) for r in d.get("photos", [])]
        return cls(**d)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def load(cls, path: str) -> "Report":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def _build(kind, d: dict):
    known = {f.name for f in fields(kind)}
    return kind(**{k: v for k, v in d.items() if k in known})
