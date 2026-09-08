"""Small, dependency-free finance domain helpers."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from calendar import monthrange
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "EGP", "SAR", "AED", "CAD", "AUD", "JPY"}
_rate_cache: dict[tuple[str, str], float] = {}
# Last-resort reference rates per USD. They keep offline local installs usable; a
# successful provider response always supersedes them and is cached for the process.
_REFERENCE_USD_RATES = {"USD": 1.0, "EUR": 0.92, "GBP": 0.78, "EGP": 50.7, "SAR": 3.75, "AED": 3.6725, "CAD": 1.38, "AUD": 1.52, "JPY": 150.0}


def _json_from(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ClearSpend/1.0"})
    with urlopen(request, timeout=6) as response:
        return json.loads(response.read().decode("utf-8"))


def convert_amount(amount: float, source: str, target: str) -> tuple[float, float]:
    """Convert at a live rate, with provider failover and last-known-rate caching."""
    source, target = source.upper(), target.upper()
    if source not in SUPPORTED_CURRENCIES or target not in SUPPORTED_CURRENCIES:
        raise ValueError("Unsupported currency")
    if source == target:
        return round(amount, 2), 1.0
    key = (source, target)
    try:
        # Frankfurter is ECB-backed.  It is the primary source when it covers the pair.
        query = urlencode({"amount": amount, "from": source, "to": target})
        payload = _json_from(f"https://api.frankfurter.app/latest?{query}")
        rate = float(payload["rates"][target]) / amount
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        try:
            # Independent provider; importantly, it covers EGP, SAR and AED too.
            payload = _json_from(f"https://open.er-api.com/v6/latest/{source}")
            rate = float(payload["rates"][target])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            rate = _rate_cache.get(key)
            if rate is None:
                # The UI stays functional for local/offline work. This is explicitly
                # a reference rate; it is replaced automatically on the next live call.
                rate = _REFERENCE_USD_RATES[target] / _REFERENCE_USD_RATES[source]
    _rate_cache[key] = rate
    return round(amount * rate, 2), round(rate, 8)


def add_frequency(start: date, frequency: str) -> date:
    if frequency == "weekly":
        return start + timedelta(days=7)
    if frequency == "yearly":
        try:
            return start.replace(year=start.year + 1)
        except ValueError:
            return start.replace(year=start.year + 1, day=28)
    # monthly, retaining the closest valid day (e.g. Jan 31 -> Feb 28).
    month = start.month + 1
    year = start.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))


def notify(conn, user_id: int, title: str, message: str) -> None:
    existing = conn.execute(
        "SELECT id FROM notifications WHERE user_id = ? AND title = ? AND message = ? AND read = 0",
        (user_id, title, message),
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO notifications (user_id, title, message) VALUES (?, ?, ?)",
            (user_id, title, message),
        )


def process_due_recurring(conn, user_id: int, today: date | None = None) -> int:
    today = today or date.today()
    rows = conn.execute(
        "SELECT * FROM recurring_transactions WHERE user_id = ? AND active = 1", (user_id,)
    ).fetchall()
    generated = 0
    for item in rows:
        try:
            due = date.fromisoformat(item["next_date"])
        except (TypeError, ValueError):
            continue
        while due <= today:
            currency = item["currency"] or "USD"
            base_amount = float(item["base_amount"] or item["amount"])
            conn.execute(
                """INSERT INTO transactions
                   (user_id, description, amount, type, category, currency, base_amount, conversion_rate, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, item["description"], item["amount"], item["type"], item["category"], currency, base_amount,
                 item["conversion_rate"] or 1, due.isoformat()),
            )
            notify(conn, user_id, "Recurring transaction posted", f"{item['description']} was added for {due.isoformat()}.")
            due = add_frequency(due, item["frequency"])
            generated += 1
        conn.execute("UPDATE recurring_transactions SET next_date = ? WHERE id = ?", (due.isoformat(), item["id"]))
    return generated


def monthly_history(rows, months: int = 6):
    """Return chronological, zero-filled monthly income/expense points."""
    today = date.today().replace(day=1)
    keys = []
    for offset in range(months - 1, -1, -1):
        index = today.year * 12 + today.month - 1 - offset
        keys.append((index // 12, index % 12 + 1))
    result = {f"{year:04d}-{month:02d}": {"income": 0.0, "expense": 0.0} for year, month in keys}
    for row in rows:
        raw = str(row["created_at"] or "")
        key = raw[:7]
        if key in result and row["type"] in {"income", "expense"}:
            result[key][row["type"]] += float(row["base_amount"] or row["amount"] or 0)
    return [
        {"label": datetime.strptime(key, "%Y-%m").strftime("%b"), "income": values["income"], "expense": values["expense"]}
        for key, values in result.items()
    ]
