import os
import json
import logging

from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# --- logging -----------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- config ------------------------------------------------------------

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ASSISTANT_ID = os.environ.get("ASSISTANT_ID")  # set this in Railway variables

OPENAI_API_BASE = "https://api.openai.com/v1"


# --- helpers -----------------------------------------------------------

def extract_question(req) -> str:
    """
    Try very hard to extract the user's question from the incoming request.

    We support:
    - JSON body
    - form-encoded body
    - raw body containing JSON
    - query parameter ?question=
    And multiple field names: question / visitor.question / visitor_question.
    """

    payload = {}

    # 1) JSON body
    try:
        if req.is_json:
            payload = req.get_json(silent=True) or {}
    except Exception as e:
        logger.exception("Error parsing JSON body: %s", e)

    # 2) form-encoded body
    if not payload:
        try:
            form_data = req.form.to_dict()
            if form_data:
                payload = form_data
        except Exception as e:
            logger.exception("Error reading form body: %s", e)

    # 3) raw body (might be JSON string)
    if not payload:
        raw = req.get_data(cache=False, as_text=True) or ""
        if raw.strip():
            try:
                payload = json.loads(raw)
            except Exception:
                # not JSON; just log for debugging
                logger.info("Raw body (non-JSON): %r", raw)

    logger.info("Incoming payload after parsing: %s", payload)

    # 4) finally, querystring
    question = (
        payload.get("question")
        or payload.get("visitor.question")
        or payload.get("visitor_question")
        or payload.get("text")
        or req.args.get("question")
        or ""
    )

    if question is None:
        question = ""

    question = str(question).strip()
    logger.info("Extracted question: %r", question)
    return question


def call_openai_assistant(question: str) -> str:
    """
    Call your OpenAI Assistant (with vector store attached) via the Responses API.
    """

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY is not set")
        return (
            "I’m having trouble accessing my knowledge right now because my API key "
            "is missing. Please contact Intoxalock support for help."
        )

    if not ASSISTANT_ID:
        logger.error("ASSISTANT_ID is not set")
        return (
            "I’m not fully configured yet (missing assistant ID). "
            "Please contact Intoxalock support so we can fix this."
        )

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "OpenAI-Beta": "assistants=v2",
    }

    body = {
        "model": "gpt-4.1-mini",
        "assistant_id": ASSISTANT_ID,
        "input": [
            {
                "role": "user",
                "content": question,
            }
        ],
        # System / style instructions live on the Assistant itself in the UI.
        # If you ever want to add *extra* one-off instructions, you can use:
        # "metadata" or an additional "input" message with role "assistant".
    }

    try:
        resp = requests.post(
            f"{OPENAI_API_BASE}/responses",
            headers=headers,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("OpenAI response JSON: %s", json.dumps(data, indent=2))

        # Prefer the convenience field if present
        answer_text = None

        # Newer Responses API sometimes includes `output_text`
        if isinstance(data, dict) and "output_text" in data:
            ot = data["output_text"]
            if isinstance(ot, dict):
                choices = ot.get("choices") or []
                if choices:
                    answer_text = choices[0].get("text")

        # Fallback: walk the `output` list
        if not answer_text:
            output = data.get("output") or []
            texts = []
            for item in output:
                # each item has "content": [{"type": "output_text", "text": {...}}]
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        text_obj = c.get("text") or {}
                        parts = text_obj.get("value") or ""
                        texts.append(parts)
            if texts:
                answer_text = "\n".join(texts)

        if not answer_text:
            logger.error("Could not extract answer text from OpenAI response")
            return (
                "I wasn’t able to read the answer from my knowledge base. "
                "Please reach out to Intoxalock support for assistance."
            )

        return answer_text.strip()

    except Exception as e:
        logger.exception("Error talking to OpenAI: %s", e)
        return (
            "I’m having trouble reaching my knowledge base right now. "
            "Please contact Intoxalock support or try again in a few minutes."
        )


# --- routes ------------------------------------------------------------

@app.route("/walter", methods=["POST"])
def walter():
    question = extract_question(request)

    if not question:
        logger.info("No question found in request; sending default message.")
        return jsonify(
            {
                "answer": "I didn’t receive a question to answer. "
                          "Please type your question and send it again."
            }
        )

    answer = call_openai_assistant(question)
    return jsonify({"answer": answer})


# --- main --------------------------------------------------------------

if __name__ == "__main__":
    # Railway sets PORT; default to 8080 for local tests
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
