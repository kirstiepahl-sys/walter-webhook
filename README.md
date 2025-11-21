
# Walter Webhook for Zoho SalesIQ (Python + Flask)

This project exposes a single webhook endpoint that connects your Zoho SalesIQ bot
to your OpenAI Assistant **Walter**.

## Endpoint

- `POST /walter`

Request body (example SalesIQ payload):

```json
{
  "question": "Where do I log into the Microsite?"
}
```

Response body:

```json
{
  "reply": "Go to https://servicecenter.intoxalock.com and sign in using your Service Center email."
}
```

## Environment Variables

- `OPENAI_API_KEY` – your OpenAI API key (required)

The Assistant ID is already set to:

```text
asst_Q0N8ruhG6yWlUNPtk1HZca7
```

## Local Run

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
python app.py
```

The server will start on `http://localhost:8000/walter`.

## Deploy to Railway

1. Create a new GitHub repository and push these files.
2. Go to [Railway](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
3. Choose your repo.
4. In the Railway project settings, add an environment variable:

   - `OPENAI_API_KEY = your_real_key_here`

5. Deploy. After deploy, Railway will give you a public URL like:

   `https://yourproject.up.railway.app`

   Your webhook endpoint for SalesIQ is:

   `https://yourproject.up.railway.app/walter`

6. In Zoho SalesIQ, create a Webhook Bot and set **URL to be invoked** to the `/walter` URL above.
