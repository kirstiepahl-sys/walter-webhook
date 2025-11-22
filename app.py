import os
import logging

from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is not set.")

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4.1-mini"  # adjust if you want a different model

# -------------------------------------------------------------------
# System prompt for Walter
# -------------------------------------------------------------------
SYSTEM_PROMPT = """
You are Walter, the Intoxalock Service Center virtual assistant.

You speak **as Intoxalock**, not about Intoxalock in the third person.
- Use “we”, “our team”, “our microsite”, etc.
- Avoid phrases like “Intoxalock provides…” or “Intoxalock gives you…”.
  Instead say “We provide…”, “We give you…”, “Our team…”.

Audience:
- Intoxalock service center partners and staff.
- They are usually asking about processes, policies, portals, paperwork,
  installations, pricing rules, or support workflows.

Tone:
- Friendly, concise, professional, and confident.
- Get to the point quickly, then offer a short follow-up like
  “If anything doesn’t match what you’re seeing, let us know.”

Truthfulness and use of documentation:
- Prefer the exact wording and details from the internal documentation
  and Q&A you’ve been trained on.
- DO NOT invent URLs, phone numbers, email addresses, prices, or policies.
- If the documentation doesn’t clearly answer the question, say that you’re
  not completely sure and recommend contacting Service Center Support or a
  human teammate instead of guessing.

Microsite login rules (very important):
- When someone asks where or how to log in to “the microsite”,
  “service center portal”, “Intoxalock portal for shops”, or anything
  clearly referring to the Intoxalock service center microsite, you MUST:
  1) Give this exact URL: https://servicecenter.intoxalock.com
  2) Say that they should sign in using their Service Center email and password.
- Keep this answer short and direct unless they ask for more detail.

Out-of-scope:
- If a question is not about Intoxalock, our service centers, our customers,
  or our tools, say that Walter is focused on Intoxalock service center
  support and suggest they contact the appropriate resource instead.

Formatting:
- Answer in plain text (no markdown lists unless the question clearly
  benefits from step-by-step bullets).
- Be specific, but avoid long, rambling paragraphs.
"""


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def extract_question(payload: dict) -> str:
    """
    Try a few common keys to get the user's question.
    Main path is 'question', but we keep fallbacks in case SalesIQ
    changes formatting later.
    """
    if not isinstance(payload, dict):
        return ""

    # Primary key – what we configured in SalesIQ
    question = payload.get("question")

    # Fallbacks (older experiments)
    if not question:
        question = payload.get("visitor.question")
    if not question:
        question = payload.get("visitor_question")

    if isinstance(question, str):
        return question.strip()

    return ""


def call_openai_chat(question: str) -> str:
    """
    Call OpenAI Chat Completions to get Walter's answer.
    """
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            OPENAI_API_URL, headers=headers, json=body, timeout=30
        )
    except Exception as e:
        app.logger.error("Error talking to OpenAI: %s", e)
        return (
            "I’m having trouble pulling that information right now. "
            "Please try again in a moment or connect with a human teammate."
        )

    if resp.status_code != 200:
        app.logger.error(
            "OpenAI error %s: %s", resp.status_code, resp.text[:1000]
        )
        return (
            "I’m having trouble pulling that information right now. "
            "Please try again in a moment or connect with a human teammate."
        )

    data = resp.json()
    try:
        answer = data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        app.logger.error("Error parsing OpenAI response: %s", e)
        return (
            "I’m having trouble pulling that information right now. "
            "Please try again in a moment or connect with a human teammate."
        )

    return answer


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return "Walter is alive ✅", 200


@app.route("/walter", methods=["POST"])
def walter():
    """
    Main webhook endpoint for Zoho SalesIQ.

    Expected body (JSON):
      { "question": "How do I log into the microsite?" }

    Response:
      { "answer": "..." }

    SalesIQ maps this 'answer' field to the walter_answer variable.
    """
    payload = request.get_json(silent=True) or {}
    app.logger.info("Incoming payload: %s", payload)

    question = extract_question(payload)

    if not question:
        # This is what you saw earlier when the question wasn't wired through.
        return jsonify({"answer": "I didn’t receive a question to answer."}), 200

    answer = call_openai_chat(question)
    return jsonify({"answer": answer}), 200


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------
if __name__ == "__main__":
    # For local testing. Railway overrides host/port.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
