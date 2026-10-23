import io
import json

from field_report_builder import claude, extract
from field_report_builder.model import Report
from field_report_builder.sample import SAMPLE_TRANSCRIPT


def test_sample_day_sorts_into_every_section():
    out = extract.extract_offline(SAMPLE_TRANSCRIPT)
    crews = {(c.contractor, c.trade): (c.count, c.hours) for c in out["crews"]}
    assert crews == {
        ("Palmetto Site Works", "Foreman"): (1, 8),
        ("Palmetto Site Works", "Laborer"): (4, 8),
        ("Palmetto Site Works", "Operator"): (2, 8),
        ("Upstate Concrete", "Finisher"): (3, 6),
    }
    eq = {e.description: e.status for e in out["equipment"]}
    assert eq == {"CAT 320 excavator": "Working", "Skid steer": "Working", "Smooth drum roller": "Idle"}
    assert [(w.location, w.quantity) for w in out["work"]] == [
        ("Sta. 12+50 to 14+00", "150 linear feet"), ("east side", "18 cubic yards")]
    assert len(out["tests"]) == 2 and "slump" in out["tests"][0]
    assert len(out["issues"]) == 2 and "RFI" in out["issues"][1]
    assert out["materials"] == ["Received six loads of number 57 stone."]
    assert "Tom Reed" in out["visitors"][0]
    assert "vest" in out["safety"][0]
    assert out["weather_observed"].startswith("Weather was clear")


def test_numbers_hours_and_stations():
    rows = extract.crews_in("Acme Paving had twelve laborers and a foreman out for nine and a half hours.")
    assert {(r.trade, r.count, r.hours) for r in rows} == {("Laborer", 12, 9.5), ("Foreman", 1, 9.5)}
    assert all(r.contractor == "Acme Paving" for r in rows)
    w = extract.work_item("Placed 42 tons of asphalt from sta 101 + 00 through station 104+50.")
    assert w.location == "Sta. 101+00 to 104+50"
    assert w.quantity == "42 tons"


def test_down_equipment_and_counts():
    rows = extract.equipment_in("Two dump trucks hauling, the backhoe was down with a hydraulic leak.")
    assert [(r.description, r.count, r.status) for r in rows] == [("Dump truck", 2, "Working"),
                                                                  ("Backhoe", 1, "Down")]


def test_head_count_in_a_safety_note_is_not_a_crew():
    out = extract.extract_offline("Two workers in the trench without hard hats, stopped work and fixed it.")
    assert out["crews"] == []


def test_fill_report_without_key_uses_rules():
    r = Report(transcript=SAMPLE_TRANSCRIPT)
    assert extract.fill_report(r) == "offline"
    assert r.total_workers() == 10
    assert r.weather.observed


def _fake_response(payload):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return Resp(json.dumps(payload).encode())


def test_fill_report_with_claude_tool_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = {}

    def fake_urlopen(req, timeout):
        sent.update(json.loads(req.data))
        return _fake_response({"content": [{"type": "tool_use", "name": "fill_daily_report", "input": {
            "crews": [{"contractor": "Palmetto Site Works", "trade": "Laborer", "count": "4", "hours": 8}],
            "equipment": [{"description": "Excavator", "count": 1, "status": "Sideways", "hours": 8}],
            "work": [{"description": "Installed 24 in RCP", "location": "Sta. 12+50 to 14+00", "quantity": "150 LF"}],
            "materials": [], "tests": ["Slump 4 in"], "visitors": [], "issues": "Unmarked water line",
            "safety": [], "weather_observed": "Clear", "remarks": ""}}]})

    monkeypatch.setattr(claude.urllib.request, "urlopen", fake_urlopen)
    r = Report(transcript="anything")
    assert extract.fill_report(r) == "claude"
    assert sent["tool_choice"] == {"type": "tool", "name": "fill_daily_report"}
    assert sent["model"] == claude.MODEL
    assert r.crews[0].count == 4
    assert r.equipment[0].status == "Working"  # unknown status coerced
    assert r.issues == ["Unmarked water line"]  # a bare string becomes a list
    assert r.work[0].quantity == "150 LF"


def test_claude_failure_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(req, timeout):
        raise OSError("offline")

    monkeypatch.setattr(claude.urllib.request, "urlopen", boom)
    r = Report(transcript=SAMPLE_TRANSCRIPT)
    assert extract.fill_report(r) == "offline"
    assert len(r.crews) == 4
