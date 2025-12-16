import os
import re
import time
import json
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, request, jsonify
from zoneinfo import ZoneInfo
from datetime import datetime

from openai import OpenAI

# -----------------------------
# CONFIG
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID", "")  # Walter assistant id

# Zoho Creator Custom API
CREATOR_BASE_URL = os.getenv(
    "CREATOR_BASE_URL",
    "https://www.zohoapis.com/creator/custom/kpcreator/lookup_wiring_diagram",
)
CREATOR_PUBLIC_KEY = os.getenv("CREATOR_PUBLIC_KEY", "")  # K9wQnhpZdEaNtgey9Ma7K87Ey

# Timezone for business hours logic in your system instructions
CST_TZ = ZoneInfo("America/Chicago")

# Polling settings for Assistants run
RUN_POLL_SECONDS = float(os.getenv("RUN_POLL_SECONDS", "0.6"))
RUN_MAX_WAIT_SECONDS = float(os.getenv("RUN_MAX_WAIT_SECONDS", "12"))

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------
# Helpers
# -----------------------------
WIRING_KEYWORDS = [
    "wiring diagram", "wiring", "wire colors", "wire colour", "wire info",
    "install wiring", "starter wire", "ignition wire", "relay", "diagram"
]

# Lightweight make list for extraction (extend anytime)
KNOWN_MAKES = [
    "acura","alfa romeo","audi","bmw","buick","cadillac","chevrolet","chrysler",
    "dodge","ford","gmc","honda","hyundai","infiniti","jaguar","jeep","kia",
    "land rover","lexus","lincoln","mazda","mercedes","mini","mitsubishi",
    "nissan","porsche","ram","subaru","tesla","toyota","volkswagen","volvo"
]

def is_wiring_request(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in WIRING_KEYWORDS)

def extract_year_make_model_ignition(text: str) -> Dict[str, Optional[str]]:
    """
    Non-assumptive extraction:
    - year: first 4-digit year 19xx/20xx
    - make: first known make found
    - model: best-effort remaining token(s) after make, stripped of ignition phrases
    - ignition: if explicit (push-to-start / smart key / standard key)
    """
    raw = (text or "").strip()
    low = raw.lower()

    # Year
    year = None
    m_year = re.search(r"\b(19\d{2}|20\d{2})\b", low)
    if m_year:
        year = m_year.group(1)

    # Ignition
    ignition = None
    if re.search(r"\b(push[\s-]?to[\s-]?start|push[\s-]?button|smart[\s-]?key|proximity)\b", low):
        ignition = "Push to Start"
    elif re.search(r"\b(standard[\s-]?key|regular[\s-]?key|key[\s-]?start|turn[\s-]?key)\b", low):
        ignition = "Standard Key"

    # Make
    make = None
    found_make = None
    for mk in sorted(KNOWN_MAKES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(mk)}\b", low):
            found_make = mk
            break
    if found_make:
        make = found_make.upper() if len(found_make) <= 4 else found_make.title()

    # Model (best effort)
    model = None
    if year and make:
        # remove year and make from text, then remove common ignition phrases
        tmp = re.sub(rf"\b{re.escape(year)}\b", " ", low)
        tmp = re.sub(rf"\b{re.escape(found_make)}\b", " ", tmp)
        tmp = re.sub(r"\b(wiring|diagram|wire|colors|colour|info|install|please|need|for|a|an|the)\b", " ", tmp)
        tmp = re.sub(r"\b(push[\s-]?to[\s-]?start|push[\s-]?button|smart[\s-]?key|proximity|standard[\s-]?key|regular[\s-]?key|key[\s-]?start|turn[\s-]?key)\b", " ", tmp)
        # collapse whitespace
        tmp = re.sub(r"\s+", " ", tmp).strip()
        # take first "chunk" as model; allow hyphens/letters/numbers/spaces
        if tmp:
            # Model often includes things like "f-150", "330e", "silverado 2500"
            model = tmp.upper() if tmp.isupper() else tmp
    elif year and not make:
        # user might say "2018 Camry" -> model only present
        tmp = re.sub(rf"\b{re.escape(year)}\b", " ", low)
        tmp = re.sub(r"\b(wiring|diagram|wire|colors|colour|info|install|please|need|for|a|an|the)\b", " ", tmp)
        tmp = re.sub(r"\s+", " ", tmp).strip()
        if tmp:
            model = tmp.upper() if tmp.isupper() else tmp

    return {
        "year": year,
        "make": make,
        "model": model,
        "ignition": ignition
    }

