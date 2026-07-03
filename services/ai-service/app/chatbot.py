"""Chatbot intent routing — TF-IDF + LinearSVC over a small seed dataset.

Lightweight ML only (no transformers): a scikit-learn Pipeline
(TfidfVectorizer -> LinearSVC) trained once at import time on the hardcoded
seed utterances below. Recognised intents are
``{bus_time, library_fine, mess_menu, fee_balance}`` plus a ``fallback``.

Because LinearSVC always predicts *some* class, we gate low-confidence
predictions to ``fallback`` using the decision-function margin: if the top
margin is below ``CONFIDENCE_THRESHOLD`` the query is treated as unrecognised.

For a recognised intent, ``route_intent`` produces the answer. Real service
calls go through the API gateway (``settings.GATEWAY_URL``) via httpx; only
``bus_time`` is wired to a live call here (``_fetch_next_bus``), and it is
factored out so tests can monkeypatch it without a gateway/token.
"""

import logging

import httpx
from app.config import settings
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

logger = logging.getLogger(__name__)

FALLBACK = "fallback"

# Below this decision-function margin, treat the prediction as unrecognised.
CONFIDENCE_THRESHOLD = 0.15

# --- Seed training data (hardcoded; ~a dozen utterances per intent) ----------
_SEED: dict[str, list[str]] = {
    "bus_time": [
        "when is my next bus",
        "what time does the bus leave",
        "next bus departure time",
        "when does the shuttle arrive",
        "bus timing for route 5",
        "what is the bus schedule today",
        "when is the next campus bus",
        "how long until the next bus",
        "bus departure from hostel",
        "when will the bus come",
        "next shuttle time please",
        "give me the bus timings",
    ],
    "library_fine": [
        "how much is my library fine",
        "do i have any overdue book fines",
        "library late fee amount",
        "what is my outstanding library fine",
        "check my library dues",
        "fine for returning a book late",
        "how much do i owe the library",
        "my library penalty balance",
        "overdue book charges",
        "pending library fines on my account",
        "library fine details",
        "how much fine for late return",
    ],
    "mess_menu": [
        "what is on the mess menu today",
        "todays mess menu",
        "what is for dinner in the mess",
        "mess food menu for lunch",
        "what are they serving in the mess",
        "show me the mess menu",
        "whats cooking in the mess",
        "menu for the mess tonight",
        "what is the breakfast menu",
        "food menu in the canteen today",
        "mess special today",
        "what is being served for lunch",
    ],
    "fee_balance": [
        "what is my fee balance",
        "how much tuition fee do i owe",
        "check my outstanding fees",
        "my pending fee amount",
        "what is my current fee due",
        "how much fees left to pay",
        "show my fee statement",
        "remaining balance on my fees",
        "total fees payable",
        "do i have any unpaid fees",
        "fee dues on my account",
        "what is my semester fee balance",
    ],
}


def _train() -> Pipeline:
    texts: list[str] = []
    labels: list[str] = []
    for intent, utterances in _SEED.items():
        texts.extend(utterances)
        labels.extend([intent] * len(utterances))

    model = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
            ("clf", LinearSVC()),
        ]
    )
    model.fit(texts, labels)
    return model


_MODEL = _train()


def classify(text: str) -> str:
    """Return the predicted intent, or ``fallback`` if confidence is too low."""
    if not text or not text.strip():
        return FALLBACK
    margins = _MODEL.decision_function([text])[0]
    top = float(max(margins))
    if top < CONFIDENCE_THRESHOLD:
        return FALLBACK
    return str(_MODEL.classes_[margins.argmax()])


def _fetch_next_bus(text: str, token: str | None) -> str:
    """Call the transport API through the gateway; return next departure time.

    Factored out so tests can monkeypatch it. Best-effort: on any error return
    a neutral placeholder rather than crashing the chat turn.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = httpx.get(
            f"{settings.GATEWAY_URL}/api/v1/transport/next-bus",
            headers=headers,
            timeout=5.0,
        )
        resp.raise_for_status()
        return str(resp.json().get("departure", "shortly"))
    except Exception:
        logger.warning("transport next-bus lookup failed", exc_info=True)
        return "shortly"


_FALLBACK_ANSWER = "I can help with bus timings, library fines, mess menu, and fee balance."


def route_intent(intent: str, text: str, token: str | None) -> str:
    """Produce a templated answer for a classified intent."""
    if intent == "bus_time":
        departure = _fetch_next_bus(text, token)
        return f"Your next bus departs at {departure}."
    if intent == "library_fine":
        return "You can check your library fine on the library dues page."
    if intent == "mess_menu":
        return "Today's mess menu is available on the hostel mess board."
    if intent == "fee_balance":
        return "You can view your fee balance on the finance portal."
    return _FALLBACK_ANSWER


def answer(text: str, token: str | None = None) -> dict:
    """Classify ``text`` and return ``{"intent": ..., "answer": ...}``."""
    intent = classify(text)
    return {"intent": intent, "answer": route_intent(intent, text, token)}
