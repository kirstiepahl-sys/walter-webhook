import os
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Hard-coded Assistant ID (your real one)
ASSISTANT_ID = "asst_Q0N8ruhG6yWNJUVPtk1HZca7"

@app.route("/walter", methods=["POST"])
def walter():
    try:
        data = request.get_json(silent=True) or {}
        print("RAW REQUEST:", data)

        question = data.get("question", "").strip()
        print("Extracted question:", question)

        if not question:
            print("ERROR: No question received.")
            return jsonify({"answer": "I didn’t receive a question to answer."})

        # Create a thread
        thread = client.threads.create()
        thread_id = thread.id
        print("Created thread:", thread_id)

        # Add the user question
        client.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=question
        )
        print("Posted question to thread.")

        # Run the assistant
        run = client.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )
        print("Assistant run status:", run.status)

        if run.status != "completed":
            print("ERROR: Run did not complete:", run.status)
            return jsonify({"answer": "Walter could not complete the request."})

        # Get messages
        messages = client.threads.messages.list(thread_id=thread_id)
        print("Messages returned:", messages)

        final_answer = ""

        if messages.data:
            # Get the most recent assistant message
            for msg in messages.data:
                if msg.role == "assistant":
                    final_answer = msg.content[0].text.value
                    break

        if not final_answer:
            final_answer = "I'm sorry — I couldn't find an answer for that."

        print("FINAL ANSWER:", final_answer)

        return jsonify({"answer": final_answer})

    except Exception as e:
        print("ERROR:", str(e))
        return jsonify({"answer": f"Server error: {str(e)}"})


@app.route("/")
def home():
    return "Walter API is running."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
