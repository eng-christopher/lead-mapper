"""
Lead Mapper - normalizes leads coming from different sources into one CRM-ready format.

Problem it solves:
    Leads arrive from web forms, Facebook Lead Ads and landing-page tools.
    Each source names its fields differently ("full_name", "name", "first_name" + "last_name"),
    some nest the data ("contact": {"email": ...}), and some send messy values
    (uppercase emails, extra spaces, phones in any format). When this goes straight
    to the CRM, records arrive incomplete.

What it does:
    1. Reads a JSON file with raw leads (a list of objects).
    2. Finds each CRM field, whatever name or nesting level the source used.
    3. Cleans the values (name, email, phone, source).
    4. Validates required fields and separates leads that need review.
    5. Writes a CRM-ready CSV, a CSV of rejected leads with the reason,
       and a short summary report.

Usage:
    python lead_mapper.py sample_data/raw_leads.json --out output
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Field aliases: every name a source might use for each CRM field.
# Dotted paths ("contact.email") reach into nested objects.
# To support a new source, just add its field name to the right list.
# --------------------------------------------------------------------------- #
FIELD_ALIASES: dict[str, list[str]] = {
    "full_name": ["full_name", "name", "fullName", "contact.name", "lead.name"],
    "first_name": ["first_name", "firstName", "fname", "contact.first_name"],
    "last_name": ["last_name", "lastName", "lname", "contact.last_name"],
    "email": ["email", "email_address", "emailAddress", "e-mail", "contact.email", "lead.email"],
    "phone": ["phone", "phone_number", "phoneNumber", "mobile", "tel", "contact.phone"],
    "source": ["source", "lead_source", "utm_source", "origin", "channel", "meta.source"],
    "company": ["company", "company_name", "organization", "contact.company"],
}

SOURCE_NORMALIZATION = {
    "fb": "Facebook",
    "facebook": "Facebook",
    "facebook ads": "Facebook",
    "ig": "Instagram",
    "instagram": "Instagram",
    "google": "Google Ads",
    "google ads": "Google Ads",
    "adwords": "Google Ads",
    "website": "Website",
    "web": "Website",
    "landing page": "Website",
    "referral": "Referral",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")

CRM_COLUMNS = ["first_name", "last_name", "email", "phone", "company", "source"]


@dataclass
class Result:
    accepted: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    duplicates: int = 0
    fixes: dict[str, int] = field(default_factory=dict)

    def count_fix(self, name: str) -> None:
        self.fixes[name] = self.fixes.get(name, 0) + 1


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def get_path(data: dict[str, Any], path: str) -> Any:
    """Return the value at a dotted path like 'contact.email', or None."""
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def find_field(raw: dict[str, Any], crm_field: str) -> str:
    """Try every known alias for a CRM field and return the first non-empty value."""
    for alias in FIELD_ALIASES[crm_field]:
        value = get_path(raw, alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value.title() if value.isupper() or value.islower() else value


def clean_email(value: str) -> str:
    return value.strip().lower()


def clean_phone(value: str) -> str:
    """Keep digits and a leading '+'. '(555) 123-4567' -> '5551234567'."""
    value = value.strip()
    if not value:
        return ""
    plus = "+" if value.startswith("+") else ""
    return plus + re.sub(r"\D", "", value)


def clean_source(value: str) -> str:
    key = value.strip().lower()
    return SOURCE_NORMALIZATION.get(key, value.strip().title() if value else "Unknown")


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
def map_lead(raw: dict[str, Any], result: Result) -> tuple[dict[str, str], list[str]]:
    """Convert one raw lead into the CRM format. Returns (lead, problems)."""
    first = find_field(raw, "first_name")
    last = find_field(raw, "last_name")
    full = find_field(raw, "full_name")

    # Split a single "name" field into first/last when the source didn't send them apart.
    if not first and full:
        parts = re.sub(r"\s+", " ", full).strip().split(" ", 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""
        result.count_fix("name split into first/last")

    email_raw = find_field(raw, "email")
    email = clean_email(email_raw)
    if email != email_raw:
        result.count_fix("email cleaned (case/spaces)")

    phone_raw = find_field(raw, "phone")
    phone = clean_phone(phone_raw)
    if phone != phone_raw:
        result.count_fix("phone normalized")

    source_raw = find_field(raw, "source")
    source = clean_source(source_raw)
    if source != source_raw:
        result.count_fix("source standardized")

    lead = {
        "first_name": clean_name(first),
        "last_name": clean_name(last),
        "email": email,
        "phone": phone,
        "company": find_field(raw, "company"),
        "source": source,
    }

    problems = []
    if not lead["first_name"]:
        problems.append("missing name")
    if not email:
        problems.append("missing email")
    elif not EMAIL_RE.match(email):
        problems.append(f"invalid email '{email}'")
    return lead, problems


def process(raw_leads: list[dict[str, Any]]) -> Result:
    result = Result()
    seen_emails: set[str] = set()

    for index, raw in enumerate(raw_leads, start=1):
        if not isinstance(raw, dict):
            result.rejected.append({"row": str(index), "reason": "not a JSON object"})
            continue

        lead, problems = map_lead(raw, result)

        if problems:
            result.rejected.append({"row": str(index), "reason": "; ".join(problems), **lead})
            continue

        if lead["email"] in seen_emails:
            result.duplicates += 1
            continue
        seen_emails.add(lead["email"])
        result.accepted.append(lead)

    return result


def write_outputs(result: Result, out_dir: Path, total: int) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "crm_ready_leads.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CRM_COLUMNS)
        writer.writeheader()
        writer.writerows(result.accepted)

    with open(out_dir / "needs_review.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["row", "reason", *CRM_COLUMNS], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result.rejected)

    lines = [
        "LEAD MAPPER - SUMMARY",
        "=" * 40,
        f"Leads received:       {total}",
        f"Ready for CRM:        {len(result.accepted)}",
        f"Need review:          {len(result.rejected)}",
        f"Duplicates removed:   {result.duplicates}",
        "",
        "Automatic fixes applied:",
    ]
    lines += [f"  - {name}: {count}" for name, count in sorted(result.fixes.items())] or ["  - none"]
    if result.rejected:
        lines += ["", "Leads that need review:"]
        lines += [f"  - row {r['row']}: {r['reason']}" for r in result.rejected]
    report = "\n".join(lines)
    (out_dir / "summary.txt").write_text(report + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize raw leads into a CRM-ready CSV.")
    parser.add_argument("input", type=Path, help="JSON file with a list of raw leads")
    parser.add_argument("--out", type=Path, default=Path("output"), help="output folder")
    args = parser.parse_args(argv)

    try:
        raw_leads = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {args.input}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw_leads, list):
        print("Input must be a JSON list of lead objects.", file=sys.stderr)
        return 1

    result = process(raw_leads)
    print(write_outputs(result, args.out, len(raw_leads)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
