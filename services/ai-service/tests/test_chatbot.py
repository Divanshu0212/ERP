import app.chatbot as chatbot


def test_chatbot_bus_time(client, monkeypatch):
    # Monkeypatch the transport API call so no real gateway is needed.
    monkeypatch.setattr(
        chatbot,
        "_fetch_next_bus",
        lambda text, token: "5:30 PM",
    )
    resp = client.post("/ai/chatbot/query", json={"text": "when is my next bus"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "bus_time"
    assert "5:30 PM" in data["answer"]


def test_chatbot_fallback(client):
    resp = client.post("/ai/chatbot/query", json={"text": "asdfqwer nonsense"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "fallback"
    assert "bus" in data["answer"].lower()
