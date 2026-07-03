"""FastAPI app — health, sentiment scoring, and chatbot intent routing.

Response shape: this service is NOT behind the Django ``{success, data}``
envelope; it returns the score/answer dicts directly (documented, simple).

Auth: ``/health`` is open. ``/ai/sentiment`` and ``/ai/chatbot/query`` are left
open for this task to keep it testable without minting tokens; the gateway sits
in front of them. A bearer token, when present, is passed through to downstream
service calls (see ``chatbot.route_intent``). HS256 verification with
``settings.JWT_SIGNING_KEY`` can be layered on here later if these routes are
exposed directly.
"""

from app.chatbot import answer
from app.sentiment import score
from fastapi import FastAPI, Request
from pydantic import BaseModel

app = FastAPI(title="SU-ERP ai-service", version="1.0.0")


class TextIn(BaseModel):
    text: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ai/sentiment")
def sentiment(body: TextIn) -> dict:
    """Score grievance text: ``{"sentiment": float, "urgency": str}``."""
    return score(body.text)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    return None


@app.post("/ai/chatbot/query")
def chatbot_query(body: TextIn, request: Request) -> dict:
    """Classify intent and answer: ``{"intent": str, "answer": str}``."""
    return answer(body.text, token=_bearer_token(request))
