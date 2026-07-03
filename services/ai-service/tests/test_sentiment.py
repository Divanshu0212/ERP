from app.sentiment import score


def test_score_critical_and_negative():
    result = score("the warden is threatening me, this is ragging")
    assert result["urgency"] == "critical"
    assert result["sentiment"] < 0


def test_score_low():
    result = score("the mess food was okay today")
    assert result["urgency"] == "low"


def test_sentiment_endpoint(client):
    resp = client.post(
        "/ai/sentiment", json={"text": "the warden is threatening me, this is ragging"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["urgency"] == "critical"
    assert data["sentiment"] < 0
