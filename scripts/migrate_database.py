from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import get_db_connection, init_db

load_dotenv()


def main() -> None:
    init_db()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
    for row in rows:
        print(f"{row['version']} applied at {row['applied_at']}")


if __name__ == "__main__":
    main()