
from pathlib import Path

path = Path("app.py")
source = path.read_text(encoding="utf-8")

old_fields = '''CSV_FIELDS = [
    "company_name",
    "emirate",
    "area",
    "industry",
    "phone",
    "email",
    "website",
    "source",
    "verified_date",
    "services_of_interest",
    "lead_status",
    "notes",
]'''

new_fields = '''CSV_FIELDS = [
    "company_name",
    "emirate",
    "area",
    "trade_license_number",
    "issuing_authority",
    "industry",
    "phone",
    "email",
    "website",
    "source",
    "verified_date",
    "services_of_interest",
    "lead_status",
    "notes",
]'''

if old_fields not in source:
    raise SystemExit("STOP: CSV_FIELDS block did not match. No changes made.")

if '"trade_license_number"' in source[source.find("CSV_FIELDS"):source.find("CSV_FIELDS") + 600]:
    raise SystemExit("STOP: Trade licence fields may already be added. No changes made.")

source = source.replace(old_fields, new_fields, 1)
path.write_text(source, encoding="utf-8")
print("SUCCESS: CSV_FIELDS now includes trade licence number and issuing authority.")
