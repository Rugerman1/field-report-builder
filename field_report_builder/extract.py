"""Sort free-form dictation into daily report fields.

Two ways to do it:

* `extract_offline` is a rule-based sorter (regular expressions and keyword
  lists).  It needs nothing and is what the tests pin down.
* `extract_with_claude` sends the transcript to Claude with a forced tool
  call whose schema is the report.  Claude is told to use only what the
  inspector said and to keep their wording.

`fill_report` tries Claude when a key is set and falls back to the rules.
"""

from __future__ import annotations

import re

from . import claude
from .model import CrewRow, EquipmentRow, Report, WorkItem

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "half": 0.5,
}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"

TRADES = {
    "foreman": "Foreman", "foremen": "Foreman", "superintendent": "Superintendent",
    "laborer": "Laborer", "laborers": "Laborer", "labourer": "Laborer", "labourers": "Laborer",
    "operator": "Operator", "operators": "Operator", "carpenter": "Carpenter", "carpenters": "Carpenter",
    "finisher": "Finisher", "finishers": "Finisher", "ironworker": "Ironworker", "ironworkers": "Ironworker",
    "rodbuster": "Ironworker", "rodbusters": "Ironworker", "electrician": "Electrician",
    "electricians": "Electrician", "plumber": "Plumber", "plumbers": "Plumber",
    "pipe layer": "Pipe layer", "pipe layers": "Pipe layer", "pipelayer": "Pipe layer",
    "pipelayers": "Pipe layer", "surveyor": "Surveyor", "surveyors": "Surveyor",
    "truck driver": "Truck driver", "truck drivers": "Truck driver", "driver": "Truck driver",
    "drivers": "Truck driver", "mason": "Mason", "masons": "Mason", "welder": "Welder",
    "welders": "Welder", "flagger": "Flagger", "flaggers": "Flagger", "mechanic": "Mechanic",
    "mechanics": "Mechanic", "painter": "Painter", "painters": "Painter", "worker": "Worker",
    "workers": "Worker", "guys": "Worker", "men": "Worker",
}

EQUIPMENT = [
    "mini excavator", "excavator", "trackhoe", "backhoe", "skid steer", "bobcat", "front end loader",
    "wheel loader", "loader", "dozer", "bulldozer", "motor grader", "grader", "smooth drum roller",
    "sheepsfoot roller", "roller", "plate compactor", "jumping jack", "compactor", "paver",
    "milling machine", "dump truck", "water truck", "concrete pump", "pump truck", "crane",
    "boom lift", "scissor lift", "telehandler", "forklift", "trencher", "generator", "light tower",
    "air compressor", "compressor", "off road truck", "articulated truck", "vac truck", "hydroseeder",
]

WORK_VERBS = (
    "excavat|backfill|install|placed|place |poured|pour |formed|form |stripped|set |laid|paved|"
    "compact|graded|grading|fine grad|milled|milling|cleared|clearing|grubb|trench|dug|drilled|"
    "drove|driving piles|erected|welded|tied|sawcut|saw cut|cut |hauled|stockpil|seeded|mulch|"
    "stabiliz|demolish|removed|patched|sealed|striped|framed|built|constructed|finished|surveyed|"
    "staked|layout|proof roll|proofroll|tested the|worked on|continued|started|completed"
)

ISSUE_WORDS = (
    "delay|delayed|problem|issue|broke|broken|break down|broken down|down for|stopped|shut down|"
    "rained out|rain out|couldn't|could not|can't|cannot|waiting|waited|conflict|unmarked|damage|"
    "damaged|rework|redo|failed|fail |rfi|change order|discrepancy|no show|didn't show|"
    "did not show|late|leak|wash out|washed out|washout|standby"
)
SAFETY_WORDS = (
    "safety|hard hat|hardhat|ppe|vest|trench box|shoring|fall protection|harness|near miss|"
    "toolbox talk|tailgate talk|injur|first aid|traffic control|osha|guardrail|barricade|silt fence"
)
TEST_WORDS = (
    r"slump|cylinder|density|nuclear gauge|compaction test|proctor|air content|air test|"
    r"proof roll|proofroll|tested|testing|\btest\b|\btests\b|break test|core|dcp|pressure test"
)
VISITOR_WORDS = (
    r"visited|visitor|came by|stopped by|came out|met with|on site from|walked the site|"
    r"site visit|from the county|from the city|from scdot|from dot|inspector from|owner's rep"
)
MATERIAL_WORDS = (
    r"delivered|delivery|deliveries|received|loads of|truckloads|tons of|cubic yards of|"
    r"pallets of|shipment|came in"
)
WEATHER_WORDS = (
    r"weather|sunny|cloudy|overcast|clear and|rain|raining|drizzle|storm|windy|cold|hot|humid|"
    r"degrees|foggy|frost|freez"
)

