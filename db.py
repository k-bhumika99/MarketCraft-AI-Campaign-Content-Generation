"""
db.py — Storage Module for MarketCraft AI
Handles all SQLite persistence: users, imported campaign reports, and
generated marketing kits.
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marketcraft.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            source_filename TEXT,
            source_type TEXT,
            raw_text TEXT,
            campaign_name TEXT,
            product_name TEXT,
            campaign_info_json TEXT,
            content_json TEXT,
            status TEXT NOT NULL DEFAULT 'imported',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # Non-destructive migration helper for future column additions.
    _ensure_columns(cur, "campaigns", {
        "brand_score": "REAL",
        "platform_count": "INTEGER DEFAULT 0",
    })
    conn.commit()
    conn.close()


def _ensure_columns(cur, table, columns: dict):
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    for name, coltype in columns.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")


# ---------------------------------------------------------------------------
# Users / Authentication
# ---------------------------------------------------------------------------

def create_user(full_name: str, email: str, password_hash: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (full_name, email, password_hash, created_at)
        VALUES (?, ?, ?, ?)
    """, (full_name, email, password_hash, datetime.utcnow().isoformat()))
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def get_user_by_email(email: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Campaign reports / marketing kits
# ---------------------------------------------------------------------------

def create_campaign(user_id, source_filename, source_type, raw_text) -> int:
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute("""
        INSERT INTO campaigns
            (user_id, source_filename, source_type, raw_text, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'imported', ?, ?)
    """, (user_id, source_filename, source_type, raw_text, now, now))
    conn.commit()
    campaign_id = cur.lastrowid
    conn.close()
    return campaign_id


def save_campaign_understanding(campaign_id, campaign_info: dict):
    conn = get_connection()
    conn.execute("""
        UPDATE campaigns
        SET campaign_info_json = ?, campaign_name = ?, product_name = ?,
            status = 'analyzed', updated_at = ?
        WHERE id = ?
    """, (
        json.dumps(campaign_info),
        campaign_info.get("campaign_name", ""),
        campaign_info.get("product_name", ""),
        datetime.utcnow().isoformat(),
        campaign_id,
    ))
    conn.commit()
    conn.close()


def save_generated_kit(campaign_id, content: dict, brand_score=None, platform_count=0):
    conn = get_connection()
    conn.execute("""
        UPDATE campaigns
        SET content_json = ?, status = 'ready', brand_score = ?, platform_count = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        json.dumps(content), brand_score, platform_count,
        datetime.utcnow().isoformat(), campaign_id,
    ))
    conn.commit()
    conn.close()


def _row_to_campaign(row):
    if not row:
        return None
    d = dict(row)
    d["campaign_info"] = json.loads(d["campaign_info_json"]) if d.get("campaign_info_json") else {}
    d["content"] = json.loads(d["content_json"]) if d.get("content_json") else {}
    return d


def get_campaign(campaign_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    conn.close()
    return _row_to_campaign(row)


def list_campaigns(user_id=None, limit=100):
    conn = get_connection()
    if user_id:
        rows = conn.execute(
            "SELECT * FROM campaigns WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [_row_to_campaign(r) for r in rows]


def delete_campaign(campaign_id):
    conn = get_connection()
    conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    conn.commit()
    conn.close()


def get_dashboard_stats(user_id=None):
    conn = get_connection()
    where = "WHERE user_id = ?" if user_id else ""
    params = (user_id,) if user_id else ()

    total = conn.execute(f"SELECT COUNT(*) c FROM campaigns {where}", params).fetchone()["c"]
    ready = conn.execute(
        f"SELECT COUNT(*) c FROM campaigns {where}{' AND' if where else 'WHERE'} status = 'ready'",
        params,
    ).fetchone()["c"]
    avg_score_row = conn.execute(
        f"SELECT AVG(brand_score) a FROM campaigns {where}{' AND' if where else 'WHERE'} brand_score IS NOT NULL",
        params,
    ).fetchone()
    avg_score = round(avg_score_row["a"], 1) if avg_score_row and avg_score_row["a"] else 0
    total_platforms_row = conn.execute(
        f"SELECT SUM(platform_count) s FROM campaigns {where}",
        params,
    ).fetchone()
    total_platforms = total_platforms_row["s"] or 0
    recent = conn.execute(
        f"SELECT * FROM campaigns {where} ORDER BY id DESC LIMIT 6", params
    ).fetchall()
    conn.close()
    return {
        "total_campaigns": total,
        "ready_kits": ready,
        "avg_brand_score": avg_score,
        "total_assets": total_platforms,
        "recent": [_row_to_campaign(r) for r in recent],
    }
