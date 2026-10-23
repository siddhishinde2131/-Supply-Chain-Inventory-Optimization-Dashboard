"""PostgreSQL connection settings and safe connection handling.

Credentials come from environment variables (or a local ``.env`` file that is
excluded from Git). Nothing is hard-coded. See ``.env.example``.
"""
import os
from contextlib import contextmanager
from dataclasses import dataclass

from dotenv import load_dotenv

from src.config import PROJECT_ROOT


class DatabaseError(Exception):
    """A database problem explained in plain language."""


@dataclass(frozen=True)
class DbConfig:
    host: str = "localhost"
    port: int = 5432
    dbname: str = "inventory_dashboard"
    user: str = "postgres"
    password: str = ""
    sslmode: str = "prefer"

    def describe(self) -> str:
        """Connection description WITHOUT the password (safe to display)."""
        return f"{self.user}@{self.host}:{self.port}/{self.dbname}"


def config_from_env(prefix: str = "PG") -> DbConfig:
    """Read PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    defaults = DbConfig()
    port = os.getenv(f"{prefix}PORT", str(defaults.port))
    try:
        port_number = int(port)
    except ValueError as exc:
        raise DatabaseError(f"{prefix}PORT must be a number, got '{port}'.") from exc
    return DbConfig(
        host=os.getenv(f"{prefix}HOST", defaults.host),
        port=port_number,
        dbname=os.getenv(f"{prefix}DATABASE", defaults.dbname),
        user=os.getenv(f"{prefix}USER", defaults.user),
        password=os.getenv(f"{prefix}PASSWORD", defaults.password),
        sslmode=os.getenv(f"{prefix}SSLMODE", defaults.sslmode),
    )


def _friendly_message(exc: Exception, config: DbConfig) -> str:
    text = str(exc).strip()
    lower = text.lower()
    if "password authentication failed" in lower or "no password supplied" in lower:
        return (f"Login failed for user '{config.user}'. Check PGUSER / PGPASSWORD in your "
                ".env file or in the connection form.")
    if "does not exist" in lower and "database" in lower:
        return (f"Database '{config.dbname}' does not exist. Create it first, e.g. in psql: "
                f"CREATE DATABASE {config.dbname};")
    if "could not connect" in lower or "connection refused" in lower or "timeout" in lower \
            or "could not translate host name" in lower:
        return (f"Cannot reach PostgreSQL at {config.host}:{config.port}. Check that the "
                "server is running and the host/port are correct.")
    return f"Database error: {text}"


def connect(config: DbConfig):
    """Open a psycopg2 connection or raise DatabaseError with a clear message."""
    import psycopg2  # imported lazily so CSV mode works even without the driver

    try:
        return psycopg2.connect(host=config.host, port=config.port, dbname=config.dbname,
                                user=config.user, password=config.password or None,
                                sslmode=config.sslmode, connect_timeout=5,
                                application_name="inventory_dashboard")
    except psycopg2.Error as exc:
        raise DatabaseError(_friendly_message(exc, config)) from exc


@contextmanager
def connection(config: DbConfig):
    """``with connection(cfg) as conn:`` - commits on success, rolls back on error."""
    conn = connect(config)
    try:
        yield conn
        conn.commit()
    except DatabaseError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        import psycopg2

        if isinstance(exc, psycopg2.Error):
            raise DatabaseError(_friendly_message(exc, config)) from exc
        raise
    finally:
        conn.close()


def check_connection(config: DbConfig) -> tuple[bool, str]:
    """Try to connect and run a trivial query. Returns (ok, message)."""
    try:
        with connection(config) as conn, conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0].split(",")[0]
        return True, f"Connected to {config.describe()} ({version})."
    except DatabaseError as exc:
        return False, str(exc)
