import os, json, re, time, random
import requests
import pandas as pd
import gspread
from gspread.utils import rowcol_to_a1
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)
MODEL = "openai/gpt-6-luna"
GUIDELINE_FILE = "guideline_v3.md"
VERSION = "v3"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Test mode: put one ticket id here (e.g. "TCK-10004") to run only that ticket
# and skip writing to the sheet. Set back to None to run all 50.
TEST_TICKET = "TCK-10004"

SHEET_ID = "13ytynvOcmhLa5RzkA5zpEHwwX97kbykGwjDgUf6KV7w"
GID = 253510695
URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={GID}"
TEXT_COL = "message_text"

CATEGORIES = ["order_tracking", "delivery_problem", "damaged_item", "return_refund",
              "order_change", "account_app", "product_question", "needs_human"]
URGENCY = ["High", "Medium", "Low"]

# 1. Input
df = pd.read_csv(URL)
if TEST_TICKET:
    df = df[df["ticket_id"] == TEST_TICKET].copy()

# 2. Mask personal data before it leaves your computer
def mask(text):
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text)
    text = re.sub(r"@\w+", "[HANDLE]", text)
    text = re.sub(r"\+?\d[\d\s-]{7,}\d", "[PHONE]", text)
    return text

SYSTEM = open(GUIDELINE_FILE, encoding="utf-8").read()

# 3. Categorize
def classify(ticket):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": mask(ticket)}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)

# 4. Clean and check
def clean(result):
    result["category"] = str(result.get("category", "")).strip().lower()
    result["urgency"] = str(result.get("urgency", "")).strip().capitalize()
    result["confidence"] = str(result.get("confidence", "")).strip().lower()
    result["english_text"] = str(result.get("english_text", "") or "").strip()
    return result

def check(result):
    if result.get("category") not in CATEGORIES:
        return "BAD_CATEGORY"
    if result.get("urgency") not in URGENCY:
        return "BAD_URGENCY"
    if result.get("confidence") not in ("high", "low"):
        return "BAD_CONFIDENCE"
    return "OK"

# 4b. Send urgent tickets to the urgent_queue tab through the webhook,
#     with retry (exponential backoff + jitter) and error logging
WEBHOOK_TRIES = 3

def send_to_webhook(ticket_id, r, tries=WEBHOOK_TRIES):
    payload = {"ticket_id": ticket_id, "urgency": r["urgency"],
               "category": r["category"], "english_text": r["english_text"]}
    for attempt in range(1, tries + 1):
        try:
            resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f"  webhook OK (try {attempt})")
                return "OK"
            print(f"  webhook got status {resp.status_code} (try {attempt})")
        except requests.RequestException as e:
            print(f"  webhook error: {type(e).__name__} (try {attempt})")
        if attempt < tries:
            wait = min(2 ** attempt, 30) + random.uniform(0, 1)  # 2s, 4s ... capped at 30s, plus jitter
            print(f"  waiting {wait:.1f}s before retry")
            time.sleep(wait)
    print(f"  WEBHOOK_FAILED for {ticket_id} after {tries} tries")
    return "WEBHOOK_FAILED"

# 5. Run all tickets
OUT_COLS = [f"{VERSION}_category", f"{VERSION}_urgency", f"{VERSION}_confidence",
            f"{VERSION}_english_text", f"{VERSION}_error"]
for c in OUT_COLS:
    df[c] = ""

for i in df.index:
    ticket_id = df.loc[i, "ticket_id"]
    try:
        r = clean(classify(df.loc[i, TEXT_COL]))
        df.loc[i, OUT_COLS[0]] = r["category"]
        df.loc[i, OUT_COLS[1]] = r["urgency"]
        df.loc[i, OUT_COLS[2]] = r["confidence"]
        df.loc[i, OUT_COLS[3]] = r["english_text"]
        df.loc[i, OUT_COLS[4]] = check(r)
        if r["urgency"] == "High":
            status = send_to_webhook(ticket_id, r)
            if status != "OK":
                df.loc[i, OUT_COLS[4]] = status
    except Exception as e:
        df.loc[i, OUT_COLS[4]] = f"FAILED: {e}"
    print(ticket_id, df.loc[i, OUT_COLS[0]], df.loc[i, OUT_COLS[1]],
          df.loc[i, OUT_COLS[2]], df.loc[i, OUT_COLS[4]])

failed = df[df[OUT_COLS[4]] == "WEBHOOK_FAILED"]["ticket_id"].tolist()
if failed:
    print("\nWebhook failed for:", ", ".join(failed), "- resend these later.")

if TEST_TICKET:
    print("\nTest run done. Check the urgent_queue tab. Nothing was written to the main sheet.")
    raise SystemExit

df.to_csv(f"results_{VERSION}.csv", index=False)

# 6. Score against the old key and the calibrated key
key_cat_old = df["final_category"]
key_urg_old = df["Urgency"]
key_cat_new = df["calibration_category_2"].fillna(df["calibration_category_1"]).fillna(df["final_category"])
key_urg_new = df["calibration_urgency_2"].fillna(df["calibration_urgency_1"]).fillna(df["Urgency"])

def acc(pred, key):
    return (pred.astype(str).str.strip().str.lower() == key.astype(str).str.strip().str.lower()).mean()

print("\n=== SCORES (category / urgency) ===")
for name in ["v1", "v2", VERSION]:
    pc, pu = df[f"{name}_category"], df[f"{name}_urgency"]
    print(f"{name} on OLD key: {acc(pc, key_cat_old):.0%} / {acc(pu, key_urg_old):.0%}")
    print(f"{name} on NEW key: {acc(pc, key_cat_new):.0%} / {acc(pu, key_urg_new):.0%}")

print("\n=== ERRORS BY TYPE ===")
print(df[OUT_COLS[4]].value_counts().to_string())

print("\n=== ACCURACY BY CONFIDENCE (new key) ===")
ok_cat = df[OUT_COLS[0]].str.lower() == key_cat_new.str.lower()
ok_urg = df[OUT_COLS[1]].str.lower() == key_urg_new.str.lower()
for level in ["high", "low"]:
    m = df[OUT_COLS[2]] == level
    if m.sum():
        print(f"confidence={level}: n={m.sum()}  category {ok_cat[m].mean():.0%}  urgency {ok_urg[m].mean():.0%}")

high = df[OUT_COLS[1]] == "High"
if high.sum():
    false_high = (key_urg_new[high].str.lower() != "high").mean()
    print(f"\nFalse High rate (model said High, key says otherwise): {false_high:.0%} of {high.sum()} High tickets")

# 7. Write this version's columns back to the Google Sheet (by header name)
gc = gspread.service_account(filename="service_account.json")
ws = gc.open_by_key(SHEET_ID).get_worksheet_by_id(GID)
headers = ws.row_values(1)
missing = [c for c in OUT_COLS if c not in headers]
if missing:
    print("\nAdd these headers to row 1 of the sheet, then run again:", missing)
else:
    updates = []
    for c in OUT_COLS:
        col = headers.index(c) + 1
        rng = f"{rowcol_to_a1(2, col)}:{rowcol_to_a1(len(df) + 1, col)}"
        updates.append({"range": rng, "values": [[v] for v in df[c].fillna("").tolist()]})
    ws.batch_update(updates)
    print("\nWritten to sheet:", ", ".join(OUT_COLS))
