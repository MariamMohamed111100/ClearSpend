from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from extensions import csrf, limiter
from models import feature_is_enabled, get_db_connection
from services import insight_service

insight_bp = Blueprint("insight_bp", __name__)

csrf.exempt(insight_bp)


def _api_key_is_valid() -> bool:
    configured_key = current_app.config["INSIGHT_API_KEY"]
    return (
        not configured_key
        or request.headers.get("X-API-Key") == configured_key
        or session.get("browser_api_access") is True
    )


@insight_bp.route("/", methods=["GET"])
def index():
    return render_template("landing.html", visitor_language=session.get("visitor_language", "en"))


@insight_bp.route("/language/<language>")
def choose_language(language: str):
    """Remember an application language before a visitor creates an account."""
    if language in {"en", "ar"}:
        session["visitor_language"] = language
    return redirect(url_for("insight_bp.index"))


@insight_bp.route("/workspace", methods=["GET"])
def workspace():
    if not feature_is_enabled("ai_advisor"):
        flash("The AI Advisor is temporarily unavailable.", "error")
        return redirect(url_for("dashboard.dashboard_home") if session.get("user_id") else url_for("insight_bp.index"))
    session["browser_api_access"] = True
    currency = "USD"
    if session.get("user_id"):
        with get_db_connection() as conn:
            user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            currency = user["base_currency"] if user else currency
    return render_template("workspace.html", currency=currency)


@insight_bp.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})


@insight_bp.route("/api/insight", methods=["POST"])
@limiter.limit(lambda: current_app.config["API_INSIGHT_RATE_LIMIT"])
def generate_insight():
    if not feature_is_enabled("ai_advisor"):
        return jsonify({"error": "The AI Advisor is temporarily unavailable."}), 503
    if not _api_key_is_valid():
        return jsonify({"error": "Valid X-API-Key header required."}), 401

    payload = request.get_json(silent=True) or {}
    user_input = payload.get("user_input", "")

    if not user_input or not str(user_input).strip():
        return jsonify({"error": "user_input is required."}), 400

    try:
        insight = insight_service.generate_financial_insight(
            user_input=user_input,
            monthly_income=payload.get("monthly_income"),
            categories=payload.get("categories", {}),
            recent_transactions=payload.get("recent_transactions", []),
        )
    except RuntimeError as exc:
        current_app.logger.warning("Insight provider failure: %s", exc)
        return jsonify({"error": "Unable to generate an insight right now."}), 500
    except Exception as exc:
        current_app.logger.exception("Unexpected insight provider failure")
        return jsonify({"error": "Unable to generate an insight right now."}), 500

    return jsonify({"insight": insight, "status": "success"})


@insight_bp.route("/api/premium-insight", methods=["POST"])
@limiter.limit(lambda: current_app.config["API_PREMIUM_INSIGHT_RATE_LIMIT"])
def generate_premium_insight():
    if "user_id" not in session:
        return jsonify({"error": "Authentication required."}), 401

    with get_db_connection() as conn:
        subscription = conn.execute(
            "SELECT plan FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (session["user_id"],),
        ).fetchone()
        transactions = conn.execute(
            "SELECT description, amount, type, category FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (session["user_id"],),
        ).fetchall()

    if not subscription or subscription["plan"] != "premium":
        return jsonify({"error": "Premium plan required."}), 403

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "Review my recent finances and suggest my highest-impact next step.")).strip()
    if not question:
        return jsonify({"error": "question is required."}), 400

    categories = {}
    for transaction in transactions:
        if transaction["type"] == "expense":
            categories[transaction["category"]] = categories.get(transaction["category"], 0) + transaction["amount"]

    try:
        insight = insight_service.generate_financial_insight(
            user_input=question,
            monthly_income=sum(row["amount"] for row in transactions if row["type"] == "income"),
            categories=categories,
            recent_transactions=[dict(row) for row in transactions],
        )
    except RuntimeError as exc:
        current_app.logger.warning("Premium insight provider failure: %s", exc)
        return jsonify({"error": "Unable to generate an insight right now."}), 500
    except Exception as exc:
        current_app.logger.exception("Unexpected premium insight provider failure")
        return jsonify({"error": "Unable to generate an insight right now."}), 500

    return jsonify({"insight": insight, "status": "success"})


@insight_bp.route("/api/premium-forecast", methods=["POST"])
@limiter.limit(lambda: current_app.config["API_PREMIUM_INSIGHT_RATE_LIMIT"])
def premium_forecast():
    if "user_id" not in session:
        return jsonify({"error": "Authentication required."}), 401
    with get_db_connection() as conn:
        subscription = conn.execute("SELECT plan FROM subscriptions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1", (session["user_id"],)).fetchone()
        transactions = conn.execute("SELECT description, amount, type, category FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 60", (session["user_id"],)).fetchall()
    if not subscription or subscription["plan"] != "premium":
        return jsonify({"error": "Premium plan required."}), 403
    try:
        insight = insight_service.generate_financial_insight(
            user_input="Create a cautious next-month cashflow forecast from this user's recent activity. Mention likely pressure points and one action to improve the forecast.",
            monthly_income=sum(row["amount"] for row in transactions if row["type"] == "income"),
            categories={},
            recent_transactions=[dict(row) for row in transactions],
        )
    except Exception:
        current_app.logger.exception("Premium forecast failed")
        return jsonify({"error": "Unable to generate a forecast right now."}), 500
    return jsonify({"forecast": insight, "status": "success"})
