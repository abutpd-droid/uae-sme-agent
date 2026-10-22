import pandas as pd

import csv
import io
import sqlite3
from datetime import date, datetime
from pathlib import Path

import streamlit as st

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

CSV_FIELDS = [
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
]

st.set_page_config(
    page_title="UAE SME AI Command Centre",
    page_icon="Ã°Å¸Â¤â€“",
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
        # Existing Milestone 2/3 tables are preserved.
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

        # Safely add trade licence fields to existing databases.
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
        if "trade_license_number" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN trade_license_number TEXT NOT NULL DEFAULT ''")
        if "issuing_authority" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN issuing_authority TEXT NOT NULL DEFAULT ''")


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
                trade_license_number, issuing_authority
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

    audit("LEAD_CREATED", f"Lead added: {company} | {emirate} | {area}")
    return "added"


def score_lead(lead):
    """Return a simple, explainable lead score and verification priority."""
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
                reasons.append("Verified within 31â€“90 days (+1)")
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


def normalize_header(header):
    header = clean(header).lower().strip().replace(" ", "_").replace("-", "_")
    aliases = {
        "company": "company_name",
        "business_name": "company_name",
        "name": "company_name",
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

overview, commands, history, lead_tab, qualification, approvals, audit_tab, safety = st.tabs(
    [
        "Overview",
        "Command Centre",
        "Task History",
        "SME Lead Manager",
        "Lead Qualification",
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
    c4.metric("Outbound messaging", "Disabled")

    st.subheader("Development roadmap")
    st.markdown(
        """
        - Milestone 1: Local dashboard
        - Milestone 2: Persistent task history
        - Milestone 3: Audit log and approval records
        - Milestone 4: SME lead management
        - Next: Controlled research tools and optional local AI
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
            with st.expander(f"Task #{task['id']} Ã¢â‚¬â€ {task['created_at']}"):
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

    add_tab, import_tab, browse_tab, export_tab = st.tabs(
        ["Add a lead", "Import CSV", "Browse and qualify", "Export"]
    )

    with add_tab:
        with st.form("add_lead_form", clear_on_submit=True):
            company_name = st.text_input("Company name *")
            c1, c2 = st.columns(2)
            emirate = c1.selectbox("Emirate", [""] + EMIRATES)
            area = c2.text_input("Area / locality")
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
                            "A likely duplicate exists with the same company, "
                            "emirate, and area. Review the existing record first."
                        )
                except sqlite3.IntegrityError:
                    st.warning("This lead appears to be a duplicate.")

    with import_tab:
        st.write("Expected columns include `company_name`, `emirate`, `area`, `industry`, `phone`, `email`, `website`, `source`, `verified_date`, `services_of_interest`, `lead_status`, and `notes`.")
        st.write("Common headers such as `company`, `business_name`, `phone_number`, and `email_address` are also recognized.")

        uploaded = st.file_uploader("Choose a CSV file", type=["csv"])

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
                    st.write("Detected columns:", list(mapped_headers.values()))
                    raw_rows = list(reader)
                    st.write(f"Rows found: {len(raw_rows)}")

                    if st.checkbox(
                        "I confirm I am authorized to import this data",
                        key="csv_authorized",
                    ):
                        if st.button("Import CSV rows"):
                            added = 0
                            duplicates = 0
                            skipped = 0
                            errors = 0

                            for raw in raw_rows:
                                record = {}
                                for original, value in raw.items():
                                    target = mapped_headers.get(original, "")
                                    if target in CSV_FIELDS:
                                        record[target] = value

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
                                f"Import finished Ã¢â‚¬â€ added: {added}; "
                                f"duplicates: {duplicates}; skipped: {skipped}; "
                                f"errors: {errors}."
                            )
                            st.rerun()
                    else:
                        st.info("Confirm authorization before importing.")
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
                    f"{lead['company_name']} Ã¢â‚¬â€ {lead['emirate'] or 'Emirate unknown'} "
                    f"Ã¢â‚¬â€ {lead['lead_status']}"
                ):
                    st.write(f"**Area:** {lead['area'] or 'Not provided'}")
                    st.write(f"**Industry:** {lead['industry'] or 'Not provided'}")
                    st.write(f"**Phone:** {lead['phone'] or 'Not provided'}")
                    st.write(f"**Email:** {lead['email'] or 'Not provided'}")
                    st.write(f"**Website:** {lead['website'] or 'Not provided'}")
                    st.write(f"**Source:** {lead['source'] or 'Not provided'}")
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
                safety_check = "Exclude ? Do Not Contact"
            elif status == "Not a Fit":
                safety_check = "Exclude ? Not a Fit"
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
            all_leads_csv = df.to_csv(index=False).encode("utf-8-sig")
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
                f"Request #{request['id']} Ã¢â‚¬â€ {request['action_type']} "
                f"Ã¢â‚¬â€ {request['status']}"
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
                f"#{entry['id']} Ã¢â‚¬â€ {entry['event']} Ã¢â‚¬â€ {entry['created_at']}"
            ):
                st.write(entry["details"])
                if entry["related_task_id"] is not None:
                    st.write(f"Related task: #{entry['related_task_id']}")

with safety:
    st.subheader("Safety and privacy")
    st.success("Outbound messaging: disabled")
    st.success("Automatic task execution: disabled")
    st.success("External AI model: not connected")

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
st.caption("UAE SME AI Command Centre Ã‚Â· Local prototype")




