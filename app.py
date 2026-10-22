import pandas as pd

import csv
import io
import sqlite3
from datetime import date, datetime
from pathlib import Path

import streamlit as st
import ollama

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "tasks.db"

EMIRATES = [
    "Abu Dhabi",
    "Dubai",
    "Sharjah",
    "Ajman",
    "Umm Al Quwain",
    "Ras Al Khaimah",
    "Fujairah",
]

INDUSTRIES = [
    "Retail",
    "Restaurant / Cafe",
    "Grocery / Supermarket",
    "Healthcare",
    "Real Estate",
    "Travel / Tourism",
    "Professional Services",
    "Typing Centre / Business Setup",
    "Logistics / Warehouse",
    "Hospitality",
    "Other",
]

LEAD_STATUSES = [
    "New",
    "Needs Verification",
    "Qualified",
    "Not a Fit",
    "Contacted - Authorized",
    "Do Not Contact",
]

SERVICE_VERTICALS = [
    "Telecom Solutions",
    "POS & Payment Solutions",
    "Flights & Corporate Travel",
    "Typing Centre & Business Setup",
]

PIPELINE_STAGES = [
    "New Lead",
    "Researching",
    "Verified",
    "Qualified",
    "Contact Eligible",
    "Approved for Outreach",
    "Contacted",
    "Follow-up",
    "Appointment",
    "Proposal",
    "Negotiation",
    "Won",
    "Lost",
]

CSV_FIELDS = [
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
]

st.set_page_config(
    page_title="UAE SME AI Command Centre",
    page_icon="🤖",
    layout="wide",
)


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Recorded',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                details TEXT NOT NULL,
                related_task_id INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                review_note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                emirate TEXT NOT NULL DEFAULT '',
                area TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                website TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                verified_date TEXT NOT NULL DEFAULT '',
                services_of_interest TEXT NOT NULL DEFAULT '',
                lead_status TEXT NOT NULL DEFAULT 'New',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(company_name, emirate, area)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                service_category TEXT NOT NULL,
                pipeline_stage TEXT NOT NULL DEFAULT 'New Lead',
                estimated_value REAL DEFAULT 0.0,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES leads (id) ON DELETE CASCADE
            )
            """
        )
        # Option B: Discovery Questionnaires Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovery_questionnaires (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                mobile_lines INTEGER DEFAULT 0,
                internet_speed TEXT NOT NULL DEFAULT '',
                pos_terminals INTEGER DEFAULT 0,
                annual_travel_budget REAL DEFAULT 0.0,
                licence_expiry_date TEXT NOT NULL DEFAULT '',
                special_requirements TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES leads (id) ON DELETE CASCADE
            )
            """
        )

        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        if "trade_license_number" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN trade_license_number TEXT NOT NULL DEFAULT ''")
        if "issuing_authority" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN issuing_authority TEXT NOT NULL DEFAULT ''")
        if "source_url" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
        if "confidence_level" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN confidence_level TEXT NOT NULL DEFAULT 'Unspecified'")
        if "research_status" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN research_status TEXT NOT NULL DEFAULT 'Pending'")


def audit(event, details, related_task_id=None):
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO audit_log
                (event, details, related_task_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event, details, related_task_id, now()),
        )


def save_task(command):
    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (command, status, created_at)
            VALUES (?, ?, ?)
            """,
            (command, "Recorded - Not Executed", now()),
        )
        task_id = cursor.lastrowid
    audit("TASK_CREATED", f"Task #{task_id} recorded", task_id)
    return task_id


def get_tasks():
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM tasks ORDER BY id DESC"
        ).fetchall()


def get_approvals(status=None):
    with connect_db() as conn:
        if status and status != "All":
            return conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE status = ? ORDER BY id DESC
                """,
                (status,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM approval_requests ORDER BY id DESC"
        ).fetchall()


