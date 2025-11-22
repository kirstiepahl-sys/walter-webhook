from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")


@app.route("/walter", methods=["POST"])
def walter():
    # Try to read JSON body (SalesIQ body parameters)
    data = request.get_json(silent=True) or {}

    print("RAW JSON BODY:", data)
    print("RAW QUERY PARAMS:", dict(request.args))

    # Try all the possible keys & locations we’ve used so far
    question = (
        data.get("visitor_question") or
        data.get("question") or
        request.args.get("visitor_question") or
        request.args.get("question") or
        ""
    ).strip()

    print("EXTRACTED QUESTION:", repr(question))

    if not question:
        # Friendly message so you can still see *something* in SalesIQ
        return jsonify({
            "answer": (
                "I didn’t receive a question to answer. "
                "Please type your Intoxalock service center question again."
            )
        })

    # ------------------------------
    # Call your Assistant
    # ------------------------------
    url = f"https://api.openai.com/v1/assistants/{ASSISTANT_ID}/messages"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "role": "user",
        "content": question,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        result = resp.json()
        print("OPENAI RAW RESPONSE:", result)

        # Adjust this extraction to your real Assistants response shape
        answer = result["choices"][0]["message"]["content"]
    except Exception as e:
        print("ERROR TALKING TO OPENAI:", repr(e))
        answer = (
            "Sorry, I ran into a problem while generating an answer. "
            "Please try again or contact Intoxalock support."
        )

    return jsonify({"answer": answer})


@app.route("/")
def home():
    return "Walter webhook running."


if __name__ == "__main__":
    # Railway will override the port; 8080 is safe default
    app.run(host="0.0.0.0", port=8080)
