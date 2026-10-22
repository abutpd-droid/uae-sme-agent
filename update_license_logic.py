from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

start = s.find("def save_lead(record):")
end = s.find("\ndef score_lead(", start)

if start == -1 or end == -1:
    raise SystemExit("STOP: Could not locate save_lead().")

f = s[start:end]

if "trade_license_number" in f or "issuing_authority" in f:
    raise SystemExit("STOP: Licence fields already present. No changes made.")

old = '''    emirate = clean(record.get("emirate"))
    area = clean(record.get("area"))
    timestamp = now()
'''
new = '''    emirate = clean(record.get("emirate"))
    area = clean(record.get("area"))
    trade_license_number = clean(record.get("trade_license_number"))
    issuing_authority = clean(record.get("issuing_authority"))
    timestamp = now()
'''
if old not in f:
    raise SystemExit("STOP: Could not locate the expected fields.")

f = f.replace(old, new, 1)

old = '''    with connect_db() as conn:
        existing = conn.execute(
'''
new = '''    with connect_db() as conn:
        if trade_license_number and emirate and issuing_authority:
            licence_match = conn.execute(
                """
                SELECT id FROM leads
                WHERE lower(trim(trade_license_number)) = lower(trim(?))
                  AND lower(trim(emirate)) = lower(trim(?))
                  AND lower(trim(issuing_authority)) = lower(trim(?))
                LIMIT 1
                """,
                (trade_license_number, emirate, issuing_authority),
            ).fetchone()
            if licence_match:
                return "duplicate"

        existing = conn.execute(
'''
if old not in f:
    raise SystemExit("STOP: Could not locate the expected duplicate check.")

f = f.replace(old, new, 1)

old = '''                lead_status, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
'''
new = '''                lead_status, notes, created_at, updated_at,
                trade_license_number, issuing_authority
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
'''
if old not in f:
    raise SystemExit("STOP: Could not locate the expected INSERT columns.")

f = f.replace(old, new, 1)

old = '''                clean(record.get("notes")),
                timestamp,
                timestamp,
'''
new = '''                clean(record.get("notes")),
                timestamp,
                timestamp,
                trade_license_number,
                issuing_authority,
'''
if old not in f:
    raise SystemExit("STOP: Could not locate the expected INSERT values.")

f = f[:]
p.write_text(s[:start] + f + s[end:], encoding="utf-8")
print("SUCCESS: Updated save_lead() with trade licence duplicate detection.")