def current_time_cst_iso() -> str:
    return datetime.now(tz=CST_TZ).isoformat()

def creator_lookup(year: str, make: str, model: str, ignition: Optional[str]) -> Dict[str, Any]:
    """
    Calls your Zoho Creator Custom API (Public Key auth).
    Returns parsed JSON or a safe fallback structure.
    """
    params = {
        "publickey": CREATOR_PUBLIC_KEY,
        "year": year,
        "make": make,
        "model": model,
    }
    if ignition:
        params["ignition"] = ignition

    try:
        r = requests.get(CREATOR_BASE_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        # Safe fallback
        return {
            "code": 5000,
            "result": {
                "count": 0,
                "matches": [],
                "error": str(e),
            }
        }

def build_injected_context(user_text: str) -> str:
    """
    Creates a strict 'context block' that we prepend to the user's message
    so Walter has the wiring matches without "searching documents."
    """
    ct = current_time_cst_iso()
    info = extract_year_make_model_ignition(user_text)

    # If not a wiring request, we don't inject lookup context
    if not is_wiring_request(user_text):
        return f"current_time_cst: {ct}\n\nUSER_MESSAGE:\n{user_text}"

    # If wiring request but missing year/make/model, do NOT call Creator
    year, make, model = info.get("year"), info.get("make"), info.get("model")
    ignition = info.get("ignition")

    if not year or not make or not model:
        # still provide parsed fields so Walter can ask only what's missing
        return (
            f"current_time_cst: {ct}\n"
            f"wiring_request: true\n"
            f"parsed_year: {year or ''}\n"
            f"parsed_make: {make or ''}\n"
            f"parsed_model: {model or ''}\n"
            f"parsed_ignition: {ignition or ''}\n\n"
            f"wiring_lookup_result: null\n\n"
            f"USER_MESSAGE:\n{user_text}"
        )

    # Call Creator
    lookup = creator_lookup(year, make, model, ignition)

    return (
        f"current_time_cst: {ct}\n"
        f"wiring_request: true\n"
        f"parsed_year: {year}\n"
        f"parsed_make: {make}\n"
        f"parsed_model: {model}\n"
        f"parsed_ignition: {ignition or ''}\n\n"
        f"wiring_lookup_result (json):\n{json.dumps(lookup, ensure_ascii=False)}\n\n"
        f"USER_MESSAGE:\n{user_text}"
    )

def run_walter(message_text: str) -> str:
    """
    Creates a new thread per message (treat every message as new),
    sends injected context + user message, runs Walter, returns output.
    """
    if not OPENAI_API_KEY or not OPENAI_ASSISTANT_ID:
        return "Configuration error: missing OPENAI_API_KEY or OPENAI_ASSISTANT_ID."

    thread = client.beta.threads.create()
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=message_text
    )

    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=OPENAI_ASSISTANT_ID
    )

    # Poll
    start = time.time()
    while True:
        r = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        if r.status in ("completed", "failed", "cancelled", "expired"):
            break
        if time.time() - start > RUN_MAX_WAIT_SECONDS:
            return "We’re sorry—something took too long. Please try again."
        time.sleep(RUN_POLL_SECONDS)

    if r.status != "completed":
        return "We’re sorry—something went wrong. Please try again."

    # Get last assistant message
    msgs = client.beta.threads.messages.list(thread_id=thread.id, order="desc", limit=10)
    for m in msgs.data:
        if m.role == "assistant":
            # message content blocks
            parts = []
            for c in m.content:
                if c.type == "text":
                    parts.append(c.text.value)
            text_out = "\n".join(parts).strip()
            return text_out or "How can we assist you today?"
    return "How can we assist you today?"


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/salesiq")
def salesiq_webhook():
    """
    SalesIQ webhook payloads vary by channel/flow.
    We'll try multiple keys to find the user's message.
    """
    payload = request.get_json(silent=True) or {}

    # Common candidate fields
    user_text = (
        payload.get("message")
        or payload.get("text")
        or payload.get("visitor_message")
        or payload.get("question")
        or payload.get("query")
        or ""
    )

    # Some payloads nest it
    if not user_text and isinstance(payload.get("data"), dict):
        user_text = payload["data"].get("message") or payload["data"].get("text") or ""

    user_text = (user_text or "").strip()
    if not user_text:
        return jsonify({"reply": "How can we assist you today?"})

    injected = build_injected_context(user_text)
    answer = run_walter(injected)

    # Return format: keep it simple. Adjust if SalesIQ expects a specific key.
    return jsonify({"reply": answer})


if __name__ == "__main__":
    # Railway uses PORT
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
