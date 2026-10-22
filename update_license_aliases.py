
from pathlib import Path

path = Path("app.py")
source = path.read_text(encoding="utf-8")

old = '''        "company": "company_name",
        "business_name": "company_name",'''

new = '''        "company": "company_name",
        "trade_license": "trade_license_number",
        "trade_licence": "trade_license_number",
        "trade_license_no": "trade_license_number",
        "trade_licence_no": "trade_license_number",
        "license_number": "trade_license_number",
        "licence_number": "trade_license_number",
        "license_no": "trade_license_number",
        "licence_no": "trade_license_number",
        "issuing_license_authority": "issuing_authority",
        "licensing_authority": "issuing_authority",
        "license_authority": "issuing_authority",
        "licence_authority": "issuing_authority",
        "business_name": "company_name",'''

if old not in source:
    raise SystemExit("STOP: Expected alias section not found. No changes made.")

if '"trade_license": "trade_license_number"' in source:
    raise SystemExit("STOP: Licence aliases may already exist. No changes made.")

source = source.replace(old, new, 1)
path.write_text(source, encoding="utf-8")
print("SUCCESS: Added trade licence CSV header aliases.")
