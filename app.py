import os
import logging
from flask import Flask, request, jsonify
from openai import OpenAI

# ---------------------------------------------------------------------
# Basic setup
# ---------------------------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

client = OpenAI()

# Assistant ID for Walter (set as environment variable or hard-code)
ASSISTANT_ID = os.environ.get("OPENAI_ASSISTANT_ID", "asst_your_walter_id_here")

# In-memory thread store: maps a SalesIQ conversation id to an OpenAI thread id.
# For production, move this to Redis or a database.
thread_store = {}

# ---------------------------------------------------------------------
# Per-request "nudger" instructions
# ---------------------------------------------------------------------
# These get merged into Walter's existing system instructions on EVERY run,
# so he stays on-script even in long conversations.
REMINDER_SYSTEM_MESSAGE = """
Follow your system instructions exactly.

WIRING DIAGRAM REQUESTS:

- Treat EVERY wiring diagram request as a NEW request.
- Ignore any vehicle information that may have been mentioned earlier in the thread
  unless the user's CURRENT message (and your immediate clarifying follow-up) explicitly
  contains all four of: vehicle year, make, model, and ignition type.

- If the user's CURRENT wiring-related message does NOT clearly include vehicle year,
  make, model, AND ignition type:
    - Do NOT search any documents.
    - Do NOT look in "Master Wiring Diagrams with Links".
    - Do NOT use cached or previous vehicle information.
    - Your ONLY response must be a clarifying question asking for the missing details.
    - Do NOT list any wiring diagrams.
    - Do NOT mention any document names.

- Only AFTER you have all four fields (from the user's current message and their
  direct answer to your clarifying question):
    - Search ONLY the document named "Master Wiring Diagrams with Links".
    - Use the columns Vehicle Year, Vehicle Make, Vehicle Model, Vehicle Ignition Type,
      Diagram Name, and Link to Diagram to find the single best matching row.
    - If a match is found, respond with: "Here is the wiring diagram — click here."
      and hyperlink the word "here" to the URL.
    - Do NOT list multiple diagrams.
    - Do NOT mention the document name.
    - Do NOT say "I found information in the document" or similar.

- If no match is found in that master document:
    - Route the user to Service Center Technical Support at 1-877-327-9130 option 2
      or sctech@intoxalock.com.
    - Then apply your live-representative logic as defined in your system instructions.

GENERAL:
- You may use other documents for NON-wiring questions.
- Never start a wiring answer by listing many different diagrams.
- Never start with phrases like "I found information related to wiring diagrams...".
"""

# ---------------------------------------------------------------------
# Helper: get or create a thread for a conversation
# ---------------------------------------------------------------------
def get_or_create_thread_id(conversation_id: str) -> str:
    """
    Get an existing OpenAI thread id for this conversation_id, or create a new one.
    """
    thread_id = thread_store.get(conversation_id)
    if thread_id:
        return thread_id

    thread = client.beta.threads.create()
    thread_id = thread.id
    thread_store[conversation_id] = thread_id
    logging.info(f"Created new thread {thread_id} for conversation {conversation_id}")
    return thread_id


# ---------------------------------------------------------------------
# SalesIQ webhook endpoint
# ---------------------------------------------------------------------
@app.route("/salesiq-webhook", methods=["POST"])
def salesiq_webhook():
    """
    Main webhook endpoint that SalesIQ calls.

    Expects JSON that includes at least:
    - question/message text
    - some conversation or chat id

    Adjust the keys below (question / message / conversation_id / chat_id / visitor_id)
    to match your actual SalesIQ payload if needed.
    """
    data = request.get_json(force=True) or {}
    logging.info(f"Incoming payload: {data}")

    # Try common key names for the user message
    user_message = (
        data.get("question")
        or data.get("message")
        or data.get("text")
        or ""
    )

    # Try common key names for a conversation identifier
    conversation_id = (
        data.get("conversation_id")
        or data.get("chat_id")
        or data.get("visitor_id")
        or "default_conversation"
    )

    if not user_message.strip():
        logging.warning("No user message found in payload.")
        return jsonify({"answer": "I didn’t receive a question to answer."})

    # Optional: if the user explicitly types "restart", reset the thread
    if user_message.strip().lower() in ["restart", "start over", "new chat", "reset"]:
        if conversation_id in thread_store:
            del thread_store[conversation_id]
            logging.info(f"Reset thread for conversation {conversation_id}")
        return jsonify({"answer": "Let’s start fresh. How can we help you today?"})

    # Get or create a thread for this conversation
    thread_id = get_or_create_thread_id(conversation_id)

    # Add the user's message to the thread
    try:
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_message,
        )
    except Exception:
        logging.exception("Error while adding user message to thread")
        return jsonify({"answer": "I ran into an issue receiving your message. Please try again."})

    # Run Walter on this thread, with the reminder instructions merged in
    try:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
            instructions=REMINDER_SYSTEM_MESSAGE,
            temperature=0.2,
        )
    except Exception:
        logging.exception("Error while creating/polling run")
        return jsonify({
            "answer": "I ran into an issue while processing your request. Please try again or contact support directly."
        })

    # Fetch the latest assistant message from the thread
    try:
        messages = client.beta.threads.messages.list(
            thread_id=thread_id,
            limit=5  # newest messages are first
        )
    except Exception:
        logging.exception("Error while listing messages")
        return jsonify({
            "answer": "I wasn’t able to retrieve a response just now. Please try again or contact support directly."
        })

    answer_text = ""

    # Pick the newest assistant message with text content
    for msg in messages.data:
        if msg.role == "assistant":
            for part in msg.content:
                if part.type == "text":
                    answer_text = part.text.value
                    break
            if answer_text:
                break

    if not answer_text:
        logging.warning("No assistant answer found in thread messages.")
        answer_text = "I’m sorry, I wasn’t able to generate a response just now."

    # Return the answer to SalesIQ.
    # Adjust the key ("answer") if your integration expects a different field name.
    return jsonify({"answer": answer_text})


# ---------------------------------------------------------------------
# Basic health check
# ---------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health_check():
    return "Walter webhook is running", 200


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    app.run(host=host, port=port, debug=debug)
