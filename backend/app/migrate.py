"""Oddiy SQL migratsiya ishga tushirgich: `python -m app.migrate`."""
from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _dsn() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


def migrate(dsn: str | None = None) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn or _dsn(), autocommit=False) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
        conn.execute("SELECT pg_advisory_xact_lock(727274)")
        done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
    return applied


if __name__ == "__main__":
    names = migrate()
    print("Qoʻllandi:", ", ".join(names) if names else "yangi migratsiya yoʻq")
