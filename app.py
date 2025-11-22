import os
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# ---- OpenAI client & Assistant ----
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ASSISTANT_ID = os.getenv("ASSISTANT_ID")


@app.route("/", methods=["GET"])
def health_check():
    return "OK", 200


@app.route("/walter", methods=["POST"])
def walter():
    # Safely parse JSON body
    data = request.get_json(silent=True)

    # 🔍 DEBUG: log whatever SalesIQ is sending
    print("\n----------------------------")
    print("RAW REQUEST FROM SALESIQ:")
    print(data)
    print("----------------------------\n")

    # If nothing came in at all
    if not data:
        return jsonify({
            "answer": "I didn’t receive a question to answer. Please type your question and send it again."
        })

    # Try multiple possible field names, but we expect `visitor_question`
    question = (
        data.get("visitor_question")
        or data.get("visitor.question")
        or data.get("question")
    )

    # If the question field is missing or empty
    if not question or not str(question).strip():
        return jsonify({
            "answer": "I didn’t receive a question to answer. Please type your question and send it again."
        })

    question = str(question).strip()

    try:
        # Create a thread seeded with the user's question
        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": question,
                }
            ]
        )

        # Run the Assistant and wait for completion
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
        )

        if run.status != "completed":
            print("Run did not complete normally:", run.status)
            return jsonify({
                "answer": "I had trouble answering that just now. Please try again in a moment."
            })

        # Get the latest message from the thread (Assistant's reply)
        messages = client.beta.threads.messages.list(
            thread_id=thread.id,
            order="desc",
            limit=1,
        )

        answer_text = ""

        if messages.data:
            msg = messages.data[0]
            for part in msg.content:
                # Text parts (ignore images / other content types)
                if getattr(part, "type", None) == "text":
                    answer_text += part.text.value

        if not answer_text.strip():
            answer_text = (
                "I’m not sure how to answer that yet. "
                "Please reach out to Intoxalock support for help."
            )

        return jsonify({"answer": answer_text})

    except Exception as e:
        # Log server-side error for debugging
        print("Error talking to OpenAI:", repr(e))
        return jsonify({
            "answer": "I ran into an error while answering that. "
                      "Please try again or contact the Intoxalock team."
        }), 500


if __name__ == "__main__":
    # Railway usually injects PORT; default to 8080 if not
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
