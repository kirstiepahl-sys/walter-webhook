import os
import logging
from flask import Flask, request, jsonify
from openai import OpenAI

# -----------------------------------------------------------------------------
# Basic setup
# -----------------------------------------------------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

client = OpenAI()  # Uses OPENAI_API_KEY from env

# Your vector store ID (from OpenAI)
VECTOR_STORE_ID = "vs_6920cf818eb8819187f1fcf4c64aba92"

SYSTEM_INSTRUCTIONS = """
You are “Walter”, Intoxalock’s AI support assistant.

Your job is to answer ONLY using the information found in the documents and snippets provided to you in context (file_search results, FAQs, manuals, wiring documentation, state rules, perks rules, etc.).

Rules:
- If the answer is clearly supported by the provided documents, answer concisely and clearly.
- If you are not sure, or the documents do NOT contain the answer, say you don’t have that information and suggest the user contact Intoxalock support or ask to be transferred to a representative. Do NOT guess or invent policies, prices, legal guidance, or wiring details.
- Always assume questions are about installing, servicing, or supporting Intoxalock devices, service centers, or customers.
- For wiring / installation questions, if the user has not already provided it, ALWAYS ask clarifying questions to get:
  - Year
  - Make
  - Model
  - Push-button vs standard (if relevant)
- After you have the necessary details, use the docs to locate the best matching wiring / install information and explain it clearly. If a specific document or diagram is referenced in the context, describe it and, if a URL is included in the text, refer to it as “here” instead of pasting a long URL.
- Keep answers focused. Use bullet points only when it makes things much clearer for the user.
- At the end of each answer, add a short follow-up like:
  “What else can I help you with about your Intoxalock install or account?”
- Never answer general questions unrelated to Intoxalock. Instead say:
  “I’m only able to answer questions based on Intoxalock documentation and policies.”
"""

# -----------------------------------------------------------------------------
# Helper: call OpenAI Responses API with file_search
# -----------------------------------------------------------------------------
def ask_walter(user_message: str, previous_response_id: str | None = None) -> str:
    """
    Sends the user message to OpenAI Responses API with file_search enabled.
    Returns plain answer text.
    """
    if not VECTOR_STORE_ID:
        logging.error("VECTOR_STORE_ID is not set")
        return (
            "I’m currently not able to access my knowledge base. "
            "Please contact Intoxalock support for help."
        )

    try:
        response = client.responses.create(
            model="gpt-4o-mini",  # or "gpt-4o" if you want the bigger model
            instructions=SYSTEM_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
            tools=[{"type": "file_search"}],
            tool_resources={
                "file_search": {
                    "vector_store_ids": [VECTOR_STORE_ID]
                }
            },
            previous_response_id=previous_response_id,
            max_output_tokens=800,
        )

        # Try to grab the answer text
        answer_text = getattr(response, "output_text", None)
        if not answer_text:
            try:
                # Fallback path if output_text isn't set
                answer_text = response.output[0].content[0].text
            except Exception:
                logging.warning("Could not parse output_text from response")
                answer_text = ""

        if not answer_text:
            return (
                "I’m not seeing enough information in my documents to answer that. "
                "Please try rephrasing your question or ask to be connected to a representative."
            )

        return answer_text.strip()

    except Exception as e:
        logging.exception("Error calling OpenAI: %s", e)
        return (
            "I ran into a problem trying to look that up. "
            "Please try again in a moment or ask to be connected to a representative."
        )

# -----------------------------------------------------------------------------
# Flask endpoint for SalesIQ webhook
# -----------------------------------------------------------------------------
@app.route("/walter", methods=["POST"])
def walter_endpoint():
    """
    Expected JSON from SalesIQ webhook block:
    {
        "user_message": "text from visitor",
        "previous_response_id": "optional OpenAI response id"  (we can extend later)
    }

    Returns JSON:
    {
        "success": true,
        "answer": "Walter's reply text"
    }
    """
    data = request.get_json(silent=True) or {}

    user_message = (data.get("user_message") or "").strip()
    previous_response_id = data.get("previous_response_id")

    if not user_message:
        return jsonify(
            {
                "success": False,
                "answer": "I didn’t catch that. What would you like help with?",
            }
        )

    answer = ask_walter(user_message, previous_response_id)

    return jsonify(
        {
            "success": True,
            "answer": answer,
            # You can add "response_id": response.id later if you want threading
        }
    )

if __name__ == "__main__":
    # e.g. python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
