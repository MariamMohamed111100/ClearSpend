from app_factory import create_app


def test_build_finance_prompt_contains_user_data():
    from services.insight_service import build_finance_prompt

    prompt = build_finance_prompt(
        user_input="Help me reduce overspending on food",
        monthly_income=5500,
        categories={"Food & Dining": 1450, "Transport": 550},
        recent_transactions=[
            {"merchant": "Starbucks", "amount": 42, "category": "Food & Dining"},
            {"merchant": "Uber", "amount": 120, "category": "Transport"},
        ],
    )

    assert "Monthly Income" in prompt
    assert "Food & Dining" in prompt
    assert "Help me reduce overspending on food" in prompt


def test_landing_and_workspace_pages_render():
    app = create_app(testing=True)
    client = app.test_client()

    landing = client.get("/")
    workspace = client.get("/workspace")

    assert landing.status_code == 200
    assert b"Feel better about" in landing.data
    assert b"Start for free" in landing.data
    assert b"/workspace" in landing.data
    assert workspace.status_code == 200
    assert b"Financial insight advisor" in workspace.data


def test_generate_endpoint_returns_insight(monkeypatch):
    from services import insight_service

    app = create_app(testing=True)

    def fake_generate(*args, **kwargs):
        return "You are on track and can save 15% by cutting dining costs."

    monkeypatch.setattr(insight_service, "generate_financial_insight", fake_generate)

    client = app.test_client()
    response = client.post(
        "/api/insight",
        json={
            "user_input": "Help me reduce overspending on food",
            "monthly_income": 5500,
            "categories": {"Food & Dining": 1450, "Transport": 550},
            "recent_transactions": [
                {"merchant": "Starbucks", "amount": 42, "category": "Food & Dining"},
                {"merchant": "Uber", "amount": 120, "category": "Transport"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["insight"] == "You are on track and can save 15% by cutting dining costs."


def test_generate_endpoint_is_rate_limited(monkeypatch):
    from services import insight_service

    app = create_app(testing=True)
    monkeypatch.setattr(
        insight_service,
        "generate_financial_insight",
        lambda **kwargs: "Use a weekly spending limit.",
    )

    client = app.test_client()
    payload = {"user_input": "How can I save more?"}
    responses = [client.post("/api/insight", json=payload) for _ in range(11)]

    assert all(response.status_code == 200 for response in responses[:10])
    assert responses[-1].status_code == 429


def test_generate_endpoint_accepts_configured_api_key(monkeypatch):
    from services import insight_service

    app = create_app(testing=True)
    app.config["INSIGHT_API_KEY"] = "test-insight-key"
    monkeypatch.setattr(
        insight_service,
        "generate_financial_insight",
        lambda **kwargs: "Keep your savings target visible.",
    )

    client = app.test_client()
    payload = {"user_input": "How can I save more?"}

    unauthorized = client.post("/api/insight", json=payload)
    authorized = client.post("/api/insight", json=payload, headers={"X-API-Key": "test-insight-key"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_browser_session_can_use_insight_without_exposing_api_key(monkeypatch):
    from services import insight_service

    app = create_app(testing=True)
    app.config["INSIGHT_API_KEY"] = "test-insight-key"
    monkeypatch.setattr(insight_service, "generate_financial_insight", lambda **kwargs: "Browser insight")

    client = app.test_client()
    client.get("/workspace")
    response = client.post("/api/insight", json={"user_input": "How can I save more?"})

    assert response.status_code == 200
    assert response.get_json()["insight"] == "Browser insight"


def test_authenticated_workspace_links_back_to_dashboard(tmp_path):
    import os

    os.environ["FINANCE_DB_PATH"] = str(tmp_path / "finance_test.db")
    app = create_app(testing=True)
    client = app.test_client()

    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_name"] = "Demo User"

    workspace = client.get("/workspace")
    assert workspace.status_code == 200
    assert b"Dashboard" in workspace.data


def test_unexpected_api_errors_are_generic(monkeypatch):
    from services import insight_service

    app = create_app(testing=True)
    monkeypatch.setattr(
        insight_service,
        "generate_financial_insight",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private provider failure")),
    )

    client = app.test_client()
    response = client.post("/api/insight", json={"user_input": "How can I save more?"})

    assert response.status_code == 500
    assert response.get_json()["error"] != "private provider failure"
