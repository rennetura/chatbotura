"""Database layer for ChatBotura - SQLite tenant config management."""
import sqlite3
import os
from typing import Optional
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "chatbotura.db")


def get_db_path() -> str:
    """Get absolute path to database."""
    return os.path.abspath(DB_PATH)


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database with tenants table and mock data."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Create tenants table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                business_name TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                tone TEXT NOT NULL DEFAULT 'professional'
            )
        """)

        # Check if mock data already exists
        cursor.execute("SELECT COUNT(*) FROM tenants")
        if cursor.fetchone()[0] == 0:
            # Insert mock tenants
            mock_tenants = [
                (
                    "pizza_shop",
                    "Mario's Pizza Palace",
                    """You are a friendly and enthusiastic pizza shop assistant. 
Your goal is to help customers with their orders, answer questions about our menu,
and provide a warm, inviting experience. Be helpful, quick, and enthusiastic about pizza!
                    """,
                    "friendly"
                ),
                (
                    "law_firm",
                    "Pearson & Associates Law",
                    """You are a professional legal assistant for Pearson & Associates Law Firm.
Your goal is to provide helpful information, schedule consultations, and answer
basic legal questions. Be professional, courteous, and precise. Always remind
clients that you are not providing legal advice and recommend they consult with an attorney.
                    """,
                    "professional"
                )
            ]

            cursor.executemany(
                "INSERT INTO tenants (tenant_id, business_name, system_prompt, tone) VALUES (?, ?, ?, ?)",
                mock_tenants
            )
            conn.commit()
            print("✓ Initialized database with mock tenants")


def get_tenant(tenant_id: str) -> Optional[dict]:
    """Fetch tenant configuration by tenant_id."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tenant_id, business_name, system_prompt, tone FROM tenants WHERE tenant_id = ?",
            (tenant_id,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def get_all_tenants() -> list[dict]:
    """Fetch all tenants."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tenant_id, business_name, system_prompt, tone FROM tenants")
        return [dict(row) for row in cursor.fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {get_db_path()}")
