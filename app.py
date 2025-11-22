import os
import json
import time
import urllib.parse

from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# Init OpenAI client
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Your existing Walter assistant ID
ASSISTANT_ID = "asst_Ou8BA8URF4u293zQ9twUKEzt"


def extract_question(req):
    """
    Try very hard to get a 'question' string from the Zoho SalesIQ webhook.
    We support:
      - JSON body: {"question": "..."} or {"Question": "..."}
      - Form body: question=...
      - URL-encoded body: question=...
      - Query string: ?question=...
    """
    raw_body = req.get_data(as_text=True) or ""
    print("Raw request body:", raw_body)
    print("Headers:", dict(req.headers))

    question = None

    # 1) Try standard JSON
    try:
        data = req.get_json(force=False, silent=True)
        if isinstance(data, dict):
            print("Parsed JSON body:", data)
            question = data.get("question") or data.get("Question")
    except Exception as e:
        print("Error parsing JSON body:", e)

    # 2) Try form fields (application/x-www-form-urlencoded)
    if not question:
        if req.form:
            print("Parsed form data:", req.form)
            question = req.form.get("question") or req.form.get("Question")

    # 3) Try query string
    if not question:
        if req.args:
            print("Parsed query args:", req.args)
            question = req.args.get("question") or req.args.get("Question")

    # 4) Try to manually parse URL-encoded body
    if not question and raw_body:
        try:
            parsed_qs = urllib.parse.parse_qs(raw_body)
            print("Parsed URL-encoded body:", parsed_qs)
            for key in ("question", "Question"):
                if key in parsed_qs and parsed_qs[key]:
                    question = parsed_qs[key][0]
                    break
        except Exception as e:
            print("Error parsing URL-encoded body:", e)

    if question:
        question = question.strip()

    return question


@app.route("/", methods=["GET"])
def health():
    return "Walter webhook is alive", 200


@app.route("/walter", methods=["POST"])
def walter():
    # Try to extract the visitor's question from the incoming request
    question = extract_question(request)

    if not question:
        # Log and return a friendly message – this is what you were seeing
        print("No question found in request; returning fallback answer.")
        return jsonify({"answer": "I didn’t receive a question to answer."})

    print(f"User question: {question!r}")

    try:
        # Create a new thread with the user's question
        thread = client.beta.threads.create(
            messages=[{"role": "user", "content": question}]
        )

        # Kick off a run for the assistant
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
        )

        # Poll until the run completes (or errors)
        while run.status in ("queued", "in_progress"):
            time.sleep(1.0)
            run = client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id,
            )

        if run.status != "completed":
            print(f"Run ended with status={run.status}, last_error={run.last_error}")
            return jsonify(
                {
                    "answer": "I’m having trouble answering right now. "
                              "Please try again or talk to a human.",
                }
            )

        # Fetch the messages and find the latest assistant message
        msgs = client.beta.threads.messages.list(thread_id=thread.id)
        answer_text = "I’m not sure how to answer that."

        for msg in msgs.data:
            if msg.role == "assistant":
                parts = []
                for part in msg.content:
                    if part.type == "text":
                        parts.append(part.text.value)
                if parts:
                    answer_text = "\n\n".join(parts)
                    break

        print("Walter answer:", answer_text)
        return jsonify({"answer": answer_text})

    except Exception as e:
        print("Error talking to OpenAI:", repr(e))
        return jsonify(
            {
                "answer": "Something went wrong while talking to Walter’s brain. "
                          "Please try again in a bit.",
            }
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
