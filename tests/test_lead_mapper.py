import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lead_mapper as lm  # noqa: E402


def test_finds_nested_fields():
    raw = {"contact": {"name": "David Lee", "email": "d@x.com"}, "meta": {"source": "web"}}
    lead, problems = lm.map_lead(raw, lm.Result())
    assert lead["first_name"] == "David"
    assert lead["last_name"] == "Lee"
    assert lead["email"] == "d@x.com"
    assert lead["source"] == "Website"
    assert problems == []


def test_cleans_values():
    raw = {"full_name": "JOHN SMITH", "email": " John@Example.COM ", "phone": "(555) 123-4567", "source": "fb"}
    lead, _ = lm.map_lead(raw, lm.Result())
    assert lead["first_name"] == "John" and lead["last_name"] == "Smith"
    assert lead["email"] == "john@example.com"
    assert lead["phone"] == "5551234567"
    assert lead["source"] == "Facebook"


def test_keeps_international_plus():
    assert lm.clean_phone("+44 20 7946 0958") == "+442079460958"


def test_rejects_missing_or_invalid_email():
    _, p1 = lm.map_lead({"name": "A B"}, lm.Result())
    _, p2 = lm.map_lead({"name": "A B", "email": "a@b"}, lm.Result())
    assert "missing email" in p1
    assert any("invalid email" in p for p in p2)


def test_removes_duplicates_by_email():
    leads = [
        {"name": "John Smith", "email": "JOHN@x.com"},
        {"name": "John Smith", "email": "john@x.com"},
    ]
    result = lm.process(leads)
    assert len(result.accepted) == 1
    assert result.duplicates == 1


def test_sample_file_end_to_end(tmp_path):
    sample = Path(__file__).resolve().parent.parent / "sample_data" / "raw_leads.json"
    assert lm.main([str(sample), "--out", str(tmp_path)]) == 0
    csv_text = (tmp_path / "crm_ready_leads.csv").read_text()
    assert csv_text.count("\n") == 7  # header + 6 clean leads
    assert "needs_review.csv" in [p.name for p in tmp_path.iterdir()]
