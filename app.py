import os
import time

from flask import Flask, request, jsonify
from openai import OpenAI

# Create OpenAI client – uses OPENAI_API_KEY from the environment
client = OpenAI()

# Your Assistant ID should be set as an environment variable in Railway
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

app = Flask(__name__)


@app.route("/walter", methods=["POST"])
def walter():
    """
    Webhook endpoint called by Zoho SalesIQ.
    Expects JSON: {"question": "..."}
    Returns JSON: {"answer": "..."}
    """
    try:
        data = request.get_json(force=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            return (
                jsonify(
                    {
                        "answer": "I didn’t receive a question to answer. "
                        "Please try asking again."
                    }
                ),
                400,
            )

        if not ASSISTANT_ID:
            # Fail fast if the assistant id isn't configured
            return (
                jsonify(
                    {
                        "answer": "Walter is not fully configured yet "
                        "(missing ASSISTANT_ID)."
                    }
                ),
                500,
            )

        # 1) Create a thread with the user’s question
        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": question,
                }
            ]
        )

        # 2) Start a run with your Assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
        )

        # 3) Poll until the run finishes or times out
        for _ in range(30):  # up to ~30 seconds
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )

            status = run_status.status
            if status == "completed":
                break
            if status in ("failed", "cancelled", "expired"):
                return (
                    jsonify(
                        {
                            "answer": "Sorry, I couldn’t process that request right now."
                        }
                    ),
                    500,
                )

            time.sleep(1)

        # 4) Retrieve the messages on the thread and extract the assistant’s reply
        messages = client.beta.threads.messages.list(thread_id=thread.id)

        answer_text = ""
        for msg in messages.data:
            if msg.role == "assistant":
                # msg.content is a list of content blocks
                for block in msg.content:
                    # text blocks have .type == "text"
                    if getattr(block, "type", None) == "text":
                        answer_text += block.text.value
                if answer_text:
                    break

        if not answer_text:
            answer_text = (
                "Sorry, I couldn’t find an answer for that, "
                "but a human can help you if you connect with support."
            )

        return jsonify({"answer": answer_text})

    except Exception as e:
        # Log to stdout so Railway logs show the error, but don’t leak details to the user
        print("Error in /walter endpoint:", repr(e))
        return (
            jsonify(
                {
                    "answer": "Sorry, something went wrong while talking to Walter. "
                    "Please try again in a moment."
                }
            ),
            500,
        )


@app.route("/", methods=["GET"])
def healthcheck():
    """Simple health check endpoint."""
    return "Walter webhook is running.", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)



