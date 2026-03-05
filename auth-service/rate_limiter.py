import time
from functools import wraps
from flask import request, jsonify
import config
import database


def get_client_ip() -> str:
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _is_over_limit(key: str) -> tuple[bool, int]:
    """returns (is_limited, retry_after_seconds) without modifying the counter."""
    count, expires_at = database.get_rate_limit(key)
    if count >= config.RATE_LIMIT_ATTEMPTS:
        return True, max(0, int(expires_at - time.time()))
    return False, 0


def rate_limit(endpoint_name: str = None):
    """ip-based rate limit decorator. increments on every request.
    intended for unauthenticated lookup endpoints (e.g. /api/user/check)."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ep = endpoint_name or request.endpoint
            key = f'ip:{get_client_ip()}:{ep}'
            limited, retry_after = _is_over_limit(key)
            if limited:
                return jsonify({
                    'error': 'Too many requests. Please try again later.',
                    'retry_after': retry_after
                }), 429
            database.increment_rate_limit(key, config.RATE_LIMIT_WINDOW_SECONDS)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def check_user_auth_limit(user_id: str) -> tuple[bool, int]:
    """check the unified auth attempt limit for a user.
    biometric and passphrase attempts share this same counter."""
    return _is_over_limit(f'auth:{user_id}')


def record_user_auth_attempt(user_id: str, success: bool):
    """record an auth attempt (biometric or passphrase) against the unified per-user counter.
    resets the counter on success so legitimate users aren't locked out."""
    key = f'auth:{user_id}'
    if success:
        database.reset_rate_limit(key)
    else:
        database.increment_rate_limit(key, config.RATE_LIMIT_WINDOW_SECONDS)