def create_approval(action_type, description):
    with connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO approval_requests
                (action_type, description, status, created_at)
            VALUES (?, ?, 'Pending', ?)
            """,
            (action_type, description, now()),
        )
        request_id = cursor.lastrowid
    audit("APPROVAL_REQUEST_CREATED", f"Request #{request_id}; {action_type}")
    return request_id


def review_approval(request_id, decision, note):
    with connect_db() as conn:
        row = conn.execute(
            "SELECT status FROM approval_requests WHERE id = ?",
            (request_id,),
        ).fetchone()

        if row is None or row["status"] != "Pending":
            return False

        conn.execute(
            """
            UPDATE approval_requests
            SET status = ?, reviewed_at = ?, review_note = ?
            WHERE id = ? AND status = 'Pending'
            """,
            (decision, now(), note.strip(), request_id),
        )

    audit(
        "APPROVAL_REVIEWED",
        f"Request #{request_id}: {decision}. Note: {note.strip() or 'None'}",
    )
    return True


def get_audit_log():
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC"
        ).fetchall()


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def save_lead(record):
    company = clean(record.get("company_name"))
    if not company:
        return "skipped"

    emirate = clean(record.get("emirate"))
    area = clean(record.get("area"))
    trade_license_number = clean(record.get("trade_license_number"))
    issuing_authority = clean(record.get("issuing_authority"))
    timestamp = now()

    with connect_db() as conn:
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
            """
            SELECT id FROM leads
            WHERE lower(company_name) = lower(?)
              AND lower(emirate) = lower(?)
              AND lower(area) = lower(?)
            """,
            (company, emirate, area),
        ).fetchone()

        if existing:
            return "duplicate"

        conn.execute(
            """
            INSERT INTO leads (
                company_name, emirate, area, industry, phone, email,
                website, source, verified_date, services_of_interest,
                lead_status, notes, created_at, updated_at,
                trade_license_number, issuing_authority, source_url, confidence_level, research_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'Unspecified', 'Pending')
            """,
            (
                company,
                emirate,
                area,
                clean(record.get("industry")),
                clean(record.get("phone")),
                clean(record.get("email")),
                clean(record.get("website")),
                clean(record.get("source")),
                clean(record.get("verified_date")),
                clean(record.get("services_of_interest")),
                clean(record.get("lead_status")) or "New",
                clean(record.get("notes")),
                timestamp,
                timestamp,
                trade_license_number,
                issuing_authority,
            ),
        )

    audit("LEAD_CREATED", f"Lead added: {company} | {emirate} | {area}")
    return "added"


def get_opportunities(company_id=None):
    with connect_db() as conn:
        if company_id:
            return conn.execute(
                "SELECT * FROM service_opportunities WHERE company_id = ? ORDER BY id DESC",
                (company_id,)
            ).fetchall()
        return conn.execute(
            """
            SELECT so.*, l.company_name, l.emirate 
            FROM service_opportunities so
            JOIN leads l ON so.company_id = l.id
            ORDER BY so.id DESC
            """
        ).fetchall()


def save_opportunity(company_id, service_category, pipeline_stage, estimated_value, notes):
    ts = now()
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO service_opportunities 
                (company_id, service_category, pipeline_stage, estimated_value, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, service_category, pipeline_stage, estimated_value, notes.strip(), ts, ts)
        )
    audit("OPPORTUNITY_CREATED", f"Created {service_category} opportunity for company ID #{company_id}")


def update_opportunity_stage(opp_id, new_stage, notes):
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE service_opportunities 
            SET pipeline_stage = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_stage, notes.strip(), now(), opp_id)
        )
    audit("OPPORTUNITY_UPDATED", f"Opportunity #{opp_id} moved to stage: {new_stage}")


# Option B Helper Functions
def get_discovery_questionnaire(company_id):
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM discovery_questionnaires WHERE company_id = ?", (company_id,)
        ).fetchone()


def save_discovery_questionnaire(company_id, mobile_lines, internet_speed, pos_terminals, travel_budget, licence_expiry, special_reqs):
    ts = now()
    with connect_db() as conn:
        existing = conn.execute("SELECT id FROM discovery_questionnaires WHERE company_id = ?", (company_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE discovery_questionnaires
                SET mobile_lines = ?, internet_speed = ?, pos_terminals = ?, annual_travel_budget = ?,
                    licence_expiry_date = ?, special_requirements = ?, updated_at = ?
                WHERE company_id = ?
                """,
                (mobile_lines, internet_speed, pos_terminals, travel_budget, licence_expiry, special_reqs.strip(), ts, company_id)
            )
        else:
            conn.execute(
                """
                INSERT INTO discovery_questionnaires
                    (company_id, mobile_lines, internet_speed, pos_terminals, annual_travel_budget, licence_expiry_date, special_requirements, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (company_id, mobile_lines, internet_speed, pos_terminals, travel_budget, licence_expiry, special_reqs.strip(), ts)
            )
    audit("DISCOVERY_UPDATED", f"Updated discovery questionnaire for company ID #{company_id}")


def score_lead(lead):
    score = 0
    reasons = []

    industry = (lead["industry"] or "").strip()
    services = (lead["services_of_interest"] or "").strip()
    phone = (lead["phone"] or "").strip()
    email = (lead["email"] or "").strip()
    website = (lead["website"] or "").strip()
    source = (lead["source"] or "").strip()
    verified = (lead["verified_date"] or "").strip()
    status = (lead["lead_status"] or "New").strip()

    if industry and industry != "Other":
        score += 2
        reasons.append("Industry recorded (+2)")
    if services:
        score += 3
        reasons.append("Service interest recorded (+3)")
    if phone or email or website:
        score += 1
        reasons.append("Contact detail recorded (+1)")
    if source:
        score += 1
        reasons.append("Source recorded (+1)")

    verification_priority = "Verify first"
    if verified:
        try:
            verified_date = date.fromisoformat(verified)
            age_days = (date.today() - verified_date).days
            if 0 <= age_days <= 30:
                score += 2
                reasons.append("Verified within 30 days (+2)")
                verification_priority = "Ready for review"
            elif 31 <= age_days <= 90:
                score += 1
                reasons.append("Verified within 31–90 days (+1)")
                verification_priority = "Recheck recommended"
            else:
                reasons.append("Verification date is old or in the future")
        except ValueError:
            reasons.append("Verification date is invalid")

    if status == "Do Not Contact":
        verification_priority = "Exclude from outreach"
    elif status == "Not a Fit":
        verification_priority = "Low priority"
    elif verification_priority == "Verify first":
        pass
    elif score >= 7:
        verification_priority = "High priority"
    elif score >= 4:
        verification_priority = "Medium priority"
    else:
        verification_priority = "Low priority"

    return {
        "score": score,
        "priority": verification_priority,
        "reasons": reasons,
    }


def get_leads():
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM leads ORDER BY id DESC"
        ).fetchall()


def update_lead_status(lead_id, status):
    with connect_db() as conn:
        conn.execute(
            "UPDATE leads SET lead_status = ?, updated_at = ? WHERE id = ?",
            (status, now(), lead_id),
        )
    audit("LEAD_STATUS_UPDATED", f"Lead #{lead_id} status changed to {status}")


def update_lead_notes(lead_id, notes):
    with connect_db() as conn:
        conn.execute(
            "UPDATE leads SET notes = ?, updated_at = ? WHERE id = ?",
            (notes.strip(), now(), lead_id),
        )
    audit("LEAD_NOTES_UPDATED", f"Notes updated for lead #{lead_id}")


def query_local_ai(prompt):
    try:
        response = ollama.chat(
            model='llama3',
            messages=[{'role': 'user', 'content': prompt}]
        )
        return response['message']['content']
    except Exception as exc:
        return f"Could not connect to local Ollama instance: {exc}. Ensure Ollama is running in the background."


def normalize_header(header):
    header = clean(header).lower().strip().replace(" ", "_").replace("-", "_")
    aliases = {
        "company": "company_name",
        "business_name": "company_name",
        "name": "company_name",
        "trade_license": "trade_license_number",
        "trade_licence": "trade_license_number",
        "trade_license_no": "trade_license_number",
        "trade_licence_no": "trade_license_number",
        "trade_license_number": "trade_license_number",
        "trade_licence_number": "trade_license_number",
        "license_number": "trade_license_number",
        "licence_number": "trade_license_number",
        "license_no": "trade_license_number",
        "licence_no": "trade_license_number",
        "issuing_license_authority": "issuing_authority",
        "issuing_licence_authority": "issuing_authority",
        "licensing_authority": "issuing_authority",
        "license_authority": "issuing_authority",
        "licence_authority": "issuing_authority",
        "issuing_authority": "issuing_authority",
        "location": "area",
        "city": "area",
        "phone_number": "phone",
        "telephone": "phone",
        "email_address": "email",
        "url": "website",
        "industry_category": "industry",
        "lead_source": "source",
        "verification_date": "verified_date",
        "services": "services_of_interest",
        "status": "lead_status",
    }
    return aliases.get(header, header)


initialize_database()

st.title("UAE SME AI Command Centre")
st.caption("Local-first business development and customer support workspace")

st.info(
    "Local prototype. Data is stored in tasks.db on this PC. "
    "Outbound messaging and automatic execution remain disabled."
)

tasks = get_tasks()
leads = get_leads()
pending_approvals = get_approvals("Pending")
audit_entries = get_audit_log()

overview, commands, history, lead_tab, prospecting_dashboard, research_tab, service_pipelines_tab, reports_tab, qualification, ai_tab, approvals, audit_tab, safety = st.tabs(
    [
        "Overview",
        "Command Centre",
        "Task History",
        "SME Lead Manager",
        "Prospecting Dashboard",
        "Compliant Research",
        "Service Pipelines",
        "Revenue Reports",
        "Lead Qualification",
        "Local AI Assistant",
        "Approval Queue",
        "Audit Log",
        "Safety",
    ]
)

with overview:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saved tasks", len(tasks))
    c2.metric("Business leads", len(leads))
    c3.metric("Pending approvals", len(pending_approvals))
    c4.metric("Local AI Status", "Llama 3 Ready")

    st.subheader("Development roadmap")
    st.markdown(
        """
        - Milestone 1: Local dashboard
        - Milestone 2: Persistent task history
        - Milestone 3: Audit log and approval records
        - Milestone 4: SME lead management
        - Phase 3: Prospecting Dashboard & Analytics (Interactive)
        - Phase 4: Local offline AI integration (Llama 3)
        - Phase 5: Compliant research & source URLs
        - Path B: Multi-Service Pipelines active
        - Option A: Multilingual AI Prompt Engine (8 Languages) active
        - Option B: Structured B2B Discovery Questionnaires active
        - Option C: Revenue Forecasting & Custom Reports active
        """
    )

with commands:
    st.subheader("Record an instruction")
    with st.form("task_form", clear_on_submit=True):
        command = st.text_area(
            "Instruction",
            placeholder=(
                "Example: Review an authorized list of UAE SMEs "
                "that may need business telecom or POS services."
            ),
            height=120,
        )
        submit_task = st.form_submit_button("Save instruction")

    if submit_task:
        if command.strip():
            task_id = save_task(command.strip())
            st.success(f"Task #{task_id} saved. It has not been executed.")
            st.rerun()
        else:
            st.error("Enter an instruction first.")

    st.divider()
    st.subheader("Propose an action for review")
    with st.form("approval_form", clear_on_submit=True):
        action_type = st.selectbox(
            "Action type",
            ["Research", "Prepare customer reply", "Prepare outreach draft", "Other"],
        )
        description = st.text_area("Describe the proposed action")
        submit_approval = st.form_submit_button("Add to approval queue")

    if submit_approval:
        if description.strip():
            request_id = create_approval(action_type, description.strip())
            st.success(f"Request #{request_id} recorded. Nothing was executed.")
            st.rerun()
        else:
            st.error("Describe the proposed action first.")

with history:
    st.subheader("Task History")
    if not tasks:
        st.info("No saved tasks yet.")
    else:
        for task in tasks:
            with st.expander(f"Task #{task['id']} — {task['created_at']}"):
                st.write("**Instruction**")
                st.write(task["command"])
                st.write("**Status**")
                st.write(task["status"])

with lead_tab:
    st.subheader("SME Lead Manager")
    st.caption(
        "Import only data you are authorized to use. Public visibility does not "
        "automatically mean permission to collect or market to a business."
    )

    add_tab, import_tab, browse_tab, discovery_tab, export_tab = st.tabs(
        ["Add a lead", "Import CSV", "Browse and qualify", "B2B Discovery Form", "Export"]
    )

    with add_tab:
        with st.form("add_lead_form", clear_on_submit=True):
            company_name = st.text_input("Company name *")
            c1, c2 = st.columns(2)
            emirate = c1.selectbox("Emirate", [""] + EMIRATES)
            area = c2.text_input("Area / locality")
            trade_license_number = st.text_input("Trade licence number (optional)")
            issuing_authority = st.text_input("Issuing authority (optional)")
            industry = st.selectbox("Industry", [""] + INDUSTRIES)
            c3, c4 = st.columns(2)
            phone = c3.text_input("Business phone (optional)")
            email = c4.text_input("Business email (optional)")
            website = st.text_input("Website (optional)")
            source = st.text_input("Source / reference *")
            verified_date = st.date_input(
                "Date verified (leave as today only if checked today)",
                value=None,
            )
            services = st.multiselect(
                "Potential service interest",
                [
                    "Business mobile / postpaid",
                    "Business internet / fibre",
                    "Landline",
                    "POS",
                    "Not assessed",
                ],
            )
            status = st.selectbox("Lead status", LEAD_STATUSES)
            notes = st.text_area("Notes (avoid unnecessary personal data)")
            add_submitted = st.form_submit_button("Save lead")

        if add_submitted:
            if not company_name.strip() or not source.strip():
                st.error("Company name and source are required.")
            else:
                record = {
                    "company_name": company_name,
                    "emirate": emirate,
                    "area": area,
                    "trade_license_number": trade_license_number,
                    "issuing_authority": issuing_authority,
                    "industry": industry,
                    "phone": phone,
                    "email": email,
                    "website": website,
                    "source": source,
                    "verified_date": verified_date.isoformat() if verified_date else "",
                    "services_of_interest": ", ".join(services),
                    "lead_status": status,
                    "notes": notes,
                }
                try:
                    result = save_lead(record)
                    if result == "added":
                        st.success("Lead saved.")
                        st.rerun()
                    else:
                        st.warning(
                            "A likely duplicate exists based on trade licence details "
                            "or company, emirate, and area. Review the existing record first."
                        )
                except sqlite3.IntegrityError:
                    st.warning("This lead appears to be a duplicate.")

    with import_tab:
        st.write("Upload a CSV to preview and validate records before importing.")
        st.write("Trade licence duplicates are checked using licence number, emirate, and issuing authority, and compared against existing database records.")

        uploaded = st.file_uploader("Choose a CSV file", type=["csv"], key="csv_preview_upload")

        if uploaded is not None:
            try:
                decoded = uploaded.getvalue().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(decoded))

                if not reader.fieldnames:
                    st.error("The CSV needs a header row.")
                else:
                    mapped_headers = {
                        header: normalize_header(header)
                        for header in reader.fieldnames
                    }
                    raw_rows = list(reader)
                    st.write("Detected columns:", list(mapped_headers.values()))
                    st.write(f"Rows found: {len(raw_rows)}")

                    with connect_db() as conn:
                        db_leads = conn.execute(
                            "SELECT company_name, emirate, area, trade_license_number, issuing_authority FROM leads"
                        ).fetchall()

                    db_licences = set()
                    db_companies = set()
                    for db_lead in db_leads:
                        dl = clean(db_lead["trade_license_number"]).casefold()
                        de = clean(db_lead["emirate"]).casefold()
                        da = clean(db_lead["issuing_authority"]).casefold()
                        if dl and de and da:
                            db_licences.add((dl, de, da))
                        
                        dc = clean(db_lead["company_name"]).casefold()
                        d_emirate = clean(db_lead["emirate"]).casefold()
                        d_area = clean(db_lead["area"]).casefold()
                        if dc:
                            db_companies.add((dc, d_emirate, d_area))

                    preview_records = []
                    seen_licences = set()
                    seen_companies = set()
                    missing_names = 0
                    file_duplicates = 0
                    db_duplicates = 0

                    for row_number, raw in enumerate(raw_rows, start=2):
                        record = {}
                        for original, value in raw.items():
                            target = mapped_headers.get(original, "")
                            if target in CSV_FIELDS:
                                record[target] = value or ""

                        company = clean(record.get("company_name"))
                        emirate_value = clean(record.get("emirate")).casefold()
                        area_value = clean(record.get("area")).casefold()
                        licence = clean(record.get("trade_license_number")).casefold()
                        authority = clean(record.get("issuing_authority")).casefold()

                        issues = []
                        if not company:
                            issues.append("Missing company name")
                            missing_names += 1

                        licence_key = (licence, emirate_value, authority)
                        company_key = (company.casefold(), emirate_value, area_value)

                        is_db_dup = False
                        if licence and emirate_value and authority and licence_key in db_licences:
                            issues.append("Duplicate licence in database")
                            is_db_dup = True
                        if company and company_key in db_companies:
                            issues.append("Duplicate company/emirate/area in database")
                            is_db_dup = True

                        if is_db_dup:
                            db_duplicates += 1

                        if licence and emirate_value and authority:
                            if licence_key in seen_licences:
                                issues.append("Duplicate licence within file")
                                file_duplicates += 1
                            seen_licences.add(licence_key)

                        if company:
                            if company_key in seen_companies:
                                issues.append("Duplicate company/emirate/area within file")
                                file_duplicates += 1
                            seen_companies.add(company_key)

                        preview = dict(record)
                        preview["CSV row"] = row_number
                        preview["Preview warnings"] = "; ".join(issues) if issues else "None detected"
                        preview_records.append(preview)

                    if preview_records:
                        st.subheader("CSV preview")
                        st.dataframe(
                            pd.DataFrame(preview_records),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.warning("This CSV contains no data rows.")

                    st.write(f"Rows missing company names: {missing_names}")
                    st.write(f"Potential duplicate rows within this file: {file_duplicates}")
                    st.write(f"Potential duplicate rows matching existing database: {db_duplicates}")
                    st.warning(
                        "This preview checks duplicates against both the uploaded file and existing database records before import."
                    )

                    authorized = st.checkbox(
                        "I confirm I am authorized to import this data",
                        key="csv_authorized",
                    )
                    confirm_preview = st.checkbox(
                        "I reviewed the preview and want to proceed with the import",
                        key="csv_preview_confirmed",
                    )

                    if st.button(
                        "Import CSV rows",
                        disabled=not (authorized and confirm_preview and bool(raw_rows)),
                    ):
                        added = 0
                        duplicates = 0
                        skipped = 0
                        errors = 0

                        for preview in preview_records:
                            record = {
                                field: preview.get(field, "")
                                for field in CSV_FIELDS
                            }

                            try:
                                outcome = save_lead(record)
                                if outcome == "added":
                                    added += 1
                                elif outcome == "duplicate":
                                    duplicates += 1
                                else:
                                    skipped += 1
                            except (sqlite3.Error, ValueError):
                                errors += 1

                        audit(
                            "CSV_IMPORT_COMPLETED",
                            f"File: {uploaded.name}; rows: {len(raw_rows)}; "
                            f"added: {added}; duplicates: {duplicates}; "
                            f"skipped: {skipped}; errors: {errors}",
                        )
                        st.success(
                            f"Import finished: added {added}; "
                            f"duplicates: {duplicates}; skipped: {skipped}; "
                            f"errors: {errors}."
                        )
                        st.rerun()

            except UnicodeDecodeError:
                st.error("Could not read this file as UTF-8 CSV. Save it as CSV UTF-8 and try again.")
            except Exception as exc:
                st.error(f"Could not read the CSV: {exc}")

    with browse_tab:
        current_leads = get_leads()
        if not current_leads:
            st.info("No leads yet. Add a lead or import an authorized CSV.")
        else:
            f1, f2, f3 = st.columns(3)
            search_text = f1.text_input("Search company, area, phone, email")
            emirate_filter = f2.selectbox("Filter emirate", ["All"] + EMIRATES)
            status_filter = f3.selectbox("Filter status", ["All"] + LEAD_STATUSES)

            filtered = []
            for lead in current_leads:
                haystack = " ".join(
                    [
                        lead["company_name"], lead["area"], lead["phone"],
                        lead["email"], lead["industry"], lead["website"],
                    ]
                ).lower()

                if search_text.strip().lower() not in haystack:
                    continue
                if emirate_filter != "All" and lead["emirate"] != emirate_filter:
                    continue
                if status_filter != "All" and lead["lead_status"] != status_filter:
                    continue
                filtered.append(lead)

            st.write(f"{len(filtered)} matching lead(s)")
            for lead in filtered:
                with st.expander(
                    f"{lead['company_name']} — {lead['emirate'] or 'Emirate unknown'} "
                    f"— {lead['lead_status']}"
                ):
                    st.write(f"**Area:** {lead['area'] or 'Not provided'}")
                    st.write(f"**Industry:** {lead['industry'] or 'Not provided'}")
                    st.write(f"**Phone:** {lead['phone'] or 'Not provided'}")
                    st.write(f"**Email:** {lead['email'] or 'Not provided'}")
                    st.write(f"**Website:** {lead['website'] or 'Not provided'}")
                    st.write(f"**Source:** {lead['source'] or 'Not provided'}")
                    st.write(f"**Source URL:** {lead['source_url'] or 'Not logged'}")
                    st.write(f"**Confidence Level:** {lead['confidence_level'] or 'Unspecified'}")
                    st.write(f"**Research Status:** {lead['research_status'] or 'Pending'}")
                    st.write(f"**Verified date:** {lead['verified_date'] or 'Not verified'}")
                    st.write(f"**Services of interest:** {lead['services_of_interest'] or 'Not assessed'}")
                    st.write(f"**Notes:** {lead['notes'] or 'None'}")

                    new_status = st.selectbox(
                        "Update lead status",
                        LEAD_STATUSES,
                        index=(
                            LEAD_STATUSES.index(lead["lead_status"])
                            if lead["lead_status"] in LEAD_STATUSES else 0
                        ),
                        key=f"status_{lead['id']}",
                    )
                    new_notes = st.text_area(
                        "Update notes",
                        value=lead["notes"],
                        key=f"notes_{lead['id']}",
                    )

                    if st.button("Save lead changes", key=f"save_{lead['id']}"):
                        if new_status != lead["lead_status"]:
                            update_lead_status(lead["id"], new_status)
                        if new_notes != lead["notes"]:
                            update_lead_notes(lead["id"], new_notes)
                        st.success("Changes saved.")
                        st.rerun()

    # Option B: Structured B2B Discovery Questionnaire Tab
    with discovery_tab:
        st.write("### Structured B2B Needs Discovery Questionnaire")
        st.caption("Record detailed requirement parameters across Telecom, POS, Travel, and Licensing.")

        disc_leads = get_leads()
        if not disc_leads:
            st.info("No leads available. Add a lead first.")
        else:
            disc_choices = {f"{l['company_name']} ({l['emirate']})": l for l in disc_leads}
            selected_disc_key = st.selectbox("Select Company for Discovery", list(disc_choices.keys()), key="disc_company_select")
            disc_lead = disc_choices[selected_disc_key]

            existing_disc = get_discovery_questionnaire(disc_lead["id"])

            with st.form("discovery_form"):
                st.subheader(f"Requirements: {disc_lead['company_name']}")

                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    m_lines = st.number_input("Mobile SIMs / Postpaid Lines Needed", min_value=0, value=existing_disc["mobile_lines"] if existing_disc else 0)
                    i_speed = st.selectbox("Internet / Fibre Speed Needed", ["None / Existing", "50 Mbps", "100 Mbps", "250 Mbps", "500 Mbps + Dedicated Fibre"], index=0)
                    p_terminals = st.number_input("POS Terminals Needed", min_value=0, value=existing_disc["pos_terminals"] if existing_disc else 0)

                with d_col2:
                    t_budget = st.number_input("Annual Corporate Travel Budget (AED)", min_value=0.0, step=1000.0, value=existing_disc["annual_travel_budget"] if existing_disc else 0.0)
                    l_expiry = st.date_input("Trade Licence Expiry Date", value=None)
                    spec_reqs = st.text_area("Special Notes / Hardware Requirements", value=existing_disc["special_requirements"] if existing_disc else "")

                save_disc_btn = st.form_submit_button("Save Discovery Questionnaire")

            if save_disc_btn:
                save_discovery_questionnaire(
                    disc_lead["id"],
                    m_lines,
                    i_speed,
                    p_terminals,
                    t_budget,
                    l_expiry.isoformat() if l_expiry else "",
                    spec_reqs
                )
                st.success("Discovery details saved successfully!")
                st.rerun()

    with export_tab:
        export_leads = get_leads()
        if not export_leads:
            st.info("There are no leads to export.")
        else:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for lead in export_leads:
                writer.writerow({field: lead[field] for field in CSV_FIELDS})

            st.download_button(
                "Download all leads as CSV",
                data=output.getvalue().encode("utf-8-sig"),
                file_name="uae_sme_leads.csv",
                mime="text/csv",
            )
            st.caption(
                "Exports all saved leads. Check your permissions before sharing "
                "or using the exported data."
            )

with prospecting_dashboard:
    st.subheader("Prospecting Analytics & Pipeline Dashboard")
    st.caption("Interactive overview of lead distributions, pipeline stages, contact health, and follow-up priorities.")

    all_dashboard_leads = get_leads()
    if not all_dashboard_leads:
        st.info("No saved leads yet. Add or import leads to populate the dashboard.")
    else:
        st.markdown("### Interactive Filters")
        f_col1, f_col2 = st.columns(2)
        selected_dash_emirate = f_col1.selectbox("Filter Dashboard by Emirate", ["All"] + EMIRATES, key="dash_emirate_filter")
        selected_dash_industry = f_col2.selectbox("Filter Dashboard by Industry", ["All"] + INDUSTRIES, key="dash_industry_filter")

        filtered_dash_leads = []
        for l in all_dashboard_leads:
            if selected_dash_emirate != "All" and l["emirate"] != selected_dash_emirate:
                continue
            if selected_dash_industry != "All" and l["industry"] != selected_dash_industry:
                continue
            filtered_dash_leads.append(l)

        st.write(f"Showing analytics for **{len(filtered_dash_leads)}** matching lead(s) out of {len(all_dashboard_leads)} total.")
        st.divider()

        if not filtered_dash_leads:
            st.warning("No leads match the selected interactive filters.")
        else:
            total_leads_count = len(filtered_dash_leads)
            qualified_leads_count = sum(1 for l in filtered_dash_leads if l["lead_status"] == "Qualified")
            needs_verification_count = sum(1 for l in filtered_dash_leads if l["lead_status"] == "Needs Verification" or not l["verified_date"])
            
            stale_count = 0
            today_date = date.today()
            for l in filtered_dash_leads:
                v_date = l["verified_date"]
                if not v_date:
                    stale_count += 1
                else:
                    try:
                        d_obj = date.fromisoformat(v_date)
                        if (today_date - d_obj).days > 90:
                            stale_count += 1
                    except ValueError:
                        stale_count += 1

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Filtered Leads", total_leads_count)
            m2.metric("Qualified Pipeline", qualified_leads_count)
            m3.metric("Needs Verification", needs_verification_count)
            m4.metric("Stale / Unverified", stale_count)

            st.divider()

            col_emirate, col_industry, col_status = st.columns(3)

            with col_emirate:
                st.markdown("### Leads by Emirate")
                emirate_counts = {}
                for l in filtered_dash_leads:
                    em = l["emirate"] or "Unspecified"
                    emirate_counts[em] = emirate_counts.get(em, 0) + 1
                df_emirate = pd.DataFrame(list(emirate_counts.items()), columns=["Emirate", "Count"]).sort_values(by="Count", ascending=False)
                st.dataframe(df_emirate, use_container_width=True, hide_index=True)

            with col_industry:
                st.markdown("### Leads by Industry")
                industry_counts = {}
                for l in filtered_dash_leads:
                    ind = l["industry"] or "Unspecified"
                    industry_counts[ind] = industry_counts.get(ind, 0) + 1
                df_industry = pd.DataFrame(list(industry_counts.items()), columns=["Industry", "Count"]).sort_values(by="Count", ascending=False)
                st.dataframe(df_industry, use_container_width=True, hide_index=True)

            with col_status:
                st.markdown("### Lead Status Pipeline")
                status_counts = {}
                for l in filtered_dash_leads:
                    st_val = l["lead_status"] or "New"
                    status_counts[st_val] = status_counts.get(st_val, 0) + 1
                df_status = pd.DataFrame(list(status_counts.items()), columns=["Status", "Count"]).sort_values(by="Count", ascending=False)
                st.dataframe(df_status, use_container_width=True, hide_index=True)

            st.divider()

            st.markdown("### Contact Health & Follow-up Priorities")
            st.caption("Filtered leads missing key contact details or flagged as stale.")

            health_records = []
            for l in filtered_dash_leads:
                has_phone = bool(l["phone"].strip())
                has_email = bool(l["email"].strip())
                has_web = bool(l["website"].strip())
                
                missing_parts = []
                if not has_phone: missing_parts.append("Phone")
                if not has_email: missing_parts.append("Email")
                if not has_web: missing_parts.append("Website")

                v_date = l["verified_date"]
                stale_status = "OK"
                if not v_date:
                    stale_status = "Never verified"
                else:
                    try:
                        d_obj = date.fromisoformat(v_date)
                        if (today_date - d_obj).days > 90:
                            stale_status = "Stale (> 90 days)"
                    except ValueError:
                        stale_status = "Invalid date"

                health_records.append({
                    "Company": l["company_name"],
                    "Emirate": l["emirate"] or "Unspecified",
                    "Status": l["lead_status"],
                    "Missing Contact Info": ", ".join(missing_parts) if missing_parts else "Complete",
                    "Verification Health": stale_status,
                    "Verified Date": v_date or "None"
                })

            df_health = pd.DataFrame(health_records)
            st.dataframe(df_health, use_container_width=True, hide_index=True)

            st.download_button(
                label="Download Filtered Contact Health Report (CSV)",
                data=df_health.to_csv(index=False).encode("utf-8-sig"),
                file_name="uae_sme_filtered_contact_health_report.csv",
                mime="text/csv"
            )

with research_tab:
    st.subheader("Compliant Research & Lead Enrichment")
    st.caption("Perform manual, authorized research using official public directories, Google Maps, and government registries. Always log source URLs and verification evidence.")

    research_leads = get_leads()
    if not research_leads:
        st.info("No leads available for research enrichment. Add a lead in SME Lead Manager first.")
    else:
        lead_choices = {f"{l['company_name']} ({l['emirate']})": l for l in research_leads}
        selected_lead_key = st.selectbox("Select lead to enrich / research", list(lead_choices.keys()), key="research_lead_select")
        target_lead = dict(lead_choices[selected_lead_key]) # Converted to standard dictionary

        with st.form("research_enrichment_form"):
            st.write(f"**Target Company:** {target_lead['company_name']}")
            st.write(f"**Current Emirate & Area:** {target_lead['emirate']} / {target_lead['area'] or 'Not specified'}")
            
            new_source_url = st.text_input("Verified Source URL (e.g., official directory or map link)", value=target_lead.get("source_url", ""))
            
            conf_options = ["Unspecified", "Low (Unverified)", "Medium (Public Directory)", "High (Official Registry / Direct Contact)"]
            curr_conf = target_lead.get("confidence_level", "Unspecified")
            conf_idx = conf_options.index(curr_conf) if curr_conf in conf_options else 0
            new_confidence = st.selectbox("Confidence Level", conf_options, index=conf_idx)
            
            res_options = ["Pending", "In Progress", "Verified Public Data", "Rejected / Unreliable"]
            curr_res = target_lead.get("research_status", "Pending")
            res_idx = res_options.index(curr_res) if curr_res in res_options else 0
            new_research_status = st.selectbox("Research Status", res_options, index=res_idx)
            
            research_notes = st.text_area("Research Findings & Evidence Notes", value=target_lead.get("notes", ""))

            submit_research = st.form_submit_button("Save Research Updates")

        if submit_research:
            with connect_db() as conn:
                conn.execute(
                    """
                    UPDATE leads 
                    SET source_url = ?, confidence_level = ?, research_status = ?, notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_source_url, new_confidence, new_research_status, research_notes, now(), target_lead["id"])
                )
            audit("LEAD_RESEARCH_UPDATED", f"Enriched lead #{target_lead['id']} ({target_lead['company_name']}) with source verification.")
            st.success("Research details successfully saved and logged to audit trail.")
            st.rerun()

