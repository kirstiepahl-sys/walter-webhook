import os
import json
import logging

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def extract_question(req) -> str | None:
    """
    Try several ways to pull `question` out of the incoming request.

    Handles:
    - Proper JSON: {"question": "..."}
    - Normal form field: question=...
    - Zoho/SalesIQ's odd form where the *key* is a JSON string:
      {"{\"question\":\"...\"}": ""}
    - Raw body like 'question=...' as a last resort.
    """

    # 1) Proper JSON body
    try:
        if req.is_json:
            data = req.get_json(silent=True) or {}
            q = data.get("question")
            if q:
                return q
    except Exception as e:
        logging.info(f"JSON parse failed: {e}")

    # 2) Regular form field
    if "question" in req.form:
        q = req.form.get("question")
        if q:
            return q

    # 3) Weird Zoho case: single form key that is itself JSON
    if len(req.form) == 1:
        only_key = next(iter(req.form.keys()))
        try:
            possible_json = json.loads(only_key)
            q = possible_json.get("question")
            if q:
                return q
        except Exception:
            pass

    # 4) Last resort: inspect raw body text
    raw = req.get_data(as_text=True) or ""
    if raw:
        # e.g. "question=how do i log in"
        if raw.startswith("question="):
            return raw[len("question="):]

        try:
            data = json.loads(raw)
            q = data.get("question")
            if q:
                return q
        except Exception:
            pass

    return None


def ask_openai(question: str) -> str:
    """Call OpenAI and return Walter's answer."""
    if not OPENAI_API_KEY:
        return "Walter isn’t configured with an OpenAI API key yet."

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {
                "role": "system",
                "content": (
                        "You are Walter, Intoxalock's friendly internal assistant for service centers. "
    "You are speaking *as* Intoxalock (use 'we' and 'I'), not about Intoxalock in the third person. "
    "Always be clear, concise, and practical.\n\n"
    "When the retrieved information includes a specific login page, portal, or resource with a URL, "
    "you MUST include that full URL directly in your answer so the user can click it "
    "(for example: 'Go to https://servicecenter.intoxalock.com and sign in...'). "
    "Prefer to give a short set of steps plus the link instead of long paragraphs.\n\n"
    "If you do NOT find enough information in the documents to confidently answer, "
    "do NOT make anything up. Instead, say that you're not completely sure and recommend that "
    "the user connect with a live team member in chat if available, "
    "or leave a message for follow-up if it's outside support hours. "
    "Do NOT tell them to 'contact Intoxalock support'; use this 'chat with a team member or leave a message' phrasing instead."
                ),
            },
            {"role": "user", "content": question},
        ],
    }

    resp = requests.post(
        "https://api.openai.com/v1/responses",
        headers=headers,
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    # responses API: output[0].content[0].text
    try:
        return data["output"][0]["content"][0]["text"].strip()
    except Exception:
        # If the shape changes, at least return something debuggable
        return json.dumps(data)


@app.route("/walter", methods=["POST"])
def walter():
    # Log what we actually receive from Zoho
    raw_body = request.get_data(as_text=True)
    logging.info(f"Raw request body: {raw_body}")
    logging.info(f"Headers: {dict(request.headers)}")
    logging.info(f"Parsed form data: {request.form}")
    logging.info(f"Parsed query args: {request.args}")

    question = extract_question(request)

    if not question:
        logging.info("No question found in request; returning fallback answer.")
        return jsonify({"answer": "I didn’t receive a question to answer."})

    logging.info(f"Question extracted: {question!r}")

    try:
        answer = ask_openai(question)
    except Exception as e:
        logging.exception("Error calling OpenAI")
        return (
            jsonify(
                {
                    "answer": (
                        "I ran into a problem looking that up. "
                        "Please connect with a human so we can help you."
                    )
                }
            ),
            500,
        )

    return jsonify({"answer": answer})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
