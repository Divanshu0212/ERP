"""Grievance scoring — polarity via VADER + rule-based urgency.

Design: rule-based / lightweight only (project decision — no transformers/torch).
``score`` is a pure function so both the HTTP route and the event consumer share
one deterministic implementation and it is trivially unit-testable.

Urgency is decided by keyword tables (module constants below, exposed as a test
hook). VADER's ``compound`` score (-1..1) provides sentiment and also bumps a
"low" urgency to "medium" when the text is strongly negative.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# --- Urgency keyword tables (test hook: patch/extend these in tests) ---------
# Safety/abuse terms -> always "critical".
CRITICAL_KEYWORDS = {
    "ragging",
    "harassment",
    "threat",
    "threatening",
    "abuse",
    "assault",
    "safety",
    "suicide",
    "unsafe",
}
# Facilities/service disruption -> "medium".
MEDIUM_KEYWORDS = {
    "broken",
    "leak",
    "no water",
    "no electricity",
    "power",
    "wifi down",
    "urgent",
}

# Sentiment at or below this compound score bumps a "low" urgency to "medium".
NEGATIVE_BUMP_THRESHOLD = -0.6

_analyzer = SentimentIntensityAnalyzer()


def _contains_any(text: str, keywords: set[str]) -> bool:
    """Case-insensitive, word-ish membership test.

    Single-word keywords match on whitespace-delimited tokens (so "power" does
    not fire on "empower"); multi-word keywords ("no water") match as a phrase
    substring.
    """
    lowered = text.lower()
    tokens = set(lowered.split())
    for kw in keywords:
        if " " in kw:
            if kw in lowered:
                return True
        elif kw in tokens:
            return True
    return False


def score(text: str) -> dict:
    """Return ``{"sentiment": float (-1..1), "urgency": str}`` for ``text``.

    ``urgency`` is one of "critical" | "medium" | "low".
    """
    sentiment = float(_analyzer.polarity_scores(text or "")["compound"])

    if _contains_any(text, CRITICAL_KEYWORDS):
        urgency = "critical"
    elif _contains_any(text, MEDIUM_KEYWORDS):
        urgency = "medium"
    else:
        urgency = "low"

    # Strongly negative sentiment nudges an otherwise-"low" grievance up.
    if urgency == "low" and sentiment <= NEGATIVE_BUMP_THRESHOLD:
        urgency = "medium"

    return {"sentiment": sentiment, "urgency": urgency}
