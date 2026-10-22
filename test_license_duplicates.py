import sqlite3

c = sqlite3.connect(":memory:")
c.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, company_name TEXT, emirate TEXT, area TEXT, trade_license_number TEXT, issuing_authority TEXT)")

def add(record):
    license_no = record["license"].strip().lower()
    emirate = record["emirate"].strip().lower()
    authority = record["authority"].strip().lower()

    if license_no and emirate and authority:
        found = c.execute(
            "SELECT id FROM leads WHERE lower(trim(trade_license_number))=? AND lower(trim(emirate))=? AND lower(trim(issuing_author