import os
import logging

from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI client – uses OPENAI_API_KEY from Railway env vars
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# System prompt so Walter talks like Intoxalock and knows the microsite URL
SYSTEM_PROMPT = """
You are Walter, the Intoxalock Service Center virtual assistant.

You speak as Intoxalock:
- Use “we”, “our team”, “our microsite”, “our support team”.
- Do NOT say “Intoxalock provides…” or “Intoxalock gives you…”.
  Instead say “We provide…”, “We give you…”, “Our team…”.

Audience:
- Intoxalock service center partners and staff asking about:
  installations, paperwork, pricing rules, microsite, support workflows,
  state-specific notes, and internal processes.

Microsite login:
- If the user asks where or how to log into the microsite, service center
  portal, or anything similar, you MUST answer with:
  1) The exact URL: https://servicecenter.intoxalock.com
  2) That they should log in with their Service Center email and password.
- Keep this answer short and direct unless they ask for more detail.

Truthfulness:
- Do NOT invent URLs, phone numbers, prices, or policies.
- If you’re not sure, say you’re not completely sure and recommend they
  contact Intoxalock Service Center Support or a human teammate.

Style:
- Be friendly, concise, and clear.
- Lead with the direct answer, then add a brief helpful note if needed.
"""

def extract_question(req) -> str:
    """
    Pull the visitor's question from the incoming request.

    We expect SalesIQ to send JSON like: {"question": "..."}.
    But we also tolerate a few alternate keys.
    """
    data = req.get_json(silent=True) or {}
    logger.info("Incoming JSON from SalesIQ: %s", data)

    q = (
        data.get("question")
        or data.get("visitor_question")
        or data.get("visitor.question")
        or ""
    )

    if not isinstance(q, str):
        q = str(q or "")

    q = q.strip()
    logger.info("Extracted question: %r", q)
    return q


@app.route("/walter", methods=["POST"])
def walter():
    # Get the question from the request
    question = extract_question(request)

    if not question:
        # Always return 200 with JSON so SalesIQ doesn’t show “insufficient data”
        return jsonify({
            "answer": (
                "I didn’t receive a question to answer. "
                "Please type your Intoxalock service center question again."
            )
        }), 200

    try:
        # Call OpenAI using the Responses-style API via the Python client
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )

        # Extract the answer text from the response object
        answer_text = ""
        try:
            # Newer Responses API structure:
            # resp.output[0].content[0].text.value
            first_output = resp.output[0]
            first_content = first_output.content[0]
            text_obj = first_content.text
            answer_text = getattr(text_obj, "value", "") or ""
        except Exception as e:
            logger.error("Error extracting answer text: %s", e)
            answer_text = ""

        if not answer_text.strip():
            answer_text = (
                "I wasn’t able to generate an answer just now. "
                "Please try again, or contact our Service Center Support team."
            )

        return jsonify({"answer": answer_text}), 200

    except Exception as e:
        logger.exception("Error talking to OpenAI: %s", e)
        return jsonify({
            "answer": (
                "I ran into a technical issue while answering that. "
                "Please try again in a moment or contact our team directly."
            )
        }), 200


@app.route("/", methods=["GET"])
def health():
    return "Walter webhook is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
