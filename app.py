import os
import time
import json
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# Environment variables set in Railway
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ASSISTANT_ID = os.environ.get("WALTER_ASSISTANT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)


def extract_question():
    """Try very hard to find the visitor's question in the incoming request."""
    raw_body = request.get_data(as_text=True)
    print("RAW BODY:", raw_body)

    # Try JSON
    try:
        data = request.get_json(silent=True) or {}
    except Exception as e:
        print("JSON parse error:", e)
        data = {}

    # Form data & query string
    form_data = request.form.to_dict()
    args = request.args.to_dict()

    print("JSON DATA:", data)
    print("FORM DATA:", form_data)
    print("ARGS:", args)

    candidates = []

    # 1) Direct keys in JSON / form / query
    for container in (data, form_data, args):
        if isinstance(container, dict):
            for key in ("question", "visitor_question", "text", "message", "query", "q"):
                val = container.get(key)
                if isinstance(val, str) and val.strip():
                    candidates.append(val.strip())

    # 2) Sometimes platforms send a JSON string in "body" or "payload"
    for container in (data, form_data, args):
        if isinstance(container, dict):
            for key in ("body", "payload"):
                val = container.get(key)
                if isinstance(val, str):
                    try:
                        inner = json.loads(val)
                        if isinstance(inner, dict):
                            for k in ("question", "visitor_question", "text", "message"):
                                v2 = inner.get(k)
                                if isinstance(v2, str) and v2.strip():
                                    candidates.append(v2.strip())
                    except Exception:
                        pass

    # 3) Raw body might itself be JSON
    if not candidates:
        try:
            inner = json.loads(raw_body)
            if isinstance(inner, dict):
                for k in ("question", "visitor_question", "text", "message"):
                    v2 = inner.get(k)
                    if isinstance(v2, str) and v2.strip():
                        candidates.append(v2.strip())
        except Exception:
            pass

    question = candidates[0] if candidates else None
    print("FINAL QUESTION:", repr(question))
    return question


@app.route("/walter", methods=["POST"])
def walter():
    # 1) Get question from request
    question = extract_question()

    if not question:
        print("No question found in request")
        return jsonify({
            "answer": (
                "I didn’t receive a question to answer. "
                "Please type your Intoxalock service center question again."
            )
        })

    print("USER QUESTION:", question)

    # 2) Create a thread with the user's question
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": question,
            }
        ]
    )

    # 3) Run the Assistant on that thread
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID,
    )

    # 4) Poll until the run completes or fails
    for _ in range(30):  # up to ~30 seconds
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        print("Run status:", run.status)
        if run.status in ("completed", "failed", "cancelled", "expired"):
            break
        time.sleep(1)

    if run.status != "completed":
        print("Run did not complete:", run.status)
        return jsonify({
            "answer": (
                "I’m having trouble answering that right now. "
                "Please try again in a moment or contact Intoxalock support."
            )
        })

    # 5) Get the latest assistant message
    messages = client.beta.threads.messages.list(
        thread_id=thread.id,
        order="desc",
        limit=1,
    )

    answer_text = ""
    for msg in messages.data:
        for item in msg.content:
            if item.type == "text":
                answer_text = item.text.value
                break
        if answer_text:
            break

    if not answer_text:
        answer_text = (
            "I’m sorry — I couldn’t find an answer to that in my Intoxalock resources."
        )

    print("FINAL ANSWER:", answer_text)

    # SalesIQ maps this "answer" field to %walter_answer%
    return jsonify({"answer": answer_text})


@app.route("/", methods=["GET"])
def healthcheck():
    return "Walter webhook is running", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
