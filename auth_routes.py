from __future__ import annotations

import secrets
import sqlite3
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from extensions import limiter
from models import feature_is_enabled, get_db_connection, get_db_path, init_db
from services.auth_email_service import send_auth_email, send_email

bp = Blueprint("auth", __name__)


def _auth_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key)


def _auth_link(action: str, email: str) -> str:
    token = _auth_serializer().dumps({"action": action, "email": email})
    return url_for("auth." + action, token=token, _external=True)


def _is_admin(user) -> bool:
    return bool(user and (user["role"] == "admin" or (
        current_app.config["ADMIN_EMAIL"] and user["email"].lower() == current_app.config["ADMIN_EMAIL"]
    )))


def _admin_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_db_connection() as conn:
        return conn.execute("SELECT id, email, role FROM users WHERE id = ?", (user_id,)).fetchone()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _admin_user()
        if not user:
            return redirect(url_for("auth.login"))
        if not _is_admin(user):
            return render_template("404.html"), 404
        return view(*args, **kwargs)
    return wrapped


def _audit(conn, action: str, target_type: str, target_id: object = "", detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail) VALUES (?, ?, ?, ?, ?)",
        (session.get("user_id"), action, target_type, str(target_id), detail[:500]),
    )


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if not feature_is_enabled("new_registration"):
            flash("New registrations are temporarily unavailable.", "error")
            return render_template("register.html")
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        language = session.get("visitor_language", "en")
        language = language if language in {"en", "ar"} else "en"

        if not name or not email or not password:
            flash("Please complete all fields.", "error")
            return render_template("register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("register.html")

        with get_db_connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                flash("Email already registered.", "error")
                return render_template("register.html")

            conn.execute(
                "INSERT INTO users (name, email, password_hash, email_verified, preferred_language) VALUES (?, ?, ?, 0, ?)",
                (name, email, generate_password_hash(password), language),
            )
            conn.commit()

        send_auth_email(email, "Verify your Finance SaaS email", _auth_link("verify_email", email))
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        with get_db_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            if user["account_status"] != "active":
                flash("This account is currently suspended. Contact support for help.", "error")
                return render_template("login.html")
            if current_app.config["REQUIRE_EMAIL_VERIFICATION"] and not user["email_verified"]:
                flash("Please verify your email before logging in.", "error")
                return render_template("login.html")
            if user["two_factor_enabled"]:
                code = f"{secrets.randbelow(1_000_000):06d}"
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE users SET two_factor_code_hash = ?, two_factor_expires_at = ? WHERE id = ?",
                        (generate_password_hash(code), (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), user["id"]),
                    )
                send_email(user["email"], "Your ClearSpend security code", f"Your verification code is {code}. It expires in 10 minutes.")
                session["pending_2fa_user_id"] = user["id"]
                flash("We sent a security code to your email.", "success")
                return redirect(url_for("auth.verify_two_factor"))
            session.permanent = request.form.get("remember_me") == "on"
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["preferred_language"] = user["preferred_language"] or "en"
            session["theme_preference"] = user["theme_preference"] or "light"
            with get_db_connection() as conn:
                conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), user["id"]))
            flash("Welcome back!", "success")
            if current_app.config["ADMIN_EMAIL"] and user["email"].lower() == current_app.config["ADMIN_EMAIL"]:
                return redirect(url_for("auth.admin"))
            return redirect(url_for("dashboard.dashboard_home"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@bp.route("/two-factor", methods=["GET", "POST"])
@limiter.limit("5 per 10 minutes", methods=["POST"])
def verify_two_factor():
    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        with get_db_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        expiry = user["two_factor_expires_at"] if user else None
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry)
        if isinstance(expiry, datetime) and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expired = not user or not isinstance(expiry, datetime) or expiry < datetime.now(timezone.utc)
        if expired or not check_password_hash(user["two_factor_code_hash"] or "", code):
            flash("That security code is invalid or expired.", "error")
            return render_template("two_factor.html")
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET two_factor_code_hash = NULL, two_factor_expires_at = NULL WHERE id = ?", (user_id,))
        session.pop("pending_2fa_user_id", None)
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["preferred_language"] = user["preferred_language"] or "en"
        session["theme_preference"] = user["theme_preference"] or "light"
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET two_factor_code_hash = NULL, two_factor_expires_at = NULL, last_login_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), user_id))
        return redirect(url_for("auth.admin") if _is_admin(user) else url_for("dashboard.dashboard_home"))
    return render_template("two_factor.html")


