import os
from flask import Flask, request, jsonify
from openai import OpenAI

# Create OpenAI client – no custom httpx / proxies, just env var
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

# Your existing Assistant ID from the OpenAI dashboard
ASSISTANT_ID = "YOUR_ASSISTANT_ID_HERE"

app = Flask(__name__)


@app.route("/walter", methods=["POST"])
def walter():
    """
    Webhook endpoint that SalesIQ calls.

    Expects JSON body like:
        { "question": "How do I log in to the microsite?" }

    Returns:
        { "answer": "..." }
    """
    try:
        # Safely parse JSON
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            # SalesIQ will see this and you’ll also no longer get
            # “insufficient data” for truly empty payloads.
            return jsonify({
                "answer": "I didn’t receive a question to answer."
            }), 200

        # 1) Create a thread with the user's question
        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": question
                }
            ]
        )

        # 2) Run the assistant and wait for completion
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
            # optional: tweak style a bit
            temperature=0.4,
        )

        if run.status != "completed":
            # The run didn’t finish successfully; don’t crash
            return jsonify({
                "answer": "I wasn’t able to generate a response just now. "
                          "Please try asking again in a moment."
            }), 200

        # 3) Fetch the latest assistant message
        messages = client.beta.threads.messages.list(
            thread_id=thread.id,
            limit=1
        )

        answer_text = ""

        # messages.data is newest-first
        for msg in messages.data:
            for part in msg.content:
                if part.type == "text":
                    answer_text = part.text.value
                    break
            if answer_text:
                break

        if not answer_text:
            answer_text = (
                "I couldn’t find a clear answer for that. "
                "You may want to contact support for more help."
            )

        # 4) Return JSON that matches your SalesIQ mapping
        return jsonify({"answer": answer_text}), 200

    except Exception as e:
        # Log to stdout so Railway logs show the error
        print("Error in /walter endpoint:", repr(e))

        # Still return a safe JSON structure so SalesIQ doesn't explode
        return jsonify({
            "answer": "Something went wrong while I was trying to answer that. "
                      "Please try again, or contact support directly."
        }), 500


if __name__ == "__main__":
    # For local testing; Railway will set PORT env var
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
