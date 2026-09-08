from __future__ import annotations

from flask import Blueprint, current_app, jsonify, redirect, request, session, url_for

from extensions import csrf
from models import get_db_connection

bp = Blueprint("billing", __name__)

csrf.exempt(bp)


def _stripe_client():
    secret_key = current_app.config["STRIPE_SECRET_KEY"]
    if not secret_key:
        return None
    if secret_key.startswith("sk_live_") and not current_app.config["ALLOW_STRIPE_LIVE"]:
        raise RuntimeError("Stripe live mode is disabled. Use a test key or explicitly enable live mode.")
    try:
        import stripe
    except ImportError as exc:
        raise RuntimeError("Stripe is not installed. Run pip install -r requirements.txt.") from exc
    stripe.api_key = secret_key
    return stripe


@bp.route("/billing/checkout", methods=["POST"])
def create_checkout():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    stripe = _stripe_client()
    if stripe is None:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO subscriptions (user_id, plan, status) VALUES (?, 'premium', 'active')",
                (session["user_id"],),
            )
            conn.commit()
        return redirect(url_for("dashboard.dashboard_home"))

    price_id = current_app.config["STRIPE_PREMIUM_PRICE_ID"]
    if not price_id:
        return jsonify({"error": "STRIPE_PREMIUM_PRICE_ID is not configured."}), 500

    checkout = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{current_app.config['APP_BASE_URL']}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{current_app.config['APP_BASE_URL']}/pricing/upgrade",
        client_reference_id=str(session["user_id"]),
        metadata={"user_id": str(session["user_id"]), "plan": "premium"},
    )
    return redirect(checkout.url, code=303)


@bp.route("/billing/success")
def billing_success():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    return redirect(url_for("dashboard.dashboard_home"))


@bp.route("/billing/webhook", methods=["POST"])
def billing_webhook():
    stripe = _stripe_client()
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")

    if stripe is None or not current_app.config["STRIPE_WEBHOOK_SECRET"]:
        return jsonify({"error": "Stripe webhook is not configured."}), 503

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            current_app.config["STRIPE_WEBHOOK_SECRET"],
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({"error": "Invalid webhook signature."}), 400

    event_type = event["type"]
    event_object = event["data"]["object"]
    event_id = event.get("id")
    if not event_id:
        return jsonify({"error": "Webhook event ID is required."}), 400

    with get_db_connection() as conn:
        inserted = conn.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, event_type) VALUES (?, ?)",
            (event_id, event_type),
        ).rowcount
        conn.commit()

    if inserted == 0:
        return jsonify({"received": True, "duplicate": True})

    if event_type == "checkout.session.completed":
        user_id = event_object.get("client_reference_id") or event_object.get("metadata", {}).get("user_id")
        if user_id:
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO subscriptions (user_id, plan, status, stripe_customer_id, stripe_subscription_id) VALUES (?, 'premium', 'active', ?, ?)",
                    (int(user_id), event_object.get("customer"), event_object.get("subscription")),
                )
                conn.commit()
    elif event_type in {"customer.subscription.deleted", "customer.subscription.paused"}:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE subscriptions SET status = 'inactive' WHERE stripe_subscription_id = ?",
                (event_object.get("id"),),
            )
            conn.commit()
    elif event_type == "customer.subscription.updated":
        status = "active" if event_object.get("status") in {"active", "trialing"} else "inactive"
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE subscriptions SET status = ? WHERE stripe_subscription_id = ?",
                (status, event_object.get("id")),
            )
            conn.commit()

    return jsonify({"received": True})