import sqlite3
import bcrypt
import os
import uuid
import time
import secrets
from datetime import datetime
from typing import Optional, Tuple
import numpy as np

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'keystroke_auth.db')

# pre-computed dummy hash used for constant-time comparison when username doesn't exist,
# preventing a timing oracle that would reveal whether a username is registered
_DUMMY_HASH = bcrypt.hashpw(b'dummy', bcrypt.gensalt())


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            passphrase_hash TEXT NOT NULL,
            profile_data BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # add column for safe re-enrollment (old profile stays active until new one is complete)
    try:
        c.execute('ALTER TABLE users ADD COLUMN pending_profile_data BLOB')
    except sqlite3.OperationalError:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS enrollment_samples (
            user_id TEXT NOT NULL,
            sample_index INTEGER NOT NULL,
            timing_data BLOB NOT NULL,
            expires_at REAL NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, sample_index),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    try:
        c.execute('ALTER TABLE enrollment_samples ADD COLUMN expires_at REAL NOT NULL DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # short-lived single-use codes for oauth-style token exchange (never in urls)
    c.execute('''
        CREATE TABLE IF NOT EXISTS auth_codes (
            code TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            auth_method TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
    ''')

    # persistent rate limits keyed by "auth:{user_id}" or "ip:{ip}:{endpoint}"
    c.execute('''
        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 1,
            expires_at REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


# --- passphrase ---

def hash_passphrase(passphrase: str) -> str:
    return bcrypt.hashpw(passphrase.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


# --- users ---

def cleanup_and_create_user(username: str) -> Tuple[bool, str]:
    """atomically clears zombie account (incomplete signup) and inserts a fresh user.
    uses BEGIN EXCLUSIVE to prevent toctou race on concurrent registrations."""
    user_id = str(uuid.uuid4())
    hashed = hash_passphrase(secrets.token_hex(32))
    conn = get_connection()
    try:
        conn.execute('BEGIN EXCLUSIVE')
        c = conn.cursor()
        row = c.execute(
            'SELECT id, profile_data FROM users WHERE username = ?', (username,)
        ).fetchone()
        if row:
            if row['profile_data'] is not None:
                conn.rollback()
                return False, 'Username already exists'
            # zombie account — no profile yet, safe to replace
            c.execute('DELETE FROM enrollment_samples WHERE user_id = ?', (row['id'],))
            c.execute('DELETE FROM users WHERE id = ?', (row['id'],))
        c.execute(
            'INSERT INTO users (id, username, passphrase_hash) VALUES (?, ?, ?)',
            (user_id, username, hashed)
        )
        conn.commit()
        return True, user_id
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, 'Username already exists'
    finally:
        conn.close()


def delete_user(user_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute('DELETE FROM enrollment_samples WHERE user_id = ?', (user_id,))
    c.execute('DELETE FROM users WHERE id = ?', (user_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_user_by_username(username: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_passphrase(username: str, passphrase: str) -> bool:
    user = get_user_by_username(username)
    if not user:
        # constant-time dummy check so response time doesn't reveal whether username exists
        bcrypt.checkpw(b'dummy', _DUMMY_HASH)
        return False
    try:
        return bcrypt.checkpw(passphrase.encode('utf-8'), user['passphrase_hash'].encode('utf-8'))
    except Exception:
        return False


def update_passphrase(user_id: str, new_passphrase: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        'UPDATE users SET passphrase_hash = ?, updated_at = ? WHERE id = ?',
        (hash_passphrase(new_passphrase), datetime.now(), user_id)
    )
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated


# --- profiles ---

def save_profile(user_id: str, profile_data: Optional[np.ndarray]) -> bool:
    """saves profile and clears any pending re-enrollment data."""
    conn = get_connection()
    c = conn.cursor()
    blob = profile_data.tobytes() if profile_data is not None else None
    c.execute(
        'UPDATE users SET profile_data = ?, pending_profile_data = NULL, updated_at = ? WHERE id = ?',
        (blob, datetime.now(), user_id)
    )
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def save_pending_profile(user_id: str, profile_data: np.ndarray) -> bool:
    """saves new profile to pending slot during re-enrollment — existing profile stays active."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        'UPDATE users SET pending_profile_data = ?, updated_at = ? WHERE id = ?',
        (profile_data.tobytes(), datetime.now(), user_id)
    )
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def activate_pending_profile(user_id: str) -> bool:
    """atomically swaps pending profile into active slot."""
    conn = get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        c = conn.cursor()
        row = c.execute(
            'SELECT pending_profile_data FROM users WHERE id = ?', (user_id,)
        ).fetchone()
        if not row or not row['pending_profile_data']:
            conn.rollback()
            return False
        c.execute(
            'UPDATE users SET profile_data = pending_profile_data, pending_profile_data = NULL, updated_at = ? WHERE id = ?',
            (datetime.now(), user_id)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_profile(user_id: str) -> Optional[np.ndarray]:
    user = get_user_by_id(user_id)
    if not user or not user['profile_data']:
        return None
    return np.frombuffer(user['profile_data'], dtype=np.float64)


def has_profile(user_id: str) -> bool:
    user = get_user_by_id(user_id)
    return user is not None and user['profile_data'] is not None


# --- enrollment samples ---

def save_enrollment_sample(user_id: str, sample_index: int, timings: list, expires_at: float) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO enrollment_samples (user_id, sample_index, timing_data, expires_at) VALUES (?, ?, ?, ?)',
        (user_id, sample_index, np.array(timings, dtype=np.float64).tobytes(), expires_at)
    )
    conn.commit()
    conn.close()
    return True


def get_enrollment_samples(user_id: str) -> list:
    """returns only non-expired samples ordered by index."""
    conn = get_connection()
    rows = conn.execute(
        'SELECT timing_data FROM enrollment_samples WHERE user_id = ? AND expires_at > ? ORDER BY sample_index',
        (user_id, time.time())
    ).fetchall()
    conn.close()
    return [np.frombuffer(row['timing_data'], dtype=np.float64) for row in rows]


def clear_enrollment_samples(user_id: str) -> bool:
    conn = get_connection()
    conn.execute('DELETE FROM enrollment_samples WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return True


def cleanup_expired_enrollment_samples():
    conn = get_connection()
    conn.execute('DELETE FROM enrollment_samples WHERE expires_at <= ?', (time.time(),))
    conn.commit()
    conn.close()


# --- auth codes (short-lived single-use exchange codes) ---

def create_auth_code(user_id: str, username: str, auth_method: str, expiry_seconds: int) -> str:
    code = secrets.token_urlsafe(32)
    conn = get_connection()
    conn.execute(
        'INSERT INTO auth_codes (code, user_id, username, auth_method, expires_at) VALUES (?, ?, ?, ?, ?)',
        (code, user_id, username, auth_method, time.time() + expiry_seconds)
    )
    conn.commit()
    conn.close()
    return code


def consume_auth_code(code: str) -> Optional[dict]:
    """atomically validates, deletes, and returns the code payload. returns none if invalid or expired."""
    conn = get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        c = conn.cursor()
        row = c.execute(
            'SELECT user_id, username, auth_method FROM auth_codes WHERE code = ? AND expires_at > ?',
            (code, time.time())
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        c.execute('DELETE FROM auth_codes WHERE code = ?', (code,))
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        return None
    finally:
        conn.close()


def cleanup_expired_auth_codes():
    conn = get_connection()
    conn.execute('DELETE FROM auth_codes WHERE expires_at <= ?', (time.time(),))
    conn.commit()
    conn.close()


# --- rate limits ---

def get_rate_limit(key: str) -> Tuple[int, float]:
    """returns (count, expires_at) for key, or (0, 0) if not found/expired."""
    conn = get_connection()
    row = conn.execute(
        'SELECT count, expires_at FROM rate_limits WHERE key = ? AND expires_at > ?',
        (key, time.time())
    ).fetchone()
    conn.close()
    return (row['count'], row['expires_at']) if row else (0, 0.0)


def increment_rate_limit(key: str, window_seconds: int) -> int:
    """increments count for key within window. creates entry on first call. returns new count."""
    conn = get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        c = conn.cursor()
        row = c.execute(
            'SELECT count, expires_at FROM rate_limits WHERE key = ?', (key,)
        ).fetchone()
        now = time.time()
        if row and row['expires_at'] > now:
            new_count = row['count'] + 1
            c.execute('UPDATE rate_limits SET count = ? WHERE key = ?', (new_count, key))
        else:
            new_count = 1
            c.execute(
                'INSERT OR REPLACE INTO rate_limits (key, count, expires_at) VALUES (?, 1, ?)',
                (key, now + window_seconds)
            )
        conn.commit()
        return new_count
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


def reset_rate_limit(key: str):
    conn = get_connection()
    conn.execute('DELETE FROM rate_limits WHERE key = ?', (key,))
    conn.commit()
    conn.close()


def cleanup_rate_limits():
    conn = get_connection()
    conn.execute('DELETE FROM rate_limits WHERE expires_at <= ?', (time.time(),))
    conn.commit()
    conn.close()


init_db()
