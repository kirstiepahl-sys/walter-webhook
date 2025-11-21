import os
from flask import Flask, request, jsonify
from openai import OpenAI

# Create Flask app
app = Flask(__name__)

# OpenAI client (uses OPENAI_API_KEY from Railway environment)
client = OpenAI()

# Your existing Assistant ID
ASSISTANT_ID = "asst_Q8N9bhu6VyNNUVPfX1HZca7"


@app.route("/walter", methods=["POST"])
def walter():
    """
    Webhook endpoint for Zoho SalesIQ.
    Expects JSON body: {"question": "<user's text>"}
    Returns JSON: {"answer": "<Walter's reply>"}
    """

    # Safely read JSON body
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    # If somehow we got no question, still return a helpful answer
    if not question:
        return jsonify({
            "answer": "I didn’t receive a question to work with. "
                      "Please try asking again in a full sentence."
        })

    try:
        # Create a new thread with the user's question
        thread = client.beta.threads.create(
            messages=[{
                "role": "user",
                "content": question
            }]
        )

        # Run the Assistant on that thread and wait for completion
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
        )

        # Fetch all messages to get the Assistant's reply
        messages = client.beta.threads.messages.list(thread_id=thread.id)

        answer_text = ""

        # Find the most recent assistant message
        for m in messages.data:
            if m.role == "assistant":
                for c in m.content:
                    if c.type == "text":
                        answer_text = c.text.value
                        break
                if answer_text:
                    break

        # Fallback if we somehow didn't see a text answer
        if not answer_text:
            answer_text = (
                "I’m not sure how to answer that right now. "
                "You can try rephrasing your question or contact support."
            )

        return jsonify({"answer": answer_text})

    except Exception as e:
        # Log error to Railway logs and return a safe message
        print("Error in /walter:", repr(e))
        return jsonify({
            "answer": "I ran into a technical issue trying to answer that. "
                      "Please try again in a moment or contact support."
        })


if __name__ == "__main__":
    # For local testing; Railway will ignore this block and run via gunicorn
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)

