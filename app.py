import os
from flask import Flask, request, jsonify
from openai import OpenAI, OpenAIError

app = Flask(__name__)

# OpenAI client
client = OpenAI()

# Your Walter assistant id from the OpenAI UI
ASSISTANT_ID = os.environ.get("OPENAI_ASSISTANT_ID", "").strip()


@app.route("/", methods=["GET"])
def health():
    """Simple health check."""
    return "Walter webhook is running.", 200


@app.route("/walter", methods=["POST"])
def walter():
    try:
        # Get the question from Zoho
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            # Nothing useful sent in, reply gracefully
            return jsonify({
                "answer": "I didn’t receive a question to answer."
            }), 200

        if not ASSISTANT_ID:
            # We can't call the assistant without its id
            print("ERROR: OPENAI_ASSISTANT_ID is not set")
            return jsonify({
                "answer": "My configuration is incomplete (assistant id missing)."
            }), 200

        # 1) Create a thread with the user's message
        thread = client.beta.threads.create(
            messages=[{
                "role": "user",
                "content": question
            }]
        )

        # 2) Run the assistant on that thread
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
        )

        if run.status != "completed":
            # Assistant didn't complete for some reason
            print(f"Run status not completed: {run.status}")
            return jsonify({
                "answer": "I ran into a problem while answering that. Please try again."
            }), 200

        # 3) Fetch messages from the thread and extract assistant text
        messages = client.beta.threads.messages.list(thread_id=thread.id)

        answer_chunks = []
        for m in messages.data:
            if m.role == "assistant":
                for c in m.content:
                    if c.type == "text":
                        answer_chunks.append(c.text.value)

        # Assistant messages are returned newest-first; reverse to get the latest as last
        answer_chunks = list(reversed(answer_chunks))

        if not answer_chunks:
            answer_text = (
                "I couldn’t find a specific answer to that in my knowledge base."
            )
        else:
            answer_text = "\n".join(answer_chunks)

        return jsonify({"answer": answer_text}), 200

    except OpenAIError as e:
        # Errors from OpenAI client itself
        print("OpenAI error in /walter:", repr(e))
        return jsonify({
            "answer": "I’m having trouble talking to my knowledge base right now."
        }), 200

    except Exception as e:
        # Anything else unexpected
        print("Unexpected error in /walter:", repr(e))
        return jsonify({
            "answer": "I hit an unexpected error while answering that."
        }), 200


if __name__ == "__main__":
    # For local testing only. Railway will use its own web server.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)


