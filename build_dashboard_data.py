import re
import pandas as pd
import gspread
from gspread.utils import rowcol_to_a1

SHEET_ID = "13ytynvOcmhLa5RzkA5zpEHwwX97kbykGwjDgUf6KV7w"
GID = 253510695
URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
TAB = "dashboard_data"

# 1. Read the sheet (all versions live in columns like v1_category, v2_category, ...)
df = pd.read_csv(URL)

# 2. The answer key: calibrated label if there is one, otherwise the original label
key_cat = df["calibration_category_2"].fillna(df["calibration_category_1"]).fillna(df["final_category"])
key_urg = df["calibration_urgency_2"].fillna(df["calibration_urgency_1"]).fillna(df["Urgency"])

def norm(s):
    return s.astype(str).str.strip().str.lower()

# 3. Find every version automatically (v1, v2, v3 ...)
versions = sorted({m.group(1) for c in df.columns if (m := re.match(r"^(v\d+)_category$", c))})
print("Versions found:", versions)

# 4. Build one row per ticket per version
rows = []
for v in versions:
    part = pd.DataFrame({
        "ticket_id": df["ticket_id"],
        "version": v,
        "true_category": key_cat,
        "pred_category": df[f"{v}_category"],
        "true_urgency": key_urg,
        "pred_urgency": df[f"{v}_urgency"].astype(str).str.strip().str.capitalize(),
        "confidence": df[f"{v}_confidence"] if f"{v}_confidence" in df else "",
    })
    part["category_correct"] = (norm(part["pred_category"]) == norm(part["true_category"])).astype(int)
    part["urgency_correct"] = (norm(part["pred_urgency"]) == norm(part["true_urgency"])).astype(int)
    part["false_high"] = ((norm(part["pred_urgency"]) == "high") & (norm(part["true_urgency"]) != "high")).astype(int)

    def error_type(r):
        if not r.category_correct and not r.urgency_correct:
            return "WRONG_BOTH"
        if not r.category_correct:
            return "WRONG_CATEGORY"
        if not r.urgency_correct:
            return "WRONG_URGENCY"
        return "OK"
    part["error_type"] = part.apply(error_type, axis=1)

    # invalid or failed model output, if that version logged it
    if f"{v}_error" in df:
        bad = df[f"{v}_error"].fillna("OK").astype(str) != "OK"
        part.loc[bad, "error_type"] = df.loc[bad, f"{v}_error"].astype(str).str.split(":").str[0]
    rows.append(part)

out = pd.concat(rows, ignore_index=True)
out.to_csv("dashboard_data.csv", index=False)
print(out.groupby("version")[["category_correct", "urgency_correct", "false_high"]].mean().round(2))

# 5. Write the table to its own tab in the Google Sheet (replaces the old contents)
gc = gspread.service_account(filename="service_account.json")
sh = gc.open_by_key(SHEET_ID)
try:
    ws = sh.worksheet(TAB)
    ws.clear()
except gspread.WorksheetNotFound:
    ws = sh.add_worksheet(title=TAB, rows=len(out) + 1, cols=len(out.columns))

values = [out.columns.tolist()] + out.fillna("").astype(object).values.tolist()
ws.update(values, "A1")
print(f"Wrote {len(out)} rows to the '{TAB}' tab.")