with service_pipelines_tab:
    st.subheader("Multi-Service Opportunity Pipelines")
    st.caption("Track parallel service pipelines (Telecom, POS, Travel, Licensing) for each master company record.")

    all_leads_for_opps = get_leads()
    if not all_leads_for_opps:
        st.info("No companies found. Add a lead in SME Lead Manager first before creating service opportunities.")
    else:
        opp_sub_add, opp_sub_view = st.tabs(["Add Opportunity", "Manage Active Pipelines"])

        with opp_sub_add:
            with st.form("add_opportunity_form", clear_on_submit=True):
                company_choices = {f"{l['company_name']} ({l['emirate']})": l['id'] for l in all_leads_for_opps}
                selected_comp_label = st.selectbox("Select Master Company", list(company_choices.keys()))
                chosen_company_id = company_choices[selected_comp_label]

                selected_vertical = st.selectbox("Service Vertical", SERVICE_VERTICALS)
                initial_stage = st.selectbox("Pipeline Stage", PIPELINE_STAGES, index=0)
                est_value = st.number_input("Estimated Deal Value (AED, optional)", min_value=0.0, step=500.0)
                opp_notes = st.text_area("Opportunity Notes / Requirements")

                submit_opp = st.form_submit_button("Create Service Opportunity")

            if submit_opp:
                save_opportunity(chosen_company_id, selected_vertical, initial_stage, est_value, opp_notes)
                st.success("Service opportunity successfully created!")
                st.rerun()

        with opp_sub_view:
            all_opps = get_opportunities()
            if not all_opps:
                st.info("No service opportunities logged yet.")
            else:
                st.write(f"Total active service opportunities: **{len(all_opps)}**")
                
                vert_filter = st.selectbox("Filter by Vertical", ["All"] + SERVICE_VERTICALS)
                
                for opp in all_opps:
                    if vert_filter != "All" and opp["service_category"] != vert_filter:
                        continue

                    with st.expander(f"{opp['company_name']} — [{opp['service_category']}] ({opp['pipeline_stage']})"):
                        st.write(f"**Emirate:** {opp['emirate']}")
                        st.write(f"**Estimated Value:** AED {opp['estimated_value']:,.2f}")
                        st.write(f"**Created At:** {opp['created_at']}")
                        
                        with st.form(f"update_opp_form_{opp['id']}"):
                            updated_stage = st.selectbox(
                                "Update Pipeline Stage",
                                PIPELINE_STAGES,
                                index=PIPELINE_STAGES.index(opp["pipeline_stage"]) if opp["pipeline_stage"] in PIPELINE_STAGES else 0,
                                key=f"stage_select_{opp['id']}"
                            )
                            updated_notes = st.text_area("Opportunity Notes", value=opp["notes"], key=f"opp_notes_{opp['id']}")
                            
                            save_opp_btn = st.form_submit_button("Update Opportunity")
                            
                        if save_opp_btn:
                            update_opportunity_stage(opp["id"], updated_stage, updated_notes)
                            st.success("Opportunity updated successfully!")
                            st.rerun()

