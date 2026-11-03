# api.py - the Support Sorter as a small REST API
# Run:  uvicorn api:app --reload
# Docs: http://127.0.0.1:8000/docs  (or point Scalar at http://127.0.0.1:8000/openapi.json)

import os, json, re
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from scalar_fastapi import get_scalar_api_reference

load_dotenv()
client = OpenAI(base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY"))
MODEL = "openai/gpt-6-luna"
GUIDELINE_FILE = "guideline_v3.md"
VERSION = "v3"
SYSTEM = open(GUIDELINE_FILE, encoding="utf-8").read()

CATEGORIES = ["order_tracking", "delivery_problem", "damaged_item", "return_refund",
              "order_change", "account_app", "product_question", "needs_human"]
URGENCY = ["High", "Medium", "Low"]
MAX_CHARS = 5000

app = FastAPI(title="Support Sorter API", version=VERSION)

# What a request must look like, and what the response looks like
class Ticket(BaseModel):
    text: str

class Result(BaseModel):
    category: str
    urgency: str
    confidence: str
    english_text: str
    version: str

def mask(text):
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]", text)
    text = re.sub(r"@\w+", "[HANDLE]", text)
    text = re.sub(r"\+?\d[\d\s-]{7,}\d", "[PHONE]", text)
    return text

def classify(ticket):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": mask(ticket)}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)

def clean(r):
    return {
        "category": str(r.get("category", "")).strip().lower(),
        "urgency": str(r.get("urgency", "")).strip().capitalize(),
        "confidence": str(r.get("confidence", "")).strip().lower(),
        "english_text": str(r.get("english_text", "") or "").strip(),
    }

def check(r):
    if r["category"] not in CATEGORIES:
        return "BAD_CATEGORY"
    if r["urgency"] not in URGENCY:
        return "BAD_URGENCY"
    if r["confidence"] not in ("high", "low"):
        return "BAD_CONFIDENCE"
    return "OK"

@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "model": MODEL}

@app.post("/classify", response_model=Result)
def classify_ticket(ticket: Ticket):
    text = ticket.text.strip()
    # 422 = the request itself is wrong (the caller must fix it)
    if not text:
        raise HTTPException(status_code=422, detail="text is empty")
    if len(text) > MAX_CHARS:
        raise HTTPException(status_code=422, detail=f"text is longer than {MAX_CHARS} characters")
    # 502 = our upstream (the model) failed or answered badly
    try:
        r = clean(classify(text))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"model call failed: {type(e).__name__}")
    status = check(r)
    if status != "OK":
        raise HTTPException(status_code=502, detail=f"model output failed check: {status}")
    return {**r, "version": VERSION}

@app.get("/scalar", include_in_schema=False)
def scalar_docs():
    return get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title)
