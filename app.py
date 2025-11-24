import os
import logging
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

# Your vector store ID
VECTOR_STORE_ID = "vs_6920cf818eb8819187f1fcf4c64aba92"


@app.route("/walter", methods=["GET", "POST"])
def walter_endpoint():
    """
    - GET: Used for browser health checks
    - POST: Used by SalesIQ webhook. Expects:
        {
            "user_message": "text...",
            "previous_response_id": "optional"
        }
    """

    logging.info("=== Walter endpoint hit: method=%s ===", request.method)

    # --------------------------
    # Handle GET (browser test)
    # --------------------------
    if request.method == "GET":
        logging.info("GET /walter query params: %s", dict(request.args))

        return jsonify({
            "success": True,
            "answer": (
                "Walter endpoint is active. "
                "Send a POST request with JSON {\"user_message\": \"your question\"}"
            )
        })

    # --------------------------
    # Handle POST (SalesIQ)
    # --------------------------
    data = request.get_json(silent=True) or {}
    logging.info("POST /walter body received: %s", data)

    user_message = (data.get("user_message") or "").strip()
    previous_response_id = data.get("previous_response_id")

    if not user_message:
        logging.warning("POST /walter missing user_message")
        return jsonify({
            "success": False,
            "answer": "Sorry — I didn’t catch that. What do you need help with?"
        })

    # Generate AI response from Walter
    answer = ask_walter(user_message, previous_response_id)

    return jsonify({
        "success": True,
        "answer": answer
    })


def ask_walter(user_message, previous_response_id=None):
    """
    Sends user_message to the OpenAI Assistant with file search enabled.
    """

    try:
        logging.info("Sending query to OpenAI Assistant: %s", user_message)

        response = client.responses.create(
            model="gpt-4.1",
            input=user_message,
            previous_response_id=previous_response_id,
            extra_body={
                "search": {
                    "vectorized_queries": [
                        {"content": user_message}
                    ],
                    "vector_store_ids": [VECTOR_STORE_ID]
                }
            }
        )

        answer = response.output_text
        logging.info("OpenAI Assistant response: %s", answer)
        return answer

    except Exception as e:
        logging.exception("Error calling OpenAI Assistant")
        return (
            "I'm having trouble retrieving that information right now. "
            "Please try again, or ask something else!"
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