# Option C: Custom Revenue Forecasting & Pipeline Reports Tab
with reports_tab:
    st.subheader("Revenue Forecasting & Custom Pipeline Reports")
    st.caption("Analyze estimated pipeline values, win rates, and vertical revenue forecasts.")

    report_opps = get_opportunities()
    if not report_opps:
        st.info("No service opportunities logged. Create opportunities in 'Service Pipelines' first to generate revenue reports.")
    else:
        df_opps = pd.DataFrame([dict(o) for o in report_opps])

        total_pipeline_val = df_opps["estimated_value"].sum()
        won_pipeline_val = df_opps[df_opps["pipeline_stage"] == "Won"]["estimated_value"].sum()
        negotiation_val = df_opps[df_opps["pipeline_stage"].isin(["Proposal", "Negotiation"])]["estimated_value"].sum()

        r1, r2, r3 = st.columns(3)
        r1.metric("Total Pipeline Value", f"AED {total_pipeline_val:,.2f}")
        r2.metric("Won Revenue", f"AED {won_pipeline_val:,.2f}")
        r3.metric("Near-Close (Proposal/Negotiation)", f"AED {negotiation_val:,.2f}")

        st.divider()

        rep_col1, rep_col2 = st.columns(2)

        with rep_col1:
            st.markdown("### Revenue Forecast by Vertical")
            vertical_rev = df_opps.groupby("service_category")["estimated_value"].sum().reset_index()
            vertical_rev.columns = ["Service Vertical", "Total Estimated Value (AED)"]
            st.dataframe(vertical_rev, use_container_width=True, hide_index=True)

        with rep_col2:
            st.markdown("### Revenue by Pipeline Stage")
            stage_rev = df_opps.groupby("pipeline_stage")["estimated_value"].sum().reset_index()
            stage_rev.columns = ["Pipeline Stage", "Total Value (AED)"]
            st.dataframe(stage_rev, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Export Custom Forecast Report")

        st.download_button(
            label="Download Full Revenue Forecast Report (CSV)",
            data=df_opps.to_csv(index=False).encode("utf-8-sig"),
            file_name="uae_sme_revenue_forecast_report.csv",
            mime="text/csv",
            key="download_revenue_report"
        )

with qualification:
    st.subheader("Lead Qualification")
    st.caption("Scores are indicators only. Verify business details and contact preferences before outreach.")

    leads = get_leads()
    if not leads:
        st.info("No saved leads yet. Add or import leads in SME Lead Manager first.")
    else:
        qualified = []
        for lead in leads:
            result = score_lead(lead)

            status = (lead["lead_status"] or "New").strip()
            verified = (lead["verified_date"] or "").strip()

            if status == "Do Not Contact":
                safety_check = "Exclude – Do Not Contact"
            elif status == "Not a Fit":
                safety_check = "Exclude – Not a Fit"
            else:
                try:
                    verified_date = date.fromisoformat(verified)
                    age_days = (date.today() - verified_date).days
                    if not verified or age_days < 0 or age_days > 90:
                        safety_check = "Verify details first"
                    else:
                        safety_check = "Manual review required"
                except ValueError:
                    safety_check = "Verify details first"

            qualified.append({
                "Company": lead["company_name"],
                "Emirate": lead["emirate"],
                "Industry": lead["industry"],
                "Score": result["score"],
                "Priority": result["priority"],
                "Safety check": safety_check,
                "Status": lead["lead_status"],
                "Verified date": lead["verified_date"],
                "Reason": "; ".join(result["reasons"]) or "No scoring signals recorded",
            })

        df = pd.DataFrame(qualified)

        st.subheader("Find prospects")
        search_text = st.text_input("Search company name")
        emirate_options = ["All"] + sorted(
            [x for x in df["Emirate"].dropna().unique() if x]
        )
        industry_options = ["All"] + sorted(
            [x for x in df["Industry"].dropna().unique() if x]
        )
        priority_options = ["All"] + sorted(
            df["Priority"].dropna().unique().tolist()
        )
        safety_options = ["All"] + sorted(
            df["Safety check"].dropna().unique().tolist()
        )

        f1, f2 = st.columns(2)
        with f1:
            emirate_filter = st.selectbox("Emirate", emirate_options)
            priority_filter = st.selectbox("Priority", priority_options)
        with f2:
            industry_filter = st.selectbox("Industry", industry_options)
            safety_filter = st.selectbox("Safety check", safety_options)

        filtered_df = df.copy()

        if search_text.strip():
            filtered_df = filtered_df[
                filtered_df["Company"].str.contains(
                    search_text.strip(), case=False, na=False, regex=False
                )
            ]
        if emirate_filter != "All":
            filtered_df = filtered_df[filtered_df["Emirate"] == emirate_filter]
        if industry_filter != "All":
            filtered_df = filtered_df[filtered_df["Industry"] == industry_filter]
        if priority_filter != "All":
            filtered_df = filtered_df[filtered_df["Priority"] == priority_filter]
        if safety_filter != "All":
            filtered_df = filtered_df[filtered_df["Safety check"] == safety_filter]

        st.metric("Matching leads", len(filtered_df))
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)

        st.subheader("Export leads")
        st.caption("CSV files may contain business contact information. Store and share them responsibly.")

        export_col1, export_col2 = st.columns(2)

        with export_col1:
            st.download_button(
                label="Download filtered prospects",
                data=filtered_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="uae_sme_filtered_prospects.csv",
                mime="text/csv",
                key="download_filtered_prospects",
            )

        with export_col2:
            all_leads_df = pd.DataFrame([dict(lead) for lead in get_leads()])
            all_leads_csv = all_leads_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="Download all saved leads",
                data=all_leads_csv,
                file_name="uae_sme_all_saved_leads.csv",
                mime="text/csv",
                key="download_all_saved_leads",
            )

        st.caption(
            "Filters only change the displayed results. Excluded leads must not "
            "be contacted. Verify contact permissions and preferences separately."
        )

        st.warning("No messages are sent from this screen. Review source permissions and contact preferences separately.")

