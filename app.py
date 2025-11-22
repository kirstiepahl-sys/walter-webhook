import os
import time
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# ---------------------------
#  CONFIG: your Assistant ID
# ---------------------------
ASSISTANT_ID = "asst_Q0N8ruhG6yWNJUVPtk1HZca7"

# OpenAI client (uses OPENAI_API_KEY env var)
client = OpenAI()


@app.route("/walter", methods=["POST"])
def walter():
    """
    Webhook endpoint for Zoho SalesIQ.
    Expects JSON like: { "question": "user text here" }
    Returns JSON like: { "answer": "Walter's reply" }
    """
    # Safely parse body
    data = request.get_json(force=True, silent=True) or {}
    print("RAW REQUEST:", data)

    # Pick up the question (we support both keys just in case)
    question = (
        data.get("question")
        or data.get("visitor_question")
        or ""
    )

    if not question.strip():
        # SalesIQ will still get a valid JSON answer
        return jsonify({
            "answer": (
                "I didn’t receive a question to answer. "
                "Please type your Intoxalock service center question again."
            )
        })

    try:
        # Create a new thread for this question
        thread = client.beta.threads.create()

        # Add the user message
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=question
        )

        # Start a run with your Assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )

        # Poll until the run finishes
        while True:
            run = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )
            if run.status in ("completed", "failed", "cancelled", "expired"):
                break
            time.sleep(0.5)

        if run.status != "completed":
            # Graceful failure message
            return jsonify({
                "answer": (
                    "I’m having trouble answering right now. "
                    "Please try again or connect with a member of the "
                    "Intoxalock Service Center team."
                )
            })

        # Fetch messages and pull the assistant's text
        messages = client.beta.threads.messages.list(thread_id=thread.id)

        assistant_text_chunks = []
        for msg in messages.data:
            if msg.role == "assistant":
                for part in msg.content:
                    if getattr(part, "type", None) == "text":
                        assistant_text_chunks.append(part.text.value)

        # Most recent assistant message last → reverse to read newest first
        answer = "\n\n".join(reversed(assistant_text_chunks)).strip()

        if not answer:
            answer = (
                "I’m not sure how to answer that. "
                "Please try rephrasing your question or reach out to the "
                "Intoxalock Service Center team."
            )

        print("WALTER ANSWER:", answer)
        return jsonify({"answer": answer})

    except Exception as e:
        # Never crash the webhook – always return a JSON answer
        print("ERROR IN /walter:", repr(e))
        return jsonify({
            "answer": (
                "I’m having trouble answering right now. "
                "Please try again or connect with a member of the "
                "Intoxalock Service Center team."
            )
        })


if __name__ == "__main__":
    # Railway sets PORT env var; default 8080 for local runs
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