QUANTITY_RE = re.compile(
    _NUM + r"\s+(cubic yards|cubic yard|cy|tons|ton|linear feet|linear foot|lf|feet|foot|ft|"
    r"square yards|square yard|sy|square feet|sf|each|ea|loads|gallons|gal|sticks|joints|pieces)\b",
    re.I,
)
STATION_RE = re.compile(r"\b(?:station|sta\.?)\s*(\d+\s*\+\s*\d+(?:\.\d+)?)"
                        r"(?:\s*(?:to|through|thru|-)\s*(?:station|sta\.?)?\s*(\d+\s*\+\s*\d+(?:\.\d+)?))?", re.I)
SIDE_RE = re.compile(r"\b(?:on|along) the ((?:north|south|east|west|left|right)(?:bound)?(?: side| shoulder| lane)?)\b",
                     re.I)
HOURS_RE = re.compile(_NUM + r"(?:\s+and a half)?\s+hours?\b", re.I)
COMPANY_RE = re.compile(r"((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|&|and|of))*?)\s+(?:had|has|brought|was out with|sent)\b")
FROM_COMPANY_RE = re.compile(r"\bfrom\s+((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|&))*)")

_trade_alt = "|".join(sorted((re.escape(t) for t in TRADES), key=len, reverse=True))
CREW_RE = re.compile(_NUM + r"\s+(?:[a-z]+\s+)?(" + _trade_alt + r")\b", re.I)
_equip_alt = "|".join(sorted((re.escape(e) for e in EQUIPMENT), key=len, reverse=True))
EQUIP_RE = re.compile(r"(?:\b" + _NUM + r"\s+)?((?:[A-Z][A-Za-z]*\s+)?(?:\d{2,4}[A-Z]?\s+)?)(" + _equip_alt + r")s?\b",
                      re.I)


def to_number(word: str) -> float:
    w = word.lower()
    if w in NUMBER_WORDS:
        return NUMBER_WORDS[w]
    return float(w)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    return [p.strip() for p in parts if p.strip()]


def _has(pattern: str, sentence: str) -> bool:
    return re.search(r"(?:" + pattern + r")", sentence, re.I) is not None


def _hours(sentence: str) -> float:
    m = HOURS_RE.search(sentence)
    if not m:
        return 0.0
    h = to_number(m.group(1))
    if "and a half" in m.group(0).lower():
        h += 0.5
    return float(h)


def crews_in(sentence: str) -> list[CrewRow]:
    rows = []
    company = ""
    m = COMPANY_RE.search(sentence) or FROM_COMPANY_RE.search(sentence)
    if m:
        company = m.group(1).strip()
        if company.split()[0].lower() in ("we", "they", "the", "i", "crew", "contractor"):
            company = ""
    hours = _hours(sentence)
    for m in CREW_RE.finditer(sentence):
        trade = TRADES[m.group(2).lower()]
        count = int(to_number(m.group(1)))
        if count < 1:
            continue
        rows.append(CrewRow(contractor=company, trade=trade, count=count, hours=hours))
    return rows


def equipment_in(sentence: str) -> list[EquipmentRow]:
    rows = []
    clauses = re.split(r",|;|\band\b|\bplus\b", sentence)
    for clause in clauses:
        for m in EQUIP_RE.finditer(clause):
            count = int(to_number(m.group(1))) if m.group(1) else 1
            prefix = (m.group(2) or "").strip()
            if prefix.lower() in NUMBER_WORDS or prefix.lower() in ("the", "our", "their", "on", "site"):
                prefix = ""
            desc = (prefix + " " + m.group(3)).strip()
            desc = desc[0].upper() + desc[1:]
            low = clause.lower()
            status = "Working"
            if re.search(r"\b(idle|standby|sat|parked|not used|unused)\b", low):
                status = "Idle"
            if re.search(r"\b(down|broke|broken|repair|leak)", low):
                status = "Down"
            rows.append(EquipmentRow(description=desc, count=max(count, 1), status=status, hours=_hours(clause)))
    return rows


