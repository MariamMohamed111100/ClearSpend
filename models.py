from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path


def get_db_path() -> Path:
    return Path(os.getenv("FINANCE_DB_PATH", Path(__file__).resolve().parent / "finance_app.db"))


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


class PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, parameters=()):
        return self._connection.execute(query.replace("?", "%s"), parameters)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self._connection.rollback()
        else:
            self._connection.commit()
        self.close()


def get_db_connection():
    database_url = _database_url()
    if database_url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires psycopg. Install the project requirements.") from exc
        return PostgresConnection(psycopg.connect(database_url, row_factory=dict_row))

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def feature_is_enabled(key: str, default: bool = True) -> bool:
    """Return a persisted feature flag, falling back safely before it is seeded."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT enabled FROM feature_flags WHERE key = ?", (key,)).fetchone()
    return default if row is None else bool(row["enabled"])


def init_db() -> None:
    if _database_url().startswith(("postgres://", "postgresql://")):
        _init_postgres_db()
        return

    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                limit_amount REAL NOT NULL,
                spent_amount REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                base_amount REAL,
                conversion_rate REAL NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL DEFAULT 'free',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS savings_goals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, target_amount REAL NOT NULL, saved_amount REAL NOT NULL DEFAULT 0, deadline TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS recurring_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL, type TEXT NOT NULL, category TEXT NOT NULL, frequency TEXT NOT NULL, next_date TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', base_amount REAL, conversion_rate REAL NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS feature_flags (key TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, subject TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS support_ticket_comments (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL, author_id INTEGER NOT NULL, message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (ticket_id) REFERENCES support_tickets(id), FOREIGN KEY (author_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT, detail TEXT NOT NULL DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (actor_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, message TEXT NOT NULL, audience TEXT NOT NULL DEFAULT 'all', active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS backup_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        for column in ("stripe_customer_id", "stripe_subscription_id"):
            try:
                conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        try:
            conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        for table, column, definition in (
            ("users", "base_currency", "TEXT NOT NULL DEFAULT 'USD'"),
            ("users", "preferred_language", "TEXT NOT NULL DEFAULT 'en'"),
            ("users", "theme_preference", "TEXT NOT NULL DEFAULT 'light'"),
            ("users", "two_factor_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("users", "two_factor_code_hash", "TEXT"),
            ("users", "two_factor_expires_at", "TEXT"),
            ("users", "avatar_filename", "TEXT"),
            ("users", "avatar_data", "TEXT"),
            ("users", "role", "TEXT NOT NULL DEFAULT 'user'"),
            ("users", "account_status", "TEXT NOT NULL DEFAULT 'active'"),
            ("users", "last_login_at", "TEXT"),
            ("budgets", "period", "TEXT NOT NULL DEFAULT 'monthly'"),
            ("transactions", "currency", "TEXT NOT NULL DEFAULT 'USD'"),
            ("transactions", "base_amount", "REAL"),
            ("transactions", "conversion_rate", "REAL NOT NULL DEFAULT 1"),
            ("recurring_transactions", "currency", "TEXT NOT NULL DEFAULT 'USD'"),
            ("recurring_transactions", "base_amount", "REAL"),
            ("recurring_transactions", "conversion_rate", "REAL NOT NULL DEFAULT 1"),
        ):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        conn.execute("UPDATE transactions SET base_amount = amount WHERE base_amount IS NULL")
        conn.execute("UPDATE recurring_transactions SET base_amount = amount WHERE base_amount IS NULL")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            ("001_initial_schema",),
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_created ON transactions(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_budgets_user_created ON budgets(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_created ON subscriptions(user_id, created_at)")
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            ("002_user_activity_indexes",),
        )
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", ("003_goals_recurring_notifications",))
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", ("004_currency_and_finance_events",))
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", ("005_two_factor_email",))
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", ("006_profiles_budget_periods",))
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", ("007_admin_operations",))
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", ("008_database_avatars",))
        conn.commit()


def _init_postgres_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id),
                category TEXT NOT NULL,
                limit_amount DOUBLE PRECISION NOT NULL,
                spent_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id),
                description TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD', base_amount DOUBLE PRECISION, conversion_rate DOUBLE PRECISION NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(id),
                plan TEXT NOT NULL DEFAULT 'free',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                id BIGSERIAL PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING",
            ("001_initial_schema",),
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_created ON transactions(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_budgets_user_created ON budgets(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_created ON subscriptions(user_id, created_at)")
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING",
            ("002_user_activity_indexes",),
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS savings_goals (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), name TEXT NOT NULL, target_amount DOUBLE PRECISION NOT NULL, saved_amount DOUBLE PRECISION NOT NULL DEFAULT 0, deadline TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS recurring_transactions (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), description TEXT NOT NULL, amount DOUBLE PRECISION NOT NULL, type TEXT NOT NULL, category TEXT NOT NULL, frequency TEXT NOT NULL, next_date TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', base_amount DOUBLE PRECISION, conversion_rate DOUBLE PRECISION NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS notifications (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), title TEXT NOT NULL, message TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS feature_flags (key TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS support_tickets (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), subject TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS support_ticket_comments (id BIGSERIAL PRIMARY KEY, ticket_id BIGINT NOT NULL REFERENCES support_tickets(id), author_id BIGINT NOT NULL REFERENCES users(id), message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_logs (id BIGSERIAL PRIMARY KEY, actor_id BIGINT REFERENCES users(id), action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT, detail TEXT NOT NULL DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS platform_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS announcements (id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, message TEXT NOT NULL, audience TEXT NOT NULL DEFAULT 'all', active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS backup_runs (id BIGSERIAL PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING", ("003_goals_recurring_notifications",))
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS base_currency TEXT NOT NULL DEFAULT 'USD'")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_language TEXT NOT NULL DEFAULT 'en'")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme_preference TEXT NOT NULL DEFAULT 'light'")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_enabled INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_code_hash TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_expires_at TIMESTAMP")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_filename TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT 'active'")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP")
        conn.execute("ALTER TABLE budgets ADD COLUMN IF NOT EXISTS period TEXT NOT NULL DEFAULT 'monthly'")
        conn.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'USD'")
        conn.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS base_amount DOUBLE PRECISION")
        conn.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS conversion_rate DOUBLE PRECISION NOT NULL DEFAULT 1")
        conn.execute("ALTER TABLE recurring_transactions ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'USD'")
        conn.execute("ALTER TABLE recurring_transactions ADD COLUMN IF NOT EXISTS base_amount DOUBLE PRECISION")
        conn.execute("ALTER TABLE recurring_transactions ADD COLUMN IF NOT EXISTS conversion_rate DOUBLE PRECISION NOT NULL DEFAULT 1")
        conn.execute("UPDATE transactions SET base_amount = amount WHERE base_amount IS NULL")
        conn.execute("UPDATE recurring_transactions SET base_amount = amount WHERE base_amount IS NULL")
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING", ("004_currency_and_finance_events",))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING", ("005_two_factor_email",))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING", ("006_profiles_budget_periods",))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING", ("007_admin_operations",))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?) ON CONFLICT DO NOTHING", ("008_database_avatars",))
