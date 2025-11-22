import os
import json
import logging
import requests

from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("INTX_OPENAI_API_KEY")


def extract_question(payload) -> str:
    """
    Try several ways to pull a 'question' out of the incoming request.
    """

    # 1) If SalesIQ style: {"question": "..."}
    if "question" in payload:
        q = payload["question"]
        if isinstance(q, str) and q.strip() != "":
            return q.strip()

    # 2) From 'data' list
    try:
        data_list = payload.get("data") or payload.get("chat") or []
        if isinstance(data_list, list) and len(data_list) > 0:
            msg = data_list[0].get("question") or ""
            if isinstance(msg, str) and msg.strip() != "":
                return msg.strip()
    except Exception as e:
        logging.info(f"Data parse failed: {e}")

    # 3) Fallback from 'input'
    if "input" in payload:
        maybe = payload["input"]
        if isinstance(maybe, str) and maybe.strip() != "":
            return maybe.strip()

    # 4) From 'visitor' key (some SalesIQ keys live in 'visitor' JSON)
    try:
        visitor = payload.get("visitor") or {}
        if isinstance(visitor, dict):
            msg = visitor.get("question") or visitor.get("input") or ""
            if isinstance(msg, str) and msg.strip() != "":
                return msg.strip()
    except Exception as e:
        logging.info(f"Visitor parse failed: {e}")

    # If we can't parse, just return empty text
    return ""


def call_openai_walter(user_question: str) -> str:
    """
    Send the user's question into Walter via OpenAI.
    """
    if not OPENAI_API_KEY:
        logging.error("INTX_OPENAI_API_KEY not set; cannot call OpenAI.")
        return (
            "I’m having trouble reaching Walter right now. "
            "Please check back later or ask a human for help."
        )

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    # System prompt with microsite + wiring rules
    system_prompt = """
You are Walter, Intoxalock's friendly internal assistant for service centers.

IDENTITY & TONE
- You are speaking AS Intoxalock, not about Intoxalock in the third person.
- Use “we” and “I” naturally, like an internal teammate.
- Be clear, concise, and practical. Prefer short paragraphs and short step-by-step lists.
- You are here to help service centers with Intoxalock-related work only, not general automotive repair.

GENERAL BEHAVIOR
- You have access to multiple internal documents (manuals, FAQs, wiring diagram entries, onboarding guides, etc.).
- For every question, first look for answers in these documents and use our language and processes whenever possible.
- If a document includes a specific login page, portal, or resource with a URL, you MUST include that full URL directly in your answer so the user can click it.
- Prefer a short set of steps plus the relevant link instead of long, wordy explanations.

MICROSITE / PORTALS / LINKS
- When a document specifies a login or portal URL (for example, service center microsites, internal portals, onboarding hubs, etc.), always:
  - State the URL clearly in the answer.
  - Provide simple steps: go to the URL, sign in with the correct type of credentials, and mention common next actions.
- When a user asks “how do I log into the microsite?” or anything similar, always answer in this style:
  - “To log into the Intoxalock microsite, go to https://servicecenter.intoxalock.com and sign in with your Intoxalock service center email and password. If you don’t remember your login details, use the ‘Forgot password’ option on that page. If you still can’t get in, let us know so we can help.”

WIRING DIAGRAMS – SPECIAL RULES
- When someone asks for a wiring diagram, ALWAYS assume they are working on an Intoxalock ignition interlock installation or service.
- Never tell them to check official OEM repair manuals or external repair databases.
- Instead, follow this process:
  1) Clarify vehicle details if needed:
     - If the user has NOT clearly given year, make, and model, ask:
       “Can you share the year, make, and model of the vehicle so I can check for the correct wiring diagram?”
  2) Search the attached “Wiring Diagram Entries” document and any other relevant resources you have:
     - Look for an entry that best matches the given year, make, model (and engine/trim if provided).
  3) If you find a wiring-diagram link:
     - Do NOT print the long raw URL in the sentence.
     - Instead phrase it exactly like:
       “You can view and download the wiring diagram for YEAR MAKE MODEL here.”
     - The word “here” should be the hyperlink to the wiring-diagram URL.
     - Briefly summarize any key notes from the entry (for example, which wire or fuse to use).
  4) If you cannot find a matching wiring diagram in the documents:
     - Do not invent instructions.
     - Say something like:
       “I’m not finding a wiring diagram for that specific vehicle in our resources.”
     - Then use the escalation guidance below.

ESCALATION WHEN INFORMATION IS MISSING OR UNCERTAIN
- If the documents do not give you enough information to confidently answer:
  - Do NOT make anything up.
  - Do NOT just say “contact Intoxalock support.”
  - Instead say:
    “I’m not completely sure from our documentation. You may want to chat with a live team member if one is available, or leave a message for follow-up if it’s outside our support hours.”
  - You may add:
    “If you’d like, you can tell me anything you’ve already tried, and I’ll see if there’s anything else we can troubleshoot together.”

CONVERSATION & CLARIFICATION
- Always read the user’s latest question in context of what they said before.
- If key details are missing (like vehicle year/make/model, state, or document name), ask one or two short, focused clarification questions before answering.
- Keep follow-up questions light and helpful, not overwhelming.
"""

    payload = {
        "model": "gpt-4.1-mini",
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question},
        ],
        "max_output_tokens": 300,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            data=json.dumps(payload),
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        logging.exception("Error calling OpenAI: %s", e)
        return (
            "I’m having trouble getting Walter’s help right now. "
            "Please check back a little later or ask a human for help."
        )

    try:
        response_json = resp.json()
        logging.info("Raw OpenAI response: %s", response_json)

        answer = None

        # Try convenience field first if present
        if isinstance(response_json.get("output_text"), dict):
            answer = response_json["output_text"].get("content")

        # Fallback to older nested structure
        if not answer:
            answer = response_json["output"][0]["content"][0]["text"]["value"]

        if answer:
            answer = answer.strip()

        if not answer:
            raise ValueError("Empty answer from Walter")

        return answer

    except Exception as e:
        logging.exception("Error parsing OpenAI response: %s", e)
        return "Walter was not able to find an answer this time. Please try again."


@app.route("/walter", methods=["POST"])
def walter():
    """
    Main endpoint: accept a JSON payload from Zoho
    and return Walter's answer as JSON.
    """
    payload = request.get_json(force=True) or {}
    logging.info("Incoming payload: %s", payload)

    question = extract_question(payload)

    if not question:
        logging.info("No question found in request; returning fallback answer.")
        # Make sure there's always *some* text in all the common keys
        msg = (
            "I didn't receive a question to answer. "
            "Please type your question in and try again."
        )
        return jsonify({
            "answer": msg,
            "message": msg,
            "text": msg,
        })

    logging.info("Question extracted: %s", question)

    try:
        answer = call_openai_walter(question)
    except Exception as e:
        logging.exception("Unexpected error getting Walter answer: %s", e)
        answer = (
            "I’m sorry, I ran into a problem talking to Walter. "
            "Please connect with a human so we can help you."
        )

    # 🔑 Return the same content under several keys so any mapping still works
    return jsonify({
        "answer": answer,
        "message": answer,
        "text": answer,
    })


if __name__ == "__main__":
    # For local testing, run the app
    app.run(host="0.0.0.0", port=8081)