def work_item(sentence: str) -> WorkItem:
    location = ""
    m = STATION_RE.search(sentence)
    if m:
        a = re.sub(r"\s+", "", m.group(1))
        location = f"Sta. {a}"
        if m.group(2):
            location += " to " + re.sub(r"\s+", "", m.group(2))
    side = SIDE_RE.search(sentence)
    if side:
        location = (location + ", " if location else "") + side.group(1).lower()
    qty = QUANTITY_RE.search(sentence)
    quantity = ""
    if qty:
        n = to_number(qty.group(1))
        quantity = f"{n:g} {qty.group(2).lower()}"
    return WorkItem(description=sentence.rstrip("."), location=location, quantity=quantity)


def classify(sentence: str) -> str:
    if _has(ISSUE_WORDS, sentence):
        return "issues"
    if _has(SAFETY_WORDS, sentence):
        return "safety"
    if _has(TEST_WORDS, sentence):
        return "tests"
    if _has(VISITOR_WORDS, sentence):
        return "visitors"
    if _has(MATERIAL_WORDS, sentence):
        return "materials"
    if _has(WORK_VERBS, sentence) or STATION_RE.search(sentence) or QUANTITY_RE.search(sentence):
        return "work"
    if _has(WEATHER_WORDS, sentence):
        return "weather"
    return "remarks"


def extract_offline(transcript: str) -> dict:
    """Return a dict of report fields (same keys as the Claude tool)."""
    out = {"crews": [], "equipment": [], "work": [], "materials": [], "tests": [], "visitors": [],
           "issues": [], "safety": [], "weather_observed": [], "remarks": []}
    for s in split_sentences(transcript):
        kind = classify(s)
        # A head count inside a safety note or a visitor line is not a crew.
        crews = crews_in(s) if kind in ("work", "remarks", "weather", "materials") else []
        equipment = equipment_in(s) if kind != "visitors" else []
        out["crews"] += crews
        out["equipment"] += equipment
        if (crews or equipment) and kind in ("work", "remarks") and not _has(WORK_VERBS, s):
            continue  # a pure "who and what was on site" sentence, already captured
        if (crews or equipment) and kind == "work" and not STATION_RE.search(s) and not QUANTITY_RE.search(s) \
                and re.search(r"\bon site\b|\bonsite\b|\bwere out\b", s, re.I):
            continue
        if kind == "work":
            out["work"].append(work_item(s))
        elif kind == "weather":
            out["weather_observed"].append(s)
        elif kind == "remarks":
            out["remarks"].append(s)
        else:
            out[kind].append(s)
    out["crews"] = _merge_crews(out["crews"])
    out["weather_observed"] = " ".join(out["weather_observed"])
    out["remarks"] = " ".join(out["remarks"])
    return out


def _merge_crews(rows: list[CrewRow]) -> list[CrewRow]:
    merged: dict[tuple[str, str], CrewRow] = {}
    for r in rows:
        key = (r.contractor.lower(), r.trade)
        if key in merged:
            merged[key].count = max(merged[key].count, r.count)
            merged[key].hours = max(merged[key].hours, r.hours)
        else:
            merged[key] = r
    return list(merged.values())


# ---------------------------------------------------------------- Claude

TOOL_NAME = "fill_daily_report"
SYSTEM = (
    "You fill in a construction inspector's daily work report from the inspector's own dictated "
    "notes (a speech-to-text transcript, so expect misheard words). Rules: use only what the "
    "inspector said and never invent crews, equipment, quantities, stations or names; keep the "
    "inspector's wording for descriptions, cleaned of filler words and obvious transcription errors; "
    "put each fact in exactly one section; if a count or hours were not said use 0; stations are "
    "written like 'Sta. 12+50 to 14+00'; leave a section empty when nothing fits. Call the tool once."
)


