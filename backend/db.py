import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime

# Load .env before reading DB config
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env', override=True)

logger = logging.getLogger(__name__)

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "scaloz_super_admin"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5432")),
}

# ─── Connection Pool ──────────────────────────────────────────────────────────
_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    """Lazy-init a threaded connection pool (1–10 connections)."""
    global _pool
    if _pool is None or _pool.closed:
        try:
            _pool = ThreadedConnectionPool(1, 10, **DB_CONFIG)
            logger.info("PostgreSQL connection pool created successfully.")
        except Exception as e:
            logger.error(f"Failed to create connection pool: {e}")
            raise
    return _pool


def get_connection():
    """Get a connection from the pool."""
    return _get_pool().getconn()


def release_connection(conn):
    """Return a connection to the pool."""
    try:
        if _pool and conn and not conn.closed:
            _pool.putconn(conn)
    except Exception as e:
        logger.warning(f"Error releasing connection: {e}")


def init_db():
    """Create tables for chat sessions and messages if they do not exist."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS xeva_chat_sessions (
                id VARCHAR(100) PRIMARY KEY,
                employee_id VARCHAR(100) NOT NULL,
                title VARCHAR(255) NOT NULL,
                is_pinned BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS xeva_chat_messages (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(100) REFERENCES xeva_chat_sessions(id) ON DELETE CASCADE,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.commit()
        cur.close()
        logger.info("Xeva PostgreSQL chat tables initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

def get_employee_sessions(employee_id: str):
    """Retrieve all chat sessions and their messages for a given employee."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT id, employee_id, title, is_pinned, 
                   EXTRACT(EPOCH FROM created_at)*1000 AS created_at
            FROM xeva_chat_sessions
            WHERE employee_id = %s
            ORDER BY is_pinned DESC, updated_at DESC;
        """, (employee_id,))
        
        sessions = cur.fetchall()
        
        for sess in sessions:
            cur.execute("""
                SELECT role, content, EXTRACT(EPOCH FROM created_at)*1000 AS ts
                FROM xeva_chat_messages
                WHERE session_id = %s
                ORDER BY id ASC;
            """, (sess["id"],))
            
            sess["messages"] = cur.fetchall()
            
            # Reconstruct history format for agent
            msgs = sess["messages"]
            sess["history"] = [{"role": m["role"], "content": m["content"]} for m in msgs]
            sess["isPinned"] = sess["is_pinned"]
            sess["createdAt"] = sess["created_at"]
            
        cur.close()
        return sessions
    except Exception as e:
        logger.error(f"Error fetching sessions for {employee_id}: {e}")
        return []
    finally:
        if conn is not None:
            release_connection(conn)

def save_session(session_id: str, employee_id: str, title: str, is_pinned: bool = False):
    """Create or update a chat session."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO xeva_chat_sessions (id, employee_id, title, is_pinned, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) 
            DO UPDATE SET 
                updated_at = CURRENT_TIMESTAMP,
                title = CASE WHEN xeva_chat_sessions.title = 'New Chat' THEN EXCLUDED.title ELSE xeva_chat_sessions.title END;
        """, (session_id, employee_id, title, is_pinned))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Error saving session {session_id}: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

def add_message(session_id: str, role: str, content: str):
    """Add a message to a session and touch updated_at."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO xeva_chat_messages (session_id, role, content)
            VALUES (%s, %s, %s);
        """, (session_id, role, content))
        
        cur.execute("""
            UPDATE xeva_chat_sessions 
            SET updated_at = CURRENT_TIMESTAMP 
            WHERE id = %s;
        """, (session_id,))
        
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Error adding message to {session_id}: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

def update_session_pin(session_id: str, is_pinned: bool):
    """Update pinned status."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE xeva_chat_sessions SET is_pinned = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;
        """, (is_pinned, session_id))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Error updating pin for {session_id}: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

def update_session_title(session_id: str, title: str):
    """Update title."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE xeva_chat_sessions SET title = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;
        """, (title, session_id))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Error updating title for {session_id}: {e}")
    finally:
        if conn is not None:
            release_connection(conn)

def delete_session(session_id: str):
    """Delete a session and its messages."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM xeva_chat_sessions WHERE id = %s;", (session_id,))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
    finally:
        if conn is not None:
            release_connection(conn)


