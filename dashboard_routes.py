from __future__ import annotations

import csv
import io
import json
import math
from datetime import date

from flask import Blueprint, Response, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from models import get_db_connection
from services.auth_email_service import send_email
from services.finance_service import SUPPORTED_CURRENCIES, convert_amount, monthly_history, notify, process_due_recurring

bp = Blueprint("dashboard", __name__)


def _forecast(history, plan: str):
    """A transparent baseline forecast: recent three-month average, not AI theatre."""
    if plan != "premium":
        return None
    recent = history[-3:]
    if not recent:
        return {"expenses": 0, "income": 0, "net": 0, "confidence": "Need more activity"}
    expenses = sum(item["expense"] for item in recent) / len(recent)
    income = sum(item["income"] for item in recent) / len(recent)
    data_months = sum(1 for item in recent if item["income"] or item["expense"])
    return {"expenses": round(expenses, 2), "income": round(income, 2), "net": round(income - expenses, 2), "confidence": "High" if data_months == 3 else "Building"}


def _budget_event(conn, user_id: int, category: str, amount: float, tx_type: str) -> None:
    if tx_type != "expense":
        return
    budgets = conn.execute("SELECT * FROM budgets WHERE user_id = ? AND lower(category) = lower(?)", (user_id, category)).fetchall()
    for budget in budgets:
        spent = float(budget["spent_amount"] or 0) + amount
        limit = float(budget["limit_amount"] or 0)
        conn.execute("UPDATE budgets SET spent_amount = ? WHERE id = ?", (spent, budget["id"]))
        title = message = None
        if limit and spent >= limit:
            title, message = "Budget limit reached", f"{category} has reached its {limit:,.2f} budget."
        elif limit and spent >= limit * 0.8:
            title, message = "Budget check-in", f"{category} is at {spent / limit:.0%} of its budget."
        if title and message:
            already_alerted = conn.execute("SELECT id FROM notifications WHERE user_id = ? AND title = ? AND message = ?", (user_id, title, message)).fetchone()
            notify(conn, user_id, title, message)
            if not already_alerted:
                user = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
                if user:
                    send_email(user["email"], f"ClearSpend: {title}", message)


def _pdf_document(lines: list[str]) -> bytes:
    """Generate a compact standards-compliant PDF without a server dependency."""
    safe = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:100] for line in lines]
    commands = ["BT /F1 18 Tf 50 760 Td"]
    for index, line in enumerate(safe):
        if index:
            commands.append("0 -20 Td /F1 10 Tf")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", "replace")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output)); output.extend(f"{index} 0 obj\n".encode()); output.extend(obj); output.extend(b"\nendobj\n")
    xref = len(output); output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    output.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)