# Option A: Multilingual AI Assistant Tab in 8 Key UAE Languages
with ai_tab:
    st.subheader("Multilingual Local AI Assistant (Offline Llama 3)")
    st.caption("Runs entirely on your RTX 3060 GPU. Generates natural B2B communications in 8 key UAE business languages.")

    ai_mode = st.selectbox(
        "Select AI task",
        ["Draft Multilingual B2B Outreach", "Summarize Lead Notes", "General Prospecting Advice"]
    )

    if ai_mode == "Draft Multilingual B2B Outreach":
        col_target, col_lang = st.columns(2)
        with col_target:
            company_input = st.text_input("Target Company Name", value="Local SME")
            service_input = st.selectbox("Service Focus", SERVICE_VERTICALS)
        with col_lang:
            target_language = st.selectbox(
                "Target Language",
                [
                    "English",
                    "Arabic (العربية)",
                    "Hindi (हिंदी)",
                    "Urdu (اردو)",
                    "Malayalam (മലയാളം)",
                    "Tamil (தமிழ்)",
                    "Russian (Русский)",
                    "Chinese (中文)",
                    "Filipino / Tagalog"
                ]
            )

        context_notes = st.text_area("Specific Value Proposition or Context Notes (Optional)")

        if st.button("Generate Natural Outreach Draft"):
            with st.spinner(f"Drafting locally in {target_language}..."):
                lang_instruction = {
                    "English": "Write in clear, concise, professional business English.",
                    "Arabic (العربية)": "Write in natural, fluent, and polite GCC business Arabic (الفصحى المعاصرة المعاملات التجارية). Use respectful business greetings like السلام عليكم.",
                    "Hindi (हिंदी)": "Write in natural, polite Indian business Hindi. Avoid direct machine translation; use authentic commercial phrasing.",
                    "Urdu (اردو)": "Write in formal, polite commercial Urdu with standard business courtesy.",
                    "Malayalam (മലയാളം)": "Write in natural, polite business Malayalam commonly used by UAE SME business owners.",
                    "Tamil (தமிழ்)": "Write in clear, polite commercial Tamil tailored for business owners.",
                    "Russian (Русский)": "Write in formal, polite corporate Russian using 'вы' and professional business etiquette.",
                    "Chinese (中文)": "Write in polite, natural Simplified Chinese (简体中文) commercial format using 您好.",
                    "Filipino / Tagalog": "Write in polite, natural Philippine business Tagalog/Taglish using respectful terms like 'po'."
                }.get(target_language, "Write in clear business English.")

                prompt = (
                    f"You are an expert B2B sales development representative in the United Arab Emirates. "
                    f"Task: Draft a short, professional, and respectful B2B introductory email/message for a company named '{company_input}' "
                    f"regarding our '{service_input}' offerings.\n"
                    f"Language Requirement: {lang_instruction}\n"
                    f"Context/Notes: {context_notes or 'No additional notes provided.'}\n"
                    f"Guidelines:\n"
                    f"1. Do not hardcode prices or guarantees.\n"
                    f"2. Keep it concise, friendly, and non-intrusive.\n"
                    f"3. Include a clear placeholder for human review before sending."
                )

                result = query_local_ai(prompt)
                st.markdown(f"### Draft Output in {target_language} (Requires Human Review)")
                st.text_area("Generated Draft", value=result, height=250)

    elif ai_mode == "Summarize Lead Notes":
        leads_list = get_leads()
        if not leads_list:
            st.info("No leads available to summarize. Add or import leads first.")
        else:
            lead_options = {f"{l['company_name']} ({l['emirate']})": l for l in leads_list}
            selected_lead_label = st.selectbox("Select lead to summarize", list(lead_options.keys()))
            chosen_lead = lead_options[selected_lead_label]
            
            st.write(f"**Current Notes:** {chosen_lead['notes'] or 'No notes recorded.'}")
            
            if st.button("Generate AI Summary"):
                with st.spinner("Processing locally on RTX 3060..."):
                    prompt = f"Summarize the business profile and notes for this UAE SME lead in 3 concise bullet points:\nCompany: {chosen_lead['company_name']}\nEmirate: {chosen_lead['emirate']}\nIndustry: {chosen_lead['industry']}\nNotes: {chosen_lead['notes']}"
                    result = query_local_ai(prompt)
                    st.markdown("### AI Summary")
                    st.write(result)

    elif ai_mode == "General Prospecting Advice":
        query_input = st.text_input("Ask a prospecting question", placeholder="e.g., What telecom services do retail shops in Ras Al Khaimah need?")
        if st.button("Get AI Insights"):
            with st.spinner("Thinking locally..."):
                prompt = f"You are a helpful B2B sales development advisor specializing in the UAE SME market. Answer this question concisely: {query_input}"
                result = query_local_ai(prompt)
                st.markdown("### AI Advice")
                st.write(result)

