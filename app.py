import os
import time
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# -------------------------------------------------------------------
# OpenAI / Walter configuration
# -------------------------------------------------------------------
# Either keep your existing ASSISTANT_ID line here,
# or edit this value to your real assistant id.
ASSISTANT_ID = os.getenv("ASSISTANT_ID", "YOUR_ASSISTANT_ID_HERE")

client = OpenAI()  # uses OPENAI_API_KEY env var


# -------------------------------------------------------------------
# Helper: send question to Walter and get answer
# -------------------------------------------------------------------
def ask_walter(question: str) -> str:
    """
    Send the user's question to the Walter assistant and return the answer text.
    """

    # Create a fresh thread for this question
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": question,
            }
        ]
    )

    # Kick off a run for your assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID,
    )

    # Poll until the run completes (or fails)
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

        if run.status == "completed":
            break
        if run.status in ("failed", "cancelled", "expired"):
            app.logger.error("Walter run ended with status: %s", run.status)
            return "I'm having trouble answering right now. Please try again or contact Intoxalock support."

        time.sleep(0.5)

    # Get the newest assistant message
    messages = client.beta.threads.messages.list(thread_id=thread.id, limit=1)

    if not messages.data:
        app.logger.error("No messages returned from Walter.")
        return "I couldn't generate an answer. Please try again or contact Intoxalock support."

    msg = messages.data[0]

    # Extract plain text from the message content
    parts = msg.content
    text_chunks = []
    for part in parts:
        if getattr(part, "type", None) == "text":
            text_chunks.append(part.text.value)
    if not text_chunks:
        return "I couldn't generate an answer. Please try again or contact Intoxalock support."

    return "\n".join(text_chunks).strip()


# -------------------------------------------------------------------
# Webhook endpoint for Zoho SalesIQ
# -------------------------------------------------------------------
@app.route("/walter", methods=["POST", "GET"])
def walter_webhook():
    try:
        # --- Inspect everything SalesIQ sends ------------------------
        raw_json = request.get_json(silent=True) or {}
        args = request.args.to_dict()
        form = request.form.to_dict()

        app.logger.info("Incoming request args: %s", args)
        app.logger.info("Incoming request form: %s", form)
        app.logger.info("Incoming request JSON: %s", raw_json)

        # --- Try to find the visitor question ------------------------
        question = (
            args.get("question")
            or form.get("question")
            or raw_json.get("question")
            or raw_json.get("visitor_question")
            or raw_json.get("visitor.question")
        )

        app.logger.info("Extracted question: %r", question)

        if not question or not str(question).strip():
            # We *always* return 200 so SalesIQ doesn't show "insufficient data".
            answer = (
                "I didn’t receive a clear question to answer. "
                "Please type your Intoxalock service center question again."
            )
            return jsonify({"answer": answer}), 200

        # --- Ask Walter via OpenAI -----------------------------------
        answer = ask_walter(question)

        # Return in the shape SalesIQ expects: { "answer": "..." }
        return jsonify({"answer": answer}), 200

    except Exception as e:
        # Log the error but still return a friendly message with 200
        app.logger.exception("Error handling /walter webhook: %s", e)
        fallback = (
            "I ran into a problem answering that right now. "
            "Please try again in a moment or contact Intoxalock support."
        )
        return jsonify({"answer": fallback}), 200


# -------------------------------------------------------------------
# Simple health check
# -------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return "Walter webhook is running.", 200


if __name__ == "__main__":
    # For local testing only; Railway will use gunicorn or similar.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
