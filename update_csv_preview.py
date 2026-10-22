from pathlib import Path
from datetime import datetime

APP = Path(__file__).resolve().parent / "app.py"
text = APP.read_text(encoding="utf-8")

start_marker = "    with import_tab:\n"
end_marker = "    with browse_tab:\n"

if text.count(start_marker) != 1 or text.count(end_marker) != 1:
    raise SystemExit("STOP: Expected import section boundaries were not found exactly once.")

start = text.index(start_marker)
end = text.index(end_marker)

if start >= end:
    raise SystemExit("STOP: Import section boundaries are in the wrong order.")

replacement = '''    with import_tab:
        st.write("Upload a CSV to preview and validate records before importing.")
        st.write("Trade licence duplicates are checked using licence number, emirate, and issuing authority.")

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

                    preview_records = []
                    seen_licences = set()
                    seen_companies = set()
                    missing_names = 0
                    file_duplicates = 0

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
                    st.warning(
                        "This preview checks duplicates within the uploaded file. "
                        "Existing database duplicates are checked again during import."
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

'''

backup = APP.with_name(
    f"app-before-csv-update-{datetime.now().strftime('%Y%m%d-%H%M%S')}.py"
)
backup.write_text(text, encoding="utf-8")
APP.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
print(f"Backup created: {backup.name}")
print("CSV import section updated.")
