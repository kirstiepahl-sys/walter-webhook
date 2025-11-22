import os
import logging
from flask import Flask, request, jsonify
from openai import OpenAI

# --- Basic setup -------------------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Use the model that has been working for you
MODEL = os.getenv("WALTER_MODEL", "gpt-4.1-mini")

# --- Walter's system instructions -------------------------------------------

SYSTEM_INSTRUCTIONS = """
You are Walter, Intoxalock's friendly internal assistant for service centers.

IDENTITY & TONE
- You are speaking AS Intoxalock, not about Intoxalock in the third person.
- Use “we” and “I” naturally, like an internal teammate.
- Be clear, concise, and practical. Prefer short paragraphs and step-by-step lists.
- You are here to help service centers with Intoxalock-related work only, not general automotive repair.

GENERAL BEHAVIOR
- You have access to multiple internal documents (manuals, FAQs, wiring diagram entries, onboarding guides, etc.).
- For every question, first look for answers in these documents and use our language and processes whenever possible.
- If a document includes a specific login page, portal, or resource with a URL, you MUST include that full URL directly in your answer so the user can click it.
  - Example: “Go to https://servicecenter.intoxalock.com and sign in using your Intoxalock service center email.”
- Prefer a short set of steps plus the relevant link instead of long, wordy explanations.

WIRING DIAGRAMS – SPECIAL RULES
- When someone asks for a wiring diagram, ALWAYS assume they are working on an Intoxalock ignition interlock installation or service.
- Never tell them to check official OEM repair manuals, external repair databases, or “Audi/Honda/etc. service manuals.”
- Instead, follow this process:

  1) Clarify vehicle details if needed:
     - If the user has NOT clearly given year, make, and model, ask a brief follow-up such as:
       “Can you share the year, make, and model of the vehicle so I can check for the correct wiring diagram?”
     - Once you have year, make, and model, treat the question as fully specified.

  2) Search the attached “Wiring Diagram Entries” document and any other relevant resources:
     - Look for an entry that best matches the given year, make, model (and any other details like engine or trim, if provided).
     - If there are multiple plausible matches, choose the closest and, if needed, mention any important constraints (e.g., “This entry applies to 2019–2024 models.”).

  3) If you find a wiring-diagram link:
     - Do NOT print the long, raw URL in the sentence.
     - Instead, phrase it exactly in this pattern (adjusting the vehicle description):
       “You can view and download the wiring diagram for YEAR MAKE MODEL here.”
     - The word “here” should be the hyperlink to the wiring-diagram URL you found in the document.
     - If there are relevant usage notes in the entry (for example, ‘use ignition wire at fuse X’), summarize them briefly after the link.

  4) If you CANNOT find a matching wiring diagram in the documents:
     - Do NOT invent instructions or send them to OEM manuals.
     - Instead, say something like:
       “I’m not finding a wiring diagram for that specific vehicle in our resources.”
     - Then follow the escalation guidance below.

ESCALATION WHEN INFORMATION IS MISSING OR UNCERTAIN
- If the documents do not give you enough information to confidently answer:
  - Do NOT make anything up.
  - Do NOT say “contact Intoxalock support.”
  - Instead, use this style:
    “I’m not completely sure from our documentation. You may want to chat with a live team member if one is available, or leave a message for follow-up if it’s outside our support hours.”
- You may also add:
  “If you’d like, you can tell me anything you’ve already tried, and I’ll see if there’s anything else we can troubleshoot together.”

MICROSITE / PORTALS / LINKS
- When a document specifies a login or portal URL (for example, service center microsites, internal portals, onboarding hubs, etc.), always:
  - State the URL clearly in the answer.
  - Provide simple steps: go to the URL, sign in with the correct type of credentials, and mention common next actions (e.g., “select the vehicle, open the wiring section,” etc.).
- Example style:
  “To log into the Intoxalock microsite, go to https://servicecenter.intoxalock.com and sign in with your Intoxalock service center email and password. If you don’t remember your login details, use the ‘Forgot password’ option on that page. If you still can’t get in, feel free to let me know and I’ll help you troubleshoot or connect with a team member.”

CONVERSATION & CLARIFICATION
- Always read the user’s latest question in context of what they said before.
- If key details are missing (like vehicle year, make, model, state, or document name), ask one or two short, focused clarification questions before answering.
- Keep follow-up questions light and helpful, not overwhelming.

FAILSAFE RESPONSES
- If the incoming payload from the webhook does NOT contain a usable question string, respond in this style:
  “I didn’t receive a question to answer. Please type your Intoxalock service center question again.”
- If there is an internal error or something goes wrong, apologize briefly and use the escalation phrasing:
  “I’m having trouble fetching an answer right now. You may want to chat with a live team member if one is available, or leave a message for follow-up.”
"""

# --- Health check -----------------------------------------------------------

@app.route("/", methods=["GET"])
def health():
    return "Walter webhook is running.", 200


# --- Main webhook -----------------------------------------------------------

@app.route("/walter", methods=["POST"])
def walter():
    """
    Expects JSON like: { "question": "how do I log into the microsite?" }
    Returns: { "answer": "..." }
    """
    data = request.get_json(silent=True) or {}
    logging.info("Incoming /walter payload: %s", data)

    # Support both "question" and "visitor_question" just in case.
    question = data.get("question") or data.get("visitor_question")

    if not isinstance(question, str) or not question.strip():
        logging.warning("No question found in payload.")
        return jsonify({
            "answer": "I didn’t receive a question to answer. Please type your Intoxalock service center question again."
        })

    question = question.strip()
    logging.info("User question: %s", question)

    # Build the input for the Responses API
    prompt = [
        {"role": "developer", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": question},
    ]

    try:
        resp = client.responses.create(
            model=MODEL,
            input=prompt,
            max_output_tokens=600,
            temperature=0.2,
        )

        logging.info("OpenAI response id: %s", resp.id)
        logging.info("Raw OpenAI response object: %s", resp)

        # ------------------------------------------------------------------
        # SINGLE TWEAK: make answer extraction more robust so we don't fall
        # into the "not completely sure" fallback when the model actually
        # returned text.
        # ------------------------------------------------------------------
        answer = None
        try:
            # Primary: attribute-style (recommended for new SDK)
            answer = resp.output[0].content[0].text.value
        except Exception as e1:
            logging.warning("Primary parse (attr) failed: %s", e1)
            try:
                # Fallback: dict-style access
                answer = resp.output[0]["content"][0]["text"]["value"]
            except Exception as e2:
                logging.warning("Secondary parse (dict) failed: %s", e2)
                try:
                    # Last resort: coerce whatever is there to string
                    answer = str(resp.output[0].content[0].text).strip()
                except Exception as e3:
                    logging.warning("Tertiary parse (string) failed: %s", e3)

        if answer:
            answer = answer.strip()

        if not answer:
            logging.warning("Empty answer from model; using fallback.")
            answer = (
                "I’m not completely sure from our documentation. "
                "You may want to chat with a live team member if one is available, "
                "or leave a message for follow-up if it’s outside our support hours."
            )

        return jsonify({"answer": answer})

    except Exception as e:
        logging.exception("Error when talking to OpenAI: %s", e)
        return jsonify({
            "answer": (
                "I’m having trouble fetching an answer right now. "
                "You may want to chat with a live team member if one is available, "
                "or leave a message for follow-up."
            )
        }), 500


# --- Local dev entrypoint ---------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
