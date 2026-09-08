from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", ROOT / "backups"))


def backup_sqlite() -> Path:
    source = Path(os.getenv("FINANCE_DB_PATH", ROOT / "finance_app.db"))
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")
    destination = BACKUP_DIR / f"finance_app_{timestamp()}.db"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as backup_connection:
        source_connection.backup(backup_connection)
    return destination


def backup_postgres(database_url: str) -> Path:
    destination = BACKUP_DIR / f"finance_app_{timestamp()}.dump"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(destination), database_url],
        check=True,
        capture_output=True,
        text=True,
    )
    return destination


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    destination = backup_postgres(database_url) if database_url.startswith(("postgres://", "postgresql://")) else backup_sqlite()
    print(destination)


if __name__ == "__main__":
    main()
