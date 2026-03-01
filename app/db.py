"""Database layer for ChatBotura - SQLite tenant config & conversation management."""
import sqlite3
import os
import uuid
import bcrypt
from typing import Optional, Tuple
from contextlib import contextmanager
from datetime import datetime

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
    """Initialize database with tenants table, conversations table, and mock data."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Create tenants table with API key support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                business_name TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                tone TEXT NOT NULL DEFAULT 'professional',
                api_key_hash TEXT
            )
        """)

        # Add api_key_hash column if it doesn't exist (migration for existing DBs)
        cursor.execute("PRAGMA table_info(tenants)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'api_key_hash' not in columns:
            cursor.execute("ALTER TABLE tenants ADD COLUMN api_key_hash TEXT")
            print("✓ Added api_key_hash column to tenants table")

        # Create conversations table for persistent chat history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
            )
        """)

        # Create messages table for individual messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
            )
        """)

        # Create indexes for better query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_tenant_session 
            ON conversations(tenant_id, session_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation 
            ON messages(conversation_id)
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

        # Ensure all tenants have API keys (for new installations or upgrades)
        cursor.execute("SELECT tenant_id FROM tenants WHERE api_key_hash IS NULL")
        tenants_without_keys = [row["tenant_id"] for row in cursor.fetchall()]
        for tenant_id in tenants_without_keys:
            api_key = ensure_tenant_api_key(tenant_id)
            if api_key:
                print(f"✓ Generated API key for tenant '{tenant_id}': {api_key}")
                print("  ⚠️  Store this key securely! It won't be shown again.")


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


# ============================================================================
# API Key Management
# ============================================================================

import secrets
import hashlib

def generate_api_key(length: int = 32) -> str:
    """Generate a cryptographically secure API key."""
    return secrets.token_urlsafe(length)

def hash_api_key(api_key: str) -> str:
    """Hash an API key using bcrypt."""
    return bcrypt.hashpw(api_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """Verify an API key against its stored hash."""
    return bcrypt.checkpw(api_key.encode('utf-8'), stored_hash.encode('utf-8'))

def set_tenant_api_key(tenant_id: str, api_key_hash: str) -> bool:
    """Set the API key hash for a tenant."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tenants SET api_key_hash = ? WHERE tenant_id = ?",
            (api_key_hash, tenant_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def get_tenant_by_api_key(api_key: str) -> Optional[dict]:
    """Fetch tenant by validating API key."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tenants WHERE api_key_hash IS NOT NULL")
        rows = cursor.fetchall()
        for row in rows:
            tenant_dict = dict(row)
            if verify_api_key(api_key, tenant_dict["api_key_hash"]):
                return tenant_dict
        return None

def ensure_tenant_api_key(tenant_id: str) -> str:
    """Ensure a tenant has an API key; generate if missing. Returns the plain API key."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT api_key_hash FROM tenants WHERE tenant_id = ?", (tenant_id,))
        row = cursor.fetchone()
        if row and row["api_key_hash"]:
            # API key already exists, return None to indicate it's already set
            return None

    # Generate new API key
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    if set_tenant_api_key(tenant_id, api_key_hash):
        return api_key
    return None


# Conversation Management Functions

def create_conversation(tenant_id: str, session_id: str) -> str:
    """Create a new conversation session.
    
    Args:
        tenant_id: The tenant identifier
        session_id: A unique session identifier (e.g., from the client)
    
    Returns:
        The conversation_id (UUID)
    """
    conversation_id = str(uuid.uuid4())
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (conversation_id, tenant_id, session_id) VALUES (?, ?, ?)",
            (conversation_id, tenant_id, session_id)
        )
        conn.commit()
    return conversation_id


def get_or_create_conversation(tenant_id: str, session_id: str) -> str:
    """Get an existing conversation or create a new one.
    
    Args:
        tenant_id: The tenant identifier
        session_id: A unique session identifier
    
    Returns:
        The conversation_id
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        # Try to find existing conversation
        cursor.execute(
            "SELECT conversation_id FROM conversations WHERE tenant_id = ? AND session_id = ? ORDER BY created_at DESC LIMIT 1",
            (tenant_id, session_id)
        )
        row = cursor.fetchone()
        if row:
            return row["conversation_id"]
    
    # Create new conversation if none exists
    return create_conversation(tenant_id, session_id)


def add_message(conversation_id: str, role: str, content: str) -> int:
    """Add a message to a conversation.
    
    Args:
        conversation_id: The conversation identifier
        role: The message role ("user" or "assistant")
        content: The message content
    
    Returns:
        The message ID
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content)
        )
        # Update the conversation's updated_at timestamp
        cursor.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE conversation_id = ?",
            (conversation_id,)
        )
        conn.commit()
        return cursor.lastrowid


def get_conversation_messages(conversation_id: str) -> list[dict]:
    """Get all messages from a conversation.
    
    Args:
        conversation_id: The conversation identifier
    
    Returns:
        List of messages as dicts with role and content
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_conversation_history(tenant_id: str, session_id: str) -> list[dict]:
    """Get conversation history for a tenant/session.
    
    Args:
        tenant_id: The tenant identifier
        session_id: The session identifier
    
    Returns:
        List of messages as dicts
    """
    conversation_id = get_or_create_conversation(tenant_id, session_id)
    return get_conversation_messages(conversation_id)


def list_conversations(tenant_id: str, limit: int = 20) -> list[dict]:
    """List recent conversations for a tenant.
    
    Args:
        tenant_id: The tenant identifier
        limit: Maximum number of conversations to return
    
    Returns:
        List of conversations with metadata
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT conversation_id, session_id, created_at, updated_at 
               FROM conversations WHERE tenant_id = ? 
               ORDER BY updated_at DESC LIMIT ?""",
            (tenant_id, limit)
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation and its messages.
    
    Args:
        conversation_id: The conversation identifier
    
    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        # Delete messages first
        cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        # Delete conversation
        cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
        conn.commit()
        return cursor.rowcount > 0


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {get_db_path()}")
