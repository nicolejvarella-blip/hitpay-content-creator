import json
import sqlite3
from contextlib import contextmanager

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    title TEXT,
    slug TEXT,
    keyword TEXT,
    meta_title TEXT,
    meta_description TEXT,
    overview TEXT,
    categories TEXT,
    tags TEXT,
    status TEXT NOT NULL DEFAULT 'writing',
    date TEXT,
    word_count INTEGER DEFAULT 0,
    model TEXT,
    country TEXT,
    file_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_brand ON posts(brand);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _row_to_dict(row) -> dict:
    return dict(row) if row else None


def save_post(post_data: dict, file_path: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO posts
               (brand, title, slug, keyword, meta_title, meta_description, overview,
                categories, tags, status, date, word_count, model, country, file_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                post_data.get("brand", ""),
                post_data.get("title", ""),
                post_data.get("slug", ""),
                post_data.get("keyword", ""),
                post_data.get("meta_title", ""),
                post_data.get("meta_description", ""),
                post_data.get("overview", ""),
                json.dumps(post_data.get("categories", [])),
                json.dumps(post_data.get("tags", [])),
                post_data.get("status", "writing"),
                post_data.get("date", ""),
                len(post_data.get("content", "").split()),
                post_data.get("model", ""),
                post_data.get("country", ""),
                file_path,
            ),
        )
        return cur.lastrowid


def get_post(post_id: int) -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return _row_to_dict(row)


def get_post_by_slug(slug: str) -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
        return _row_to_dict(row)


def list_posts(status: str = None, brand: str = None) -> list[dict]:
    query = "SELECT * FROM posts WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if brand:
        query += " AND brand = ?"
        params.append(brand)
    query += " ORDER BY id DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]


def update_post_status(post_id: int, new_status: str, old_file: str, new_file: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE posts SET status = ?, file_path = ? WHERE id = ?",
            (new_status, new_file, post_id),
        )


def update_post_fields(post_id: int, updates: dict):
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(
            f"UPDATE posts SET {set_clause} WHERE id = ?",
            (*updates.values(), post_id),
        )


def delete_post(post_id: int):
    with _connect() as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
