import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


@app.route("/walter", methods=["GET", "POST"])
def walter():
    """
    Temporary 'echo' Walter:
    - GET: simple health check
    - POST: used by SalesIQ, expects JSON { "user_message": "..." }
    """

    logging.info("Walter hit with method %s", request.method)

    if request.method == "GET":
        # Browser or test pings
        return jsonify({
            "success": True,
            "answer": "Walter endpoint is up. Send a POST with {\"user_message\": \"...\"}."
        })

    # POST: from SalesIQ
    data = request.get_json(silent=True) or {}
    logging.info("POST /walter body: %s", data)

    user_message = (data.get("user_message") or "").strip()

    if not user_message:
        return jsonify({
            "success": False,
            "answer": "I didn’t catch that. What would you like help with?"
        })

    # For now, just echo back what the visitor said
    return jsonify({
        "success": True,
        "answer": f"You said: {user_message}"
    })


if __name__ == "__main__":
    # Local dev; Railway will use gunicorn
    app.run(host="0.0.0.0", port=8000)
