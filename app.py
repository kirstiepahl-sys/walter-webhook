import os
import logging
from flask import Flask, request, jsonify
from openai import OpenAI

# ---------------------------------------------------------------------
# Basic setup
# ---------------------------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# OpenAI client
client = OpenAI()

# Assistant ID for Walter (set this in your environment or hard-code)
ASSISTANT_ID = os.environ.get("OPENAI_ASSISTANT_ID", "asst_your_walter_id_here")

# In-memory thread store: maps a SalesIQ conversation/chat id to an OpenAI thread id.
# If you scale this beyond a single process, move this to Redis or a database.
thread_store = {}

# ---------------------------------------------------------------------
# Per-request "nudger" instructions
# ---------------------------------------------------------------------
# These get merged into Walter's existing system instructions on EVERY run,
# so he stays on-script even in long conversations.
REMINDER_SYSTEM_MESSAGE = """
Follow your system instructions exactly.

For ANY wiring diagram request:
- Treat it as a wiring-diagram workflow.
- You must collect vehicle year, make, model, and ignition type if they are not already known.
- You are ONLY allowed to use the document named "Master Wiring Diagrams with Links" to locate wiring diagrams.
- Do NOT search or use any other manuals or documents for wiring diagrams.
- Use the columns Vehicle Year, Vehicle Make, Vehicle Model, Vehicle Ignition Type, Diagram Name, and Link to Diagram to find the correct row.
- If a match is found, respond with: "Here is the wiring diagram — click here." and hyperlink the word "here" to the URL.
- If no match is found in that master document, route the user to Service Center Technical Support at 1-877-327-9130 option 2 or sctech@intoxalock.com.

Never begin wiring responses with phrases like:
- "I found information related to wiring diagrams in the manual..."
- "The manual says..."

You may still use other documents for NON-wiring questions, but wiring questions must always follow the master-document workflow.

Also remember:
- Apply routing rules and live-representative logic as defined in your system instructions.
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

    # Get or create a thread for this conversation
    thread_id = get_or_create_thread_id(conversation_id)

    # Add the user's message to the thread
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_message,
    )

    # Run Walter on this thread, with the reminder instructions merged in
    try:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
            instructions=REMINDER_SYSTEM_MESSAGE,
            temperature=0.2,
        )
    except Exception as e:
        logging.exception("Error while creating/polling run")
        return jsonify({
            "answer": "I ran into an issue while processing your request. Please try again or contact support directly."
        })

    # Fetch the latest assistant message from the thread
    try:
        messages = client.beta.threads.messages.list(
            thread_id=thread_id,
            limit=5  # small window; newest messages are returned first
        )
    except Exception as e:
        logging.exception("Error while listing messages")
        return jsonify({
            "answer": "I wasn’t able to retrieve a response just now. Please try again or contact support directly."
        })

    answer_text = ""

    # messages.data is usually ordered newest-first for beta.threads.messages.list
    for msg in messages.data:
        if msg.role == "assistant":
            # Each message can have multiple content parts; we only care about text
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
    # Use environment variables or defaults for host/port as needed
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    app.run(host=host, port=port, debug=debug)

