from contextlib import contextmanager
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from config import NEON_DSN, MAX_MEMORY

# Thread-safe connection pool globally initialized
pool = None

def init_db_pool():
    global pool
    # Pool minimal 1, maximal 20 connections
    pool = ThreadedConnectionPool(1, 20, dsn=NEON_DSN, cursor_factory=RealDictCursor)

def close_db_pool():
    global pool
    if pool:
        pool.closeall()

@contextmanager
def get_db_cursor(commit=False):
    """
    Context manager to easily get a connection and a cursor from the pool.
    Includes pinging to avoid 'connection already closed' errors from serverless DBs.
    """
    conn = None
    retries = 3
    while retries > 0:
        conn = pool.getconn()
        if conn.closed:
            pool.putconn(conn, close=True)
            conn = None
            retries -= 1
            continue
            
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            break
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            pool.putconn(conn, close=True)
            conn = None
            retries -= 1
            
    if not conn:
        raise Exception("Gagal mendapatkan koneksi database yang valid setelah beberapa percobaan.")

    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception as e:
        if not conn.closed:
            conn.rollback()
        raise e
    finally:
        # If connection died during transaction, close it properly in the pool
        pool.putconn(conn, close=(conn.closed != 0))


def init_postgres():
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                file_type TEXT,
                total_chunks INT DEFAULT 0,
                total_chars INT DEFAULT 0,
                total_lines INT DEFAULT 0,
                uploaded_at TIMESTAMP DEFAULT NOW()
            );
        """)
    print("✅ Postgres tables ready")

def ensure_user(user_id: str, username: str = None):
    with get_db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (id, username) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (user_id, username)
        )

def get_memory(user_id: str) -> list:
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT role, content FROM conversations
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, MAX_MEMORY))
        rows = cur.fetchall()
    # Return chronologically
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def save_memory(user_id: str, role: str, content: str):
    with get_db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO conversations (user_id, role, content) VALUES (%s, %s, %s)",
            (user_id, role, content)
        )

def clear_memory_db(user_id: str):
    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,))

def save_document_meta(user_id: str, filename: str, file_type: str,
                       total_chunks: int, total_chars: int, total_lines: int):
    with get_db_cursor(commit=True) as cur:
        # Upsert
        cur.execute("""
            INSERT INTO documents (user_id, filename, file_type, total_chunks, total_chars, total_lines)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (user_id, filename, file_type, total_chunks, total_chars, total_lines))
        # Update if it exists
        cur.execute("""
            UPDATE documents SET
                total_chunks = %s, total_chars = %s, total_lines = %s, uploaded_at = NOW()
            WHERE user_id = %s AND filename = %s
        """, (total_chunks, total_chars, total_lines, user_id, filename))

def get_user_documents(user_id: str) -> list:
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT filename, file_type, total_chunks, total_chars, total_lines, uploaded_at
            FROM documents WHERE user_id = %s ORDER BY uploaded_at DESC
        """, (user_id,))
        return cur.fetchall()

def delete_document_meta(user_id: str, filename: str):
    with get_db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM documents WHERE user_id = %s AND filename = %s",
            (user_id, filename)
        )