@bp.route("/verify-email/<token>")
def verify_email(token):
    try:
        payload = _auth_serializer().loads(token, max_age=86400)
    except (BadSignature, SignatureExpired):
        flash("This verification link is invalid or expired.", "error")
        return redirect(url_for("auth.login"))
    if payload.get("action") != "verify_email":
        flash("This verification link is invalid.", "error")
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET email_verified = 1 WHERE email = ?", (payload["email"],))
        conn.commit()
    flash("Email verified successfully.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        with get_db_connection() as conn:
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            send_auth_email(email, "Reset your Finance SaaS password", _auth_link("reset_password", email))
        flash("If that email exists, a password reset link has been sent.", "success")
        return redirect(url_for("auth.login"))
    return render_template("forgot_password.html")


@bp.route("/resend-verification", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification():
    email = (request.form.get("email") or "").strip().lower()
    with get_db_connection() as conn:
        user = conn.execute("SELECT email_verified FROM users WHERE email = ?", (email,)).fetchone()
    if user and not user["email_verified"]:
        send_auth_email(email, "Verify your Finance SaaS email", _auth_link("verify_email", email))
    flash("If that account needs verification, a new link has been sent.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        payload = _auth_serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("This password reset link is invalid or expired.", "error")
        return redirect(url_for("auth.login"))
    if payload.get("action") != "reset_password":
        flash("This password reset link is invalid.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        password = request.form.get("password") or ""
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("reset_password.html", token=token)
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (generate_password_hash(password), payload["email"]))
            conn.commit()
        flash("Password reset successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("reset_password.html", token=token)


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        language = (request.form.get("language") or "en").lower()
        theme = (request.form.get("theme") or "light").lower()
        if not name or language not in {"en", "ar"} or theme not in {"light", "dark"}:
            flash("Please provide a valid name, language, and theme.", "error")
            return redirect(url_for("auth.settings"))
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET name = ?, preferred_language = ?, theme_preference = ? WHERE id = ?",
                (name, language, theme, user_id),
            )
        session["user_name"] = name
        session["preferred_language"] = language
        session["theme_preference"] = theme
        flash("Your profile and preferences were saved.", "success")
        return redirect(url_for("auth.settings"))

    with get_db_connection() as conn:
        user = conn.execute(
            "SELECT name, email, base_currency, preferred_language, theme_preference, two_factor_enabled, avatar_filename FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return render_template("settings.html", user=user)


@bp.route("/settings/avatar", methods=["POST"])
def upload_avatar():
    user_id = session.get("user_id")
    if current_app.config.get("VERCEL"):
        flash("Profile photo uploads need cloud storage before they can be used on Vercel.", "error")
        return redirect(url_for("auth.settings"))
    image = request.files.get("avatar")
    if not user_id or not image or not image.filename:
        flash("Choose an image to upload.", "error")
        return redirect(url_for("auth.settings"))
    extension = Path(secure_filename(image.filename)).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        flash("Use a JPG, PNG, or WebP image.", "error")
        return redirect(url_for("auth.settings"))
    filename = f"user-{user_id}{extension}"
    destination = Path(current_app.static_folder) / "uploads"
    destination.mkdir(exist_ok=True)
    image.save(destination / filename)
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET avatar_filename = ? WHERE id = ?", (filename, user_id))
    flash("Profile photo updated.", "success")
    return redirect(url_for("auth.settings"))


@bp.route("/admin")
@admin_required
def admin():
    with get_db_connection() as conn:
        for key, description in (
            ("maintenance_mode", "Temporarily show a maintenance notice to customers."),
            ("new_registration", "Allow new customer registrations."),
            ("ai_advisor", "Enable the AI Advisor workspace."),
        ):
            if not conn.execute("SELECT key FROM feature_flags WHERE key = ?", (key,)).fetchone():
                conn.execute("INSERT INTO feature_flags (key, enabled, description) VALUES (?, ?, ?)", (key, int(key != "maintenance_mode"), description))
        metrics = {
            "users": conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"],
            "transactions": conn.execute("SELECT COUNT(*) AS total FROM transactions").fetchone()["total"],
            "notifications": conn.execute("SELECT COUNT(*) AS total FROM notifications WHERE read = 0").fetchone()["total"],
            "tickets": conn.execute("SELECT COUNT(*) AS total FROM support_tickets WHERE status != 'closed'").fetchone()["total"],
        }
        users = conn.execute("SELECT id, name, email, email_verified, role, account_status, created_at, last_login_at FROM users ORDER BY created_at DESC LIMIT 50").fetchall()
        recent_transactions = conn.execute("SELECT description, amount, type, category, created_at FROM transactions ORDER BY created_at DESC LIMIT 10").fetchall()
        flags = conn.execute("SELECT key, enabled, description FROM feature_flags ORDER BY key").fetchall()
        tickets = conn.execute("SELECT t.id, t.subject, t.status, t.priority, t.created_at, u.name, u.email FROM support_tickets t JOIN users u ON u.id = t.user_id ORDER BY t.updated_at DESC LIMIT 10").fetchall()
        audits = conn.execute("SELECT a.action, a.target_type, a.target_id, a.detail, a.created_at, COALESCE(u.name, 'System') AS actor FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_id ORDER BY a.created_at DESC LIMIT 12").fetchall()
        announcements = conn.execute("SELECT id, title, audience, active, created_at FROM announcements ORDER BY created_at DESC LIMIT 8").fetchall()
    health = {
        "database": "Connected",
        "email": "Suppressed" if current_app.config["MAIL_SUPPRESS_SEND"] else ("Configured" if current_app.config["MAIL_SERVER"] else "Missing configuration"),
        "error_tracking": "Configured" if current_app.config["SENTRY_DSN"] else "Not configured",
        "backups": "SQLite ready" if get_db_path().exists() else "Database file unavailable",
    }
    return render_template("admin.html", metrics=metrics, users=users, recent_transactions=recent_transactions, flags=flags, tickets=tickets, audits=audits, announcements=announcements, health=health)


@bp.route("/admin/users/<int:user_id>", methods=["POST"])
@admin_required
def update_admin_user(user_id):
    status = request.form.get("account_status", "active")
    role = request.form.get("role", "user")
    if status not in {"active", "suspended"} or role not in {"user", "support", "admin"}:
        flash("Invalid account update.", "error")
        return redirect(url_for("auth.admin"))
    if user_id == session["user_id"] and (status != "active" or role != "admin"):
        flash("You cannot remove your own admin access from this screen.", "error")
        return redirect(url_for("auth.admin"))
    with get_db_connection() as conn:
        target = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            return render_template("404.html"), 404
        conn.execute("UPDATE users SET account_status = ?, role = ? WHERE id = ?", (status, role, user_id))
        _audit(conn, "user.updated", "user", user_id, f"role={role}; status={status}")
    flash("User access was updated.", "success")
    return redirect(url_for("auth.admin") + "#users")


@bp.route("/admin/flags/<flag_key>", methods=["POST"])
@admin_required
def update_feature_flag(flag_key):
    enabled = int(request.form.get("enabled") == "1")
    with get_db_connection() as conn:
        flag = conn.execute("SELECT key FROM feature_flags WHERE key = ?", (flag_key,)).fetchone()
        if not flag:
            return render_template("404.html"), 404
        conn.execute("UPDATE feature_flags SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?", (enabled, flag_key))
        _audit(conn, "feature_flag.updated", "feature_flag", flag_key, f"enabled={enabled}")
    flash("Feature flag updated.", "success")
    return redirect(url_for("auth.admin") + "#features")


@bp.route("/admin/tickets/<int:ticket_id>", methods=["POST"])
@admin_required
def update_ticket(ticket_id):
    status = request.form.get("status", "open")
    priority = request.form.get("priority", "normal")
    if status not in {"open", "in_progress", "closed"} or priority not in {"low", "normal", "high"}:
        flash("Invalid ticket update.", "error")
        return redirect(url_for("auth.admin"))
    with get_db_connection() as conn:
        ticket = conn.execute("SELECT id FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not ticket:
            return render_template("404.html"), 404
        conn.execute("UPDATE support_tickets SET status = ?, priority = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, priority, ticket_id))
        _audit(conn, "ticket.updated", "support_ticket", ticket_id, f"status={status}; priority={priority}")
    flash("Ticket updated.", "success")
    return redirect(url_for("auth.admin") + "#tickets")


@bp.route("/admin/announcements", methods=["POST"])
@admin_required
def create_announcement():
    title = (request.form.get("title") or "").strip()
    message = (request.form.get("message") or "").strip()
    audience = request.form.get("audience", "all")
    if not title or not message or audience not in {"all", "english", "arabic"}:
        flash("Enter an announcement title, message, and audience.", "error")
        return redirect(url_for("auth.admin"))
    with get_db_connection() as conn:
        conn.execute("INSERT INTO announcements (title, message, audience) VALUES (?, ?, ?)", (title[:120], message[:1000], audience))
        _audit(conn, "announcement.created", "announcement", "", title)
    flash("Announcement published.", "success")
    return redirect(url_for("auth.admin") + "#announcements")


@bp.route("/admin/backups", methods=["POST"])
@admin_required
def create_backup():
    if current_app.config["DATABASE_URL"]:
        flash("Use the managed database backup provider for PostgreSQL backups.", "error")
        return redirect(url_for("auth.admin") + "#health")
    backup_dir = Path(current_app.root_path) / "backups"
    backup_dir.mkdir(exist_ok=True)
    filename = f"finance-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.db"
    destination = backup_dir / filename
    source = sqlite3.connect(str(get_db_path()))
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO backup_runs (filename, status) VALUES (?, ?)", (filename, "completed"))
        _audit(conn, "backup.created", "backup", filename, "SQLite database backup")
    flash("A local database backup was created.", "success")
    return redirect(url_for("auth.admin") + "#health")


@bp.route("/support", methods=["GET", "POST"])
def support():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()
        if not subject or not message:
            flash("Enter a subject and message.", "error")
        else:
            with get_db_connection() as conn:
                conn.execute("INSERT INTO support_tickets (user_id, subject, message) VALUES (?, ?, ?)", (user_id, subject[:160], message[:2000]))
            flash("Your support ticket was sent.", "success")
        return redirect(url_for("auth.support"))
    with get_db_connection() as conn:
        tickets = conn.execute("SELECT id, subject, status, priority, created_at FROM support_tickets WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
    return render_template("support.html", tickets=tickets)


@bp.route("/settings/password", methods=["POST"])
@limiter.limit("5 per hour")
def change_password():
    user_id = session.get("user_id")
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    if not user_id or len(new_password) < 8:
        flash("Use a new password with at least 8 characters.", "error")
        return redirect(url_for("auth.settings"))
    with get_db_connection() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], current_password):
            flash("Your current password is incorrect.", "error")
            return redirect(url_for("auth.settings"))
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_password), user_id))
    flash("Password updated successfully.", "success")
    return redirect(url_for("auth.settings"))


@bp.route("/settings/two-factor", methods=["POST"])
def update_two_factor():
    user_id = session.get("user_id")
    password = request.form.get("current_password") or ""
    enabled = request.form.get("enabled") == "on"
    with get_db_connection() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Your current password is incorrect.", "error")
            return redirect(url_for("auth.settings"))
        conn.execute("UPDATE users SET two_factor_enabled = ? WHERE id = ?", (int(enabled), user_id))
    flash("Two-factor authentication was updated.", "success")
    return redirect(url_for("auth.settings"))


@bp.route("/settings/email", methods=["POST"])
@limiter.limit("3 per hour")
def request_email_change():
    user_id = session.get("user_id")
    new_email = (request.form.get("new_email") or "").strip().lower()
    password = request.form.get("current_password") or ""
    if not user_id or not new_email:
        flash("Enter a valid new email address.", "error")
        return redirect(url_for("auth.settings"))
    with get_db_connection() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (new_email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Your current password is incorrect.", "error")
        return redirect(url_for("auth.settings"))
    if existing:
        flash("That email is already in use.", "error")
        return redirect(url_for("auth.settings"))
    token = _auth_serializer().dumps({"action": "verify_new_email", "user_id": user_id, "email": new_email})
    send_auth_email(new_email, "Confirm your new ClearSpend email", url_for("auth.verify_new_email", token=token, _external=True))
    flash("Check your new email address to confirm the change.", "success")
    return redirect(url_for("auth.settings"))


@bp.route("/verify-new-email/<token>")
def verify_new_email(token):
    try:
        payload = _auth_serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("This email-change link is invalid or expired.", "error")
        return redirect(url_for("auth.login"))
    if payload.get("action") != "verify_new_email":
        flash("This email-change link is invalid.", "error")
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (payload["email"],)).fetchone()
        if existing:
            flash("That email is already in use.", "error")
            return redirect(url_for("auth.login"))
        conn.execute("UPDATE users SET email = ?, email_verified = 1 WHERE id = ?", (payload["email"], payload["user_id"]))
    flash("Your email address was updated.", "success")
    return redirect(url_for("auth.settings"))


@bp.route("/account/delete", methods=["POST"])
def delete_account():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    password = request.form.get("delete_password") or ""
    with get_db_connection() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Enter your current password to delete your account.", "error")
            return redirect(url_for("auth.settings"))
        for table in ("subscriptions", "transactions", "budgets", "savings_goals", "recurring_transactions", "notifications"):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()

    session.clear()
    flash("Your account and financial data have been deleted.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@bp.route("/terms")
def terms():
    return render_template("terms.html")
