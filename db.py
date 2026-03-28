"""
PUT UP — Database layer
Uses PostgreSQL when DATABASE_URL is set, falls back to wallets.json for local dev.
"""

import os
import json

DATABASE_URL = os.environ.get("DATABASE_URL") or None

# ── PostgreSQL helpers ────────────────────────────────────────────

def _get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create wallets table if it doesn't exist."""
    if not DATABASE_URL:
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    name TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    seed TEXT NOT NULL,
                    email TEXT,
                    password_hash TEXT,
                    balance REAL DEFAULT 0,
                    deposit_xrp REAL DEFAULT 0,
                    stripe_paid BOOLEAN DEFAULT FALSE
                )
            """)
        conn.commit()
    finally:
        conn.close()


def load_wallets():
    """Return wallets as dict matching wallets.json format."""
    if not DATABASE_URL:
        return _load_from_file()

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, address, seed, email, password_hash, balance, deposit_xrp, stripe_paid FROM wallets")
            rows = cur.fetchall()
    finally:
        conn.close()

    result = {}
    for row in rows:
        name, address, seed, email, password_hash, balance, deposit_xrp, stripe_paid = row
        entry = {"address": address, "seed": seed}
        if email is not None:
            entry["email"] = email
        if password_hash is not None:
            entry["password_hash"] = password_hash
        if balance is not None:
            entry["balance"] = balance
        if deposit_xrp is not None:
            entry["deposit_xrp"] = deposit_xrp
        if stripe_paid is not None:
            entry["stripe_paid"] = stripe_paid
        result[name] = entry
    return result


def save_wallet(name, data):
    """Insert or update a single wallet entry."""
    if not DATABASE_URL:
        return  # file-based saves handled directly in app.py for local dev

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wallets (name, address, seed, email, password_hash, balance, deposit_xrp, stripe_paid)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    address = EXCLUDED.address,
                    seed = EXCLUDED.seed,
                    email = EXCLUDED.email,
                    password_hash = EXCLUDED.password_hash,
                    balance = EXCLUDED.balance,
                    deposit_xrp = EXCLUDED.deposit_xrp,
                    stripe_paid = EXCLUDED.stripe_paid
            """, (
                name,
                data.get("address"),
                data.get("seed"),
                data.get("email"),
                data.get("password_hash"),
                data.get("balance", 0),
                data.get("deposit_xrp", 0),
                data.get("stripe_paid", False),
            ))
        conn.commit()
    finally:
        conn.close()


def save_all_wallets(wallets_dict):
    """Upsert all wallets from a dict."""
    if not DATABASE_URL:
        return _save_to_file(wallets_dict)
    for name, data in wallets_dict.items():
        save_wallet(name, data)


# ── File fallback (local dev) ─────────────────────────────────────

def _wallets_path():
    import config
    wallets_dir = os.environ.get("WALLETS_DIR")
    if wallets_dir:
        return os.path.join(wallets_dir, "wallets.json")
    return config.WALLETS_FILE


def _load_from_file():
    path = _wallets_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _save_to_file(wallets_dict):
    path = _wallets_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(wallets_dict, f, indent=2)
