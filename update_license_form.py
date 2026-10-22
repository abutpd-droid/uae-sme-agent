from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old_form = '''            emirate = c1.selectbox("Emirate", [""] + EMIRATES)
            area = c2.text_input("Area / locality")
            industry = st.selectbox("Industry", [""] + INDUSTRIES)
'''

new_form = '''            emirate = c1.selectbox("Emirate", [""] + EMIRATES)
            area = c2.text_input("Area / locality")
            trade_license_number = st.text_input("Trade licence number (optional)")
            issuing_authority = st.text_input("Issuing authority (optional)")
            industry = st.selectbox("Industry", [""] + INDUSTRIES)
'''

old_record = '''                    "emirate": emirate,
                    "area": area,
                    "industry": industry,
'''

new_record = '''                    "emirate": emirate,
                    "area": area,
                    "trade_license_number": trade_license_number,
                    "issuing_authority": issuing_authority,
                    "industry": industry,
'''

if s.count(old_form) != 1:
    raise SystemExit("STOP: Expected form section not found exactly once; app.py unchanged.")

if s.count(old_record) != 1:
    raise SystemExit("STOP: Expected record section not found exactly once; app.py unchanged.")

s = s.replace(old_form, new_form, 1)
s = s.replace(old_record, new_record, 1)

p.write_text(s, encoding="utf-8")
print("SUCCESS: Added trade licence fields to the form and record.")