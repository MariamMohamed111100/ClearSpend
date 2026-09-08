import os

from app_factory import create_app
from models import get_db_connection


def test_register_user_and_create_budget(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()

    register = client.post(
        "/register",
        data={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "secret123",
        },
        follow_redirects=True,
    )

    assert register.status_code == 200

    login = client.post(
        "/login",
        data={
            "email": "alice@example.com",
            "password": "secret123",
        },
        follow_redirects=True,
    )

    assert login.status_code == 200

    budget = client.post(
        "/budget",
        data={
            "category": "Food & Dining",
            "limit": "900",
            "spent": "650",
        },
        follow_redirects=True,
    )

    assert budget.status_code == 200
    assert b"Food" in budget.data
    assert b"Dining" in budget.data


def test_user_can_track_transactions_and_upgrade_to_premium(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()

    client.post(
        "/register",
        data={
            "name": "Bob",
            "email": "bob@example.com",
            "password": "secret123",
        },
        follow_redirects=True,
    )
    client.post(
        "/login",
        data={
            "email": "bob@example.com",
            "password": "secret123",
        },
        follow_redirects=True,
    )

    transaction = client.post(
        "/transactions",
        data={
            "description": "Groceries",
            "amount": "120",
            "type": "expense",
            "category": "Food & Dining",
        },
        follow_redirects=True,
    )

    assert transaction.status_code == 200
    assert b"Groceries" in transaction.data

    premium = client.post(
        "/pricing/upgrade",
        data={"plan": "premium"},
        follow_redirects=True,
    )

    assert premium.status_code == 200
    assert b"Premium" in premium.data or b"premium" in premium.data


def test_analytics_summarizes_spending_and_premium_insight_requires_plan(tmp_path, monkeypatch):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()

    client.post(
        "/register",
        data={"name": "Cara", "email": "cara@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/login",
        data={"email": "cara@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/transactions",
        data={"description": "Rent", "amount": "1000", "type": "expense", "category": "Housing"},
        follow_redirects=True,
    )
    client.post(
        "/transactions",
        data={"description": "Salary", "amount": "3000", "type": "income", "category": "Income"},
        follow_redirects=True,
    )

    analytics = client.get("/analytics")
    assert analytics.status_code == 200
    assert b"$1,000.00" in analytics.data
    assert b"Housing" in analytics.data

    blocked = client.post("/api/premium-insight", json={"question": "How can I save more?"})
    assert blocked.status_code == 403

    client.post("/pricing/upgrade", data={"plan": "premium"}, follow_redirects=True)

    monkeypatch.setattr(
        "services.insight_service.generate_financial_insight",
        lambda **kwargs: "Prioritize housing and keep a three-month emergency buffer.",
    )
    premium = client.post("/api/premium-insight", json={"question": "How can I save more?"})
    assert premium.status_code == 200
    assert premium.get_json()["insight"].startswith("Prioritize housing")


def test_local_billing_fallback_and_unconfigured_webhook(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()
    client.post(
        "/register",
        data={"name": "Dana", "email": "dana@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/login",
        data={"email": "dana@example.com", "password": "secret123"},
        follow_redirects=True,
    )

    checkout = client.post("/billing/checkout", follow_redirects=False)
    assert checkout.status_code == 302
    assert checkout.headers["Location"].endswith("/dashboard")

    with get_db_connection() as conn:
        subscription = conn.execute(
            "SELECT plan, status FROM subscriptions WHERE user_id = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert dict(subscription) == {"plan": "premium", "status": "active"}

    webhook = client.post("/billing/webhook", data=b"{}")
    assert webhook.status_code == 503


def test_invalid_financial_values_are_rejected_without_database_rows(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()
    client.post(
        "/register",
        data={"name": "Eli", "email": "eli@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/login",
        data={"email": "eli@example.com", "password": "secret123"},
        follow_redirects=True,
    )

    invalid_transaction = client.post(
        "/transactions",
        data={"description": "Bad entry", "amount": "-20", "type": "refund", "category": "Other"},
        follow_redirects=True,
    )
    assert invalid_transaction.status_code == 200
    assert b"Bad entry" not in invalid_transaction.data

    with get_db_connection() as conn:
        transaction_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert transaction_count == 0


def test_browser_forms_require_csrf_outside_testing(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    app.config["TESTING"] = False
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()

    response = client.post(
        "/register",
        data={"name": "No Token", "email": "csrf@example.com", "password": "secret123"},
    )

    assert response.status_code == 400


def test_webhook_event_store_is_initialized(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    create_app(testing=True)

    with get_db_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(webhook_events)").fetchall()
        }

    assert {"event_id", "event_type", "received_at"}.issubset(columns)


def test_invalid_budget_values_are_rejected_without_database_rows(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()
    client.post(
        "/register",
        data={"name": "Faye", "email": "faye@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/login",
        data={"email": "faye@example.com", "password": "secret123"},
        follow_redirects=True,
    )

    invalid_budget = client.post(
        "/budget",
        data={"category": "Housing", "limit": "-500", "spent": "100"},
        follow_redirects=True,
    )
    assert invalid_budget.status_code == 200

    with get_db_connection() as conn:
        budget_count = conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0]
    assert budget_count == 0


def test_user_can_delete_account_and_financial_data(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()
    client.post(
        "/register",
        data={"name": "Gina", "email": "gina@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/login",
        data={"email": "gina@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    client.post(
        "/transactions",
        data={"description": "Coffee", "amount": "5", "type": "expense", "category": "Food"},
        follow_redirects=True,
    )

    rejected = client.post("/account/delete", data={"delete_password": "wrong-password"}, follow_redirects=True)
    assert rejected.status_code == 200
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1

    deleted = client.post("/account/delete", data={"delete_password": "secret123"}, follow_redirects=True)

    assert deleted.status_code == 200
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_email_verification_and_password_reset_flow(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True
    client = app.test_client()

    client.post(
        "/register",
        data={"name": "Hana", "email": "hana@example.com", "password": "secret123"},
        follow_redirects=True,
    )

    with app.test_request_context():
        from auth_routes import _auth_link

        verification_link = _auth_link("verify_email", "hana@example.com")
        reset_link = _auth_link("reset_password", "hana@example.com")

    blocked_login = client.post(
        "/login",
        data={"email": "hana@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    assert blocked_login.status_code == 200
    with client.session_transaction() as session:
        assert "user_id" not in session

    verified = client.get(verification_link, follow_redirects=True)
    assert verified.status_code == 200

    client.post(
        "/reset-password/invalid",
        data={"password": "newsecret123"},
        follow_redirects=True,
    )
    reset = client.post(
        reset_link,
        data={"password": "newsecret123"},
        follow_redirects=True,
    )
    assert reset.status_code == 200
    logged_in = client.post(
        "/login",
        data={"email": "hana@example.com", "password": "newsecret123"},
        follow_redirects=False,
    )
    assert logged_in.status_code == 302
    assert logged_in.headers["Location"].endswith("/dashboard")


def test_public_policy_and_error_pages_render(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    client = app.test_client()

    assert client.get("/privacy").status_code == 200
    assert b"Your data" in client.get("/privacy").data
    assert client.get("/terms").status_code == 200
    assert b"Terms of Service" in client.get("/terms").data
    assert client.get("/missing-page").status_code == 404
    assert client.get("/api/missing").get_json() == {"error": "Resource not found."}


def test_dashboard_exposes_premium_navigation_for_free_users(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)
    app = create_app(testing=True)
    client = app.test_client()
    client.post("/register", data={"name": "Ivy", "email": "ivy@example.com", "password": "secret123"})
    client.post("/login", data={"email": "ivy@example.com", "password": "secret123"})

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert b"> Premium<" in dashboard.data
    assert b"Meet your Premium AI advisor" in dashboard.data


def test_stripe_live_mode_is_blocked_by_default(tmp_path):
    db_path = tmp_path / "finance_test.db"
    os.environ["FINANCE_DB_PATH"] = str(db_path)

    app = create_app(testing=True)
    app.config["STRIPE_SECRET_KEY"] = "sk_live_blocked"
    app.config["ALLOW_STRIPE_LIVE"] = False

    with app.app_context():
        from billing_routes import _stripe_client

        try:
            _stripe_client()
        except RuntimeError as exc:
            assert "live mode is disabled" in str(exc)
        else:
            raise AssertionError("Live Stripe mode should be blocked by default")