with approvals:
    st.subheader("Approval Queue")
    st.warning(
        "Approvals are recorded for review only. They do not send messages "
        "or authorize automatic execution."
    )
    filter_status = st.selectbox(
        "Filter approval requests",
        ["Pending", "Approved", "Rejected", "All"],
    )
    requests = get_approvals(filter_status)

    if not requests:
        st.info("No requests match this filter.")
    else:
        for request in requests:
            with st.expander(
                f"Request #{request['id']} — {request['action_type']} "
                f"— {request['status']}"
            ):
                st.write(request["description"])
                st.write(f"Created: {request['created_at']}")
                if request["reviewed_at"]:
                    st.write(f"Reviewed: {request['reviewed_at']}")
                    st.write(f"Review note: {request['review_note'] or 'None'}")

                if request["status"] == "Pending":
                    note = st.text_input(
                        "Review note (optional)",
                        key=f"review_note_{request['id']}",
                    )
                    left, right = st.columns(2)
                    if left.button("Approve record", key=f"approve_{request['id']}"):
                        if review_approval(request["id"], "Approved", note):
                            st.rerun()
                    if right.button("Reject request", key=f"reject_{request['id']}"):
                        if review_approval(request["id"], "Rejected", note):
                            st.rerun()

with audit_tab:
    st.subheader("Audit Log")
    entries = get_audit_log()
    if not entries:
        st.info("No audit events yet.")
    else:
        for entry in entries:
            with st.expander(
                f"#{entry['id']} — {entry['event']} — {entry['created_at']}"
            ):
                st.write(entry["details"])
                if entry["related_task_id"] is not None:
                    st.write(f"Related task: #{entry['related_task_id']}")

with safety:
    st.subheader("Safety and privacy")
    st.success("Outbound messaging: disabled")
    st.success("Automatic task execution: disabled")
    st.success("External AI model: disconnected (Offline Llama 3 active)")

    st.markdown(
        """
        - Existing tasks, approvals, and audit records are preserved.
        - Business leads are stored locally in `tasks.db`.
        - Import only data you are authorized to use.
        - Public availability does not automatically authorize marketing.
        - Check lead sources and verification dates before relying on records.
        - Do not enter passwords, payment details, or unnecessary personal data.
        - The database is not encrypted by this app and the audit log is not tamper-proof.
        """
    )

st.divider()
st.caption("UAE SME AI Command Centre · Local prototype")