def tool_schema() -> dict:
    str_list = {"type": "array", "items": {"type": "string"}}
    return {
        "name": TOOL_NAME,
        "description": "Fill the sections of the daily work report.",
        "input_schema": {
            "type": "object",
            "properties": {
                "crews": {"type": "array", "description": "Contractor forces on site", "items": {
                    "type": "object", "properties": {
                        "contractor": {"type": "string"}, "trade": {"type": "string"},
                        "count": {"type": "integer"}, "hours": {"type": "number"}},
                    "required": ["contractor", "trade", "count", "hours"]}},
                "equipment": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "description": {"type": "string"}, "count": {"type": "integer"},
                        "status": {"type": "string", "enum": ["Working", "Idle", "Down"]},
                        "hours": {"type": "number"}},
                    "required": ["description", "count", "status", "hours"]}},
                "work": {"type": "array", "description": "Work performed today", "items": {
                    "type": "object", "properties": {
                        "description": {"type": "string"}, "location": {"type": "string"},
                        "quantity": {"type": "string"}},
                    "required": ["description", "location", "quantity"]}},
                "materials": {**str_list, "description": "Materials delivered or received"},
                "tests": {**str_list, "description": "Field tests and inspections with results"},
                "visitors": {**str_list, "description": "Visitors and who they were with"},
                "issues": {**str_list, "description": "Delays, problems, conflicts, RFIs, idle time"},
                "safety": {**str_list, "description": "Safety observations and actions"},
                "weather_observed": {"type": "string", "description": "What the inspector said about weather"},
                "remarks": {"type": "string", "description": "Anything else worth keeping"},
            },
            "required": ["crews", "equipment", "work", "materials", "tests", "visitors", "issues", "safety",
                         "weather_observed", "remarks"],
        },
    }


def extract_with_claude(transcript: str) -> dict:
    resp = claude.call(
        [{"role": "user", "content": "Inspector's notes for today:\n\n" + transcript}],
        SYSTEM, max_tokens=4000, tools=[tool_schema()], tool_choice={"type": "tool", "name": TOOL_NAME},
    )
    return normalize(claude.tool_input(resp, TOOL_NAME))


def normalize(d: dict) -> dict:
    """Coerce a tool result into the shape `extract_offline` returns."""
    def num(v, kind=float):
        try:
            return kind(v)
        except (TypeError, ValueError):
            return kind(0)

    def strs(v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    status_ok = {"Working", "Idle", "Down"}
    return {
        "crews": [CrewRow(str(r.get("contractor", "")), str(r.get("trade", "")), num(r.get("count"), int),
                          num(r.get("hours"))) for r in d.get("crews") or [] if isinstance(r, dict)],
        "equipment": [EquipmentRow(str(r.get("description", "")), max(num(r.get("count", 1), int), 1),
                                   r.get("status") if r.get("status") in status_ok else "Working",
                                   num(r.get("hours"))) for r in d.get("equipment") or [] if isinstance(r, dict)],
        "work": [WorkItem(str(r.get("description", "")), str(r.get("location", "")), str(r.get("quantity", "")))
                 for r in d.get("work") or [] if isinstance(r, dict)],
        "materials": strs(d.get("materials")), "tests": strs(d.get("tests")),
        "visitors": strs(d.get("visitors")), "issues": strs(d.get("issues")), "safety": strs(d.get("safety")),
        "weather_observed": str(d.get("weather_observed") or ""), "remarks": str(d.get("remarks") or ""),
    }


def apply(report: Report, fields_: dict) -> None:
    """Replace the dictation-derived sections of `report` with `fields_`."""
    report.crews = fields_["crews"]
    report.equipment = fields_["equipment"]
    report.work = fields_["work"]
    for key in ("materials", "tests", "visitors", "issues", "safety"):
        setattr(report, key, fields_[key])
    report.weather.observed = fields_["weather_observed"]
    report.remarks = fields_["remarks"]


def fill_report(report: Report, use_claude: bool = True) -> str:
    """Fill `report` from `report.transcript`.  Returns 'claude' or 'offline'."""
    if use_claude and claude.api_key():
        try:
            apply(report, extract_with_claude(report.transcript))
            return "claude"
        except claude.ClaudeError:
            pass
    apply(report, extract_offline(report.transcript))
    return "offline"
