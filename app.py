
from flask import Flask, request, jsonify
import os
import requests
import time

app = Flask(__name__)

# Read API key from environment variable for security
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
ASSISTANT_ID = "asst_Q0N8ruhG6yWlUNPtk1HZca7"

BASE_URL = "https://api.openai.com/v1"


def create_thread():
    r = requests.post(
        f"{BASE_URL}/threads",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
    )
    r.raise_for_status()
    return r.json()["id"]


def add_message(thread_id, user_message):
    r = requests.post(
        f"{BASE_URL}/threads/{thread_id}/messages",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={"role": "user", "content": user_message}
    )
    r.raise_for_status()


def run_assistant(thread_id):
    r = requests.post(
        f"{BASE_URL}/threads/{thread_id}/runs",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        },
        json={"assistant_id": ASSISTANT_ID}
    )
    r.raise_for_status()
    return r.json()["id"]


def wait_for_response(thread_id, run_id):
    while True:
        r = requests.get(
            f"{BASE_URL}/threads/{thread_id}/runs/{run_id}",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
        )
        r.raise_for_status()
        run = r.json()
        status = run.get("status")

        if status == "completed":
            break
        elif status in ["failed", "cancelled", "expired"]:
            return "I'm sorry — something went wrong while processing your request."

        time.sleep(0.75)

    messages = requests.get(
        f"{BASE_URL}/threads/{thread_id}/messages",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}
    )
    messages.raise_for_status()
    data = messages.json().get("data", [])

    for msg in data:
        if msg.get("role") == "assistant":
            # Get the first text content part
            contents = msg.get("content", [])
            for c in contents:
                if c.get("type") == "text":
                    return c["text"]["value"]

    return "I'm sorry — I couldn't generate a response."


@app.route("/walter", methods=["POST"])
def walter():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    # SalesIQ can be configured to post any key; we check a few common ones
    user_message = (
        data.get("question")
        or data.get("message")
        or data.get("query")
        or data.get("text")
        or ""
    )

    if not user_message:
        return jsonify({"reply": "I didn't receive any message to process."})

    try:
        thread = create_thread()
        add_message(thread, user_message)
        run_id = run_assistant(thread)
        reply = wait_for_response(thread, run_id)
    except Exception as e:
        # Log error to console; return generic message to user
        print("Error talking to OpenAI:", repr(e))
        reply = "I'm sorry — I'm having trouble answering right now. Please try again in a moment."

    return jsonify({"reply": reply})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