@bp.route("/dashboard")
def dashboard_home():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    with get_db_connection() as conn:
        account = conn.execute("SELECT email, role FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if account and (account["role"] == "admin" or (current_app.config["ADMIN_EMAIL"] and account["email"].lower() == current_app.config["ADMIN_EMAIL"])):
        return redirect(url_for("auth.admin"))

    with get_db_connection() as conn:
        process_due_recurring(conn, session["user_id"])
        budgets = conn.execute(
            "SELECT * FROM budgets WHERE user_id = ? ORDER BY created_at DESC",
            (session["user_id"],),
        ).fetchall()

        transactions = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (session["user_id"],),
        ).fetchall()

        subscription = conn.execute(
            "SELECT plan, status FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (session["user_id"],),
        ).fetchone()

        transaction_summary = conn.execute(
            "SELECT type, COALESCE(SUM(COALESCE(base_amount, amount)), 0) AS total, COUNT(*) AS count FROM transactions WHERE user_id = ? GROUP BY type",
            (session["user_id"],),
        ).fetchall()
        history_rows = conn.execute("SELECT type, amount, base_amount, created_at FROM transactions WHERE user_id = ?", (session["user_id"],)).fetchall()
        notifications = conn.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY read, created_at DESC LIMIT 8", (session["user_id"],)).fetchall()
        user = conn.execute("SELECT base_currency, email, avatar_filename FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    formatted_budgets = []
    for budget in budgets:
        limit = float(budget["limit_amount"] or 0)
        spent = float(budget["spent_amount"] or 0)
        percent = min((spent / limit) * 100, 100) if limit else 0
        formatted_budgets.append({
            "id": budget["id"],
            "category": budget["category"],
            "limit_amount": limit,
            "spent_amount": spent,
            "percent": percent,
        })

    summary = {row["type"]: {"total": float(row["total"] or 0), "count": row["count"]} for row in transaction_summary}
    total_income = summary.get("income", {}).get("total", 0)
    total_expenses = summary.get("expense", {}).get("total", 0)
    total_budget = sum(item["limit_amount"] for item in formatted_budgets)
    total_budget_spent = sum(item["spent_amount"] for item in formatted_budgets)

    return render_template(
        "dashboard.html",
        budgets=formatted_budgets,
        transactions=transactions,
        plan=(subscription["plan"] if subscription else "free"),
        user_name=session.get("user_name", "User"),
        total_income=total_income,
        total_expenses=total_expenses,
        net_cashflow=total_income - total_expenses,
        total_budget=total_budget,
        total_budget_spent=total_budget_spent,
        transaction_count=sum(item["count"] for item in summary.values()),
        currency=(user["base_currency"] if user else "USD"),
        currencies=sorted(SUPPORTED_CURRENCIES),
        notifications=notifications,
        unread_notifications=sum(not row["read"] for row in notifications),
        is_admin=bool(current_app.config["ADMIN_EMAIL"] and user and user["email"].lower() == current_app.config["ADMIN_EMAIL"]),
        avatar_filename=(user["avatar_filename"] if user else None),
        monthly_history=monthly_history(history_rows),
        forecast=_forecast(monthly_history(history_rows), plan=(subscription["plan"] if subscription else "free")),
    )


@bp.route("/analytics")
def analytics():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    with get_db_connection() as conn:
        process_due_recurring(conn, session["user_id"])
        transactions = conn.execute(
            "SELECT type, category, amount, base_amount, created_at FROM transactions WHERE user_id = ?",
            (session["user_id"],),
        ).fetchall()
        user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    total_income = sum(float(row["base_amount"] or row["amount"] or 0) for row in transactions if row["type"] == "income")
    total_expenses = sum(float(row["base_amount"] or row["amount"] or 0) for row in transactions if row["type"] == "expense")
    category_totals = {}
    for row in transactions:
        if row["type"] != "expense":
            continue
        category_totals[row["category"]] = category_totals.get(row["category"], 0) + float(row["base_amount"] or row["amount"] or 0)

    category_breakdown = [
        {"category": category, "amount": amount, "percent": (amount / total_expenses * 100) if total_expenses else 0}
        for category, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    return render_template(
        "analytics.html",
        total_income=total_income,
        total_expenses=total_expenses,
        net_cashflow=total_income - total_expenses,
        category_breakdown=category_breakdown,
        monthly_history=monthly_history(transactions),
        currency=(user["base_currency"] if user else "USD"),
    )


@bp.route("/budget", methods=["GET", "POST"])
def manage_budget():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        category = (request.form.get("category") or "").strip()
        limit_amount = request.form.get("limit")
        spent_amount = request.form.get("spent")

        if not category or not limit_amount:
            flash("Category and limit are required.", "error")
            return redirect(url_for("dashboard.manage_budget"))

        try:
            parsed_limit = float(limit_amount)
            parsed_spent = float(spent_amount or 0)
        except (TypeError, ValueError):
            flash("Budget amounts must be valid numbers.", "error")
            return redirect(url_for("dashboard.manage_budget"))

        if (
            not math.isfinite(parsed_limit)
            or not math.isfinite(parsed_spent)
            or parsed_limit <= 0
            or parsed_spent < 0
        ):
            flash("Budget limit must be greater than zero and spent cannot be negative.", "error")
            return redirect(url_for("dashboard.manage_budget"))

        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO budgets (user_id, category, limit_amount, spent_amount) VALUES (?, ?, ?, ?)",
                (session["user_id"], category, parsed_limit, parsed_spent),
            )
            conn.commit()

        flash("Budget saved successfully.", "success")
        return redirect(url_for("dashboard.dashboard_home"))

    with get_db_connection() as conn:
        user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("budget.html", currency=(user["base_currency"] if user else "USD"))


@bp.route("/transactions", methods=["GET", "POST"])
def manage_transactions():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        description = (request.form.get("description") or "").strip()
        amount = request.form.get("amount")
        tx_type = (request.form.get("type") or "expense").strip().lower()
        category = (request.form.get("category") or "General").strip()
        source_currency = (request.form.get("currency") or "USD").upper()

        if not description or not amount:
            flash("Description and amount are required.", "error")
            return redirect(url_for("dashboard.manage_transactions"))

        try:
            parsed_amount = float(amount)
        except (TypeError, ValueError):
            flash("Amount must be a valid number.", "error")
            return redirect(url_for("dashboard.manage_transactions"))

        if not math.isfinite(parsed_amount) or parsed_amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return redirect(url_for("dashboard.manage_transactions"))

        if tx_type not in {"expense", "income"}:
            flash("Transaction type must be income or expense.", "error")
            return redirect(url_for("dashboard.manage_transactions"))

        with get_db_connection() as conn:
            user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            target_currency = user["base_currency"] if user else "USD"
            try:
                base_amount, rate = convert_amount(parsed_amount, source_currency, target_currency)
            except (ValueError, RuntimeError) as exc:
                flash(str(exc), "error")
                return redirect(url_for("dashboard.manage_transactions"))
            conn.execute(
                "INSERT INTO transactions (user_id, description, amount, type, category, currency, base_amount, conversion_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session["user_id"], description, parsed_amount, tx_type, category, source_currency, base_amount, rate),
            )
            _budget_event(conn, session["user_id"], category, base_amount, tx_type)
            conn.commit()

        flash("Transaction saved successfully.", "success")
        return redirect(url_for("dashboard.dashboard_home"))

    with get_db_connection() as conn:
        process_due_recurring(conn, session["user_id"])
        search = (request.args.get("q") or "").strip()
        category = (request.args.get("category") or "").strip()
        tx_type = (request.args.get("type") or "").strip().lower()
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()
        min_amount = (request.args.get("min_amount") or "").strip()
        max_amount = (request.args.get("max_amount") or "").strip()
        page = max(int(request.args.get("page", 1) or 1), 1)
        clauses = ["user_id = ?"]
        parameters = [session["user_id"]]
        if search:
            clauses.append("(lower(description) LIKE ? OR lower(category) LIKE ?)")
            parameters.extend([f"%{search.lower()}%", f"%{search.lower()}%"])
        if category:
            clauses.append("lower(category) = ?")
            parameters.append(category.lower())
        if tx_type in {"income", "expense"}:
            clauses.append("type = ?")
            parameters.append(tx_type)
        if date_from:
            clauses.append("date(created_at) >= date(?)")
            parameters.append(date_from)
        if date_to:
            clauses.append("date(created_at) <= date(?)")
            parameters.append(date_to)
        for raw, operator in ((min_amount, ">="), (max_amount, "<=")):
            if raw:
                try:
                    clauses.append(f"amount {operator} ?")
                    parameters.append(float(raw))
                except ValueError:
                    flash("Amount filters must be valid numbers.", "error")
        where = " AND ".join(clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", parameters).fetchone()[0]
        transactions = conn.execute(
            f"SELECT * FROM transactions WHERE {where} ORDER BY created_at DESC LIMIT 20 OFFSET ?",
            [*parameters, (page - 1) * 20],
        ).fetchall()

        user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("transactions.html", transactions=transactions, currency=(user["base_currency"] if user else "USD"), currencies=sorted(SUPPORTED_CURRENCIES), filters={"q": search, "category": category, "type": tx_type, "date_from": date_from, "date_to": date_to, "min_amount": min_amount, "max_amount": max_amount}, page=page, has_next=total > page * 20)


@bp.route("/transactions/<int:transaction_id>/delete", methods=["POST"])
def delete_transaction(transaction_id: int):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (transaction_id, session["user_id"]))
    flash("Transaction deleted.", "success")
    return redirect(url_for("dashboard.manage_transactions"))


@bp.route("/transactions/<int:transaction_id>/edit", methods=["POST"])
def edit_transaction(transaction_id: int):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    description = (request.form.get("description") or "").strip()
    category = (request.form.get("category") or "General").strip()
    try:
        amount = float(request.form.get("amount"))
        if not description or amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Enter a valid transaction description and amount.", "error")
        return redirect(url_for("dashboard.manage_transactions"))
    with get_db_connection() as conn:
        conn.execute("UPDATE transactions SET description = ?, category = ?, amount = ? WHERE id = ? AND user_id = ?", (description, category, amount, transaction_id, session["user_id"]))
    flash("Transaction updated.", "success")
    return redirect(url_for("dashboard.manage_transactions"))


@bp.route("/budgets/<int:budget_id>/delete", methods=["POST"])
def delete_budget(budget_id: int):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        conn.execute("DELETE FROM budgets WHERE id = ? AND user_id = ?", (budget_id, session["user_id"]))
    flash("Budget deleted.", "success")
    return redirect(url_for("dashboard.dashboard_home"))


@bp.route("/budgets/<int:budget_id>/edit", methods=["POST"])
def edit_budget(budget_id: int):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    try:
        limit, spent = float(request.form.get("limit")), float(request.form.get("spent") or 0)
        if limit <= 0 or spent < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Budget amounts must be valid.", "error")
        return redirect(url_for("dashboard.dashboard_home"))
    period = request.form.get("period") if request.form.get("period") in {"weekly", "monthly"} else "monthly"
    with get_db_connection() as conn:
        conn.execute("UPDATE budgets SET category = ?, limit_amount = ?, spent_amount = ?, period = ? WHERE id = ? AND user_id = ?", ((request.form.get("category") or "General").strip(), limit, spent, period, budget_id, session["user_id"]))
    flash("Budget updated.", "success")
    return redirect(url_for("dashboard.dashboard_home"))


@bp.route("/goals/<int:goal_id>/delete", methods=["POST"])
def delete_goal(goal_id: int):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        conn.execute("DELETE FROM savings_goals WHERE id = ? AND user_id = ?", (goal_id, session["user_id"]))
    flash("Goal deleted.", "success")
    return redirect(url_for("dashboard.savings_goals"))


@bp.route("/goals/<int:goal_id>/edit", methods=["POST"])
def edit_goal(goal_id: int):
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    try:
        target, saved = float(request.form.get("target")), float(request.form.get("saved") or 0)
        if target <= 0 or saved < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Goal amounts must be valid.", "error")
        return redirect(url_for("dashboard.savings_goals"))
    with get_db_connection() as conn:
        conn.execute("UPDATE savings_goals SET name = ?, target_amount = ?, saved_amount = ?, deadline = ? WHERE id = ? AND user_id = ?", ((request.form.get("name") or "Goal").strip(), target, saved, request.form.get("deadline") or None, goal_id, session["user_id"]))
    flash("Goal updated.", "success")
    return redirect(url_for("dashboard.savings_goals"))


@bp.route("/pricing/upgrade", methods=["GET", "POST"])
def pricing_upgrade():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        return redirect(url_for("billing.create_checkout"), code=307)

    return render_template("pricing.html")


@bp.route("/goals", methods=["GET", "POST"])
def savings_goals():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        target = request.form.get("target")
        saved = request.form.get("saved") or 0
        if not name or not target:
            flash("Goal name and target are required.", "error")
            return redirect(url_for("dashboard.savings_goals"))
        try:
            target_amount = float(target)
            saved_amount = float(saved)
            if not math.isfinite(target_amount) or not math.isfinite(saved_amount) or target_amount <= 0 or saved_amount < 0:
                raise ValueError
        except (TypeError, ValueError):
            flash("Goal amounts must be valid positive numbers.", "error")
            return redirect(url_for("dashboard.savings_goals"))
        with get_db_connection() as conn:
            conn.execute("INSERT INTO savings_goals (user_id, name, target_amount, saved_amount, deadline) VALUES (?, ?, ?, ?, ?)", (session["user_id"], name, target_amount, saved_amount, request.form.get("deadline") or None))
            if saved_amount >= target_amount * 0.8:
                message = f"{name} is already {saved_amount / target_amount:.0%} funded."
                notify(conn, session["user_id"], "Savings goal check-in", message)
                user = conn.execute("SELECT email FROM users WHERE id = ?", (session["user_id"],)).fetchone()
                if user:
                    send_email(user["email"], "ClearSpend: Savings goal check-in", message)
            conn.commit()
        flash("Savings goal created.", "success")
        return redirect(url_for("dashboard.savings_goals"))
    with get_db_connection() as conn:
        goals = conn.execute("SELECT * FROM savings_goals WHERE user_id = ? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
        user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("goals.html", goals=goals, currency=(user["base_currency"] if user else "USD"))


@bp.route("/recurring", methods=["GET", "POST"])
def recurring_transactions():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        description = (request.form.get("description") or "").strip()
        category = (request.form.get("category") or "General").strip()
        frequency = (request.form.get("frequency") or "monthly").strip().lower()
        source_currency = (request.form.get("currency") or "USD").upper()
        tx_type = (request.form.get("type") or "expense").strip().lower()
        next_date = request.form.get("next_date") or ""
        try:
            amount = float(request.form.get("amount"))
            date.fromisoformat(next_date)
            if not description or amount <= 0 or frequency not in {"weekly", "monthly", "yearly"} or tx_type not in {"income", "expense"}:
                raise ValueError
        except (TypeError, ValueError):
            flash("Enter a valid recurring transaction.", "error")
            return redirect(url_for("dashboard.recurring_transactions"))
        with get_db_connection() as conn:
            user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            try:
                base_amount, rate = convert_amount(amount, source_currency, user["base_currency"] if user else "USD")
            except (ValueError, RuntimeError) as exc:
                flash(str(exc), "error")
                return redirect(url_for("dashboard.recurring_transactions"))
            conn.execute("INSERT INTO recurring_transactions (user_id, description, amount, type, category, frequency, next_date, currency, base_amount, conversion_rate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (session["user_id"], description, amount, tx_type, category, frequency, next_date, source_currency, base_amount, rate))
            conn.commit()
        flash("Recurring transaction saved.", "success")
        return redirect(url_for("dashboard.recurring_transactions"))
    with get_db_connection() as conn:
        process_due_recurring(conn, session["user_id"])
        recurring = conn.execute("SELECT * FROM recurring_transactions WHERE user_id = ? AND active = 1 ORDER BY next_date", (session["user_id"],)).fetchall()
        user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("recurring.html", recurring=recurring, currency=(user["base_currency"] if user else "USD"), currencies=sorted(SUPPORTED_CURRENCIES))


@bp.route("/reports")
def reports():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        process_due_recurring(conn, session["user_id"])
        transactions = conn.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
        user = conn.execute("SELECT base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    income = sum(float(row["base_amount"] or row["amount"]) for row in transactions if row["type"] == "income")
    expenses = sum(float(row["base_amount"] or row["amount"]) for row in transactions if row["type"] == "expense")
    return render_template("reports.html", transactions=transactions, income=income, expenses=expenses, net=income - expenses, currency=(user["base_currency"] if user else "USD"), monthly_history=monthly_history(transactions))


@bp.route("/export/transactions.csv")
def export_transactions():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        rows = conn.execute("SELECT description, amount, type, category, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Description", "Amount", "Type", "Category", "Created at"])
    writer.writerows([[row["description"], row["amount"], row["type"], row["category"], row["created_at"]] for row in rows])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=clearspend-transactions.csv"})


@bp.route("/export/account.json")
def export_account_data():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        payload = {"profile": dict(conn.execute("SELECT name, email, base_currency, preferred_language FROM users WHERE id = ?", (session["user_id"],)).fetchone())}
        for key, table in (("transactions", "transactions"), ("budgets", "budgets"), ("goals", "savings_goals"), ("recurring", "recurring_transactions")):
            payload[key] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (session["user_id"],)).fetchall()]
    return Response(json.dumps(payload, default=str, ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=clearspend-account-data.json"})


@bp.route("/export/report.pdf")
def export_report_pdf():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    with get_db_connection() as conn:
        rows = conn.execute("SELECT description, type, category, amount, base_amount, created_at FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (session["user_id"],)).fetchall()
        user = conn.execute("SELECT name, base_currency FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    income = sum(float(row["base_amount"] or row["amount"]) for row in rows if row["type"] == "income")
    expenses = sum(float(row["base_amount"] or row["amount"]) for row in rows if row["type"] == "expense")
    currency = user["base_currency"] if user else "USD"
    lines = ["ClearSpend financial report", f"Prepared for {user['name'] if user else 'your account'}", f"Currency: {currency}", f"Income: {income:,.2f}", f"Expenses: {expenses:,.2f}", f"Net cashflow: {income-expenses:,.2f}", "", "Recent transactions"]
    lines += [f"{str(row['created_at'])[:10]} | {row['description']} | {row['type']} | {float(row['base_amount'] or row['amount']):,.2f}" for row in rows]
    return Response(_pdf_document(lines), mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=clearspend-report.pdf"})


@bp.route("/settings/currency", methods=["POST"])
def update_currency():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    currency = (request.form.get("base_currency") or "").upper()
    if currency not in SUPPORTED_CURRENCIES:
        flash("Choose a supported currency.", "error")
    else:
        with get_db_connection() as conn:
            transactions = conn.execute("SELECT id, amount, currency FROM transactions WHERE user_id = ?", (session["user_id"],)).fetchall()
            recurring = conn.execute("SELECT id, amount, currency FROM recurring_transactions WHERE user_id = ?", (session["user_id"],)).fetchall()
            try:
                converted_transactions = [(convert_amount(float(row["amount"]), row["currency"], currency), row["id"]) for row in transactions]
                converted_recurring = [(convert_amount(float(row["amount"]), row["currency"], currency), row["id"]) for row in recurring]
            except (ValueError, RuntimeError) as exc:
                flash(str(exc), "error")
                return redirect(request.referrer or url_for("dashboard.dashboard_home"))
            for (amount, rate), row_id in converted_transactions:
                conn.execute("UPDATE transactions SET base_amount = ?, conversion_rate = ? WHERE id = ?", (amount, rate, row_id))
            for (amount, rate), row_id in converted_recurring:
                conn.execute("UPDATE recurring_transactions SET base_amount = ?, conversion_rate = ? WHERE id = ?", (amount, rate, row_id))
            conn.execute("UPDATE users SET base_currency = ? WHERE id = ?", (currency, session["user_id"]))
        flash(f"Your dashboard currency is now {currency}; all saved amounts were reconverted at live rates.", "success")
    return redirect(request.referrer or url_for("dashboard.dashboard_home"))


@bp.route("/notifications/read", methods=["POST"])
def read_notifications():
    if "user_id" not in session:
        return jsonify({"error": "Authentication required."}), 401
    with get_db_connection() as conn:
        conn.execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (session["user_id"],))
    return jsonify({"ok": True})
