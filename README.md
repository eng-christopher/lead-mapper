# Lead Mapper — clean, CRM-ready leads from any source

Leads arrive from web forms, Facebook Lead Ads, Google Ads and landing-page tools, and every source names its fields differently. When they go straight into a CRM, records end up incomplete: missing emails, names in the wrong field, phones in five formats, duplicate contacts.

This Python script fixes that before the data reaches the CRM.

## What it does
- **Finds each field whatever the source called it** — `full_name`, `name`, `firstName`, or nested like `contact.email`
- **Splits full names** into first and last name
- **Cleans values** — lowercases emails, strips spaces, normalizes phones (keeps international `+`), standardizes sources (`fb` → `Facebook`)
- **Validates** required fields and catches invalid emails
- **Removes duplicates** by email
- **Never loses a lead** — anything that can't be fixed goes to a review file with the reason

## Result on the sample data
| | |
|---|---|
| Leads received | 10 |
| Ready for CRM | 6 |
| Sent for review (with reason) | 3 |
| Duplicates removed | 1 |

## How to run
```bash
python lead_mapper.py sample_data/raw_leads.json --out output
```
Outputs:
- `output/crm_ready_leads.csv` — import directly into the CRM
- `output/needs_review.csv` — leads with problems, and why
- `output/summary.txt` — what was received, fixed and rejected

Requires Python 3.9+. No external libraries.

## Adapting to a new source
Add the new field name to `FIELD_ALIASES` at the top of the script — no other change needed.

## Tests
```bash
python -m pytest tests
```
