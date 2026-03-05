import jwt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session_token(user_id: str, username: str, auth_method: str = 'biometric') -> str:
    now = _now()
    payload = {
        'sub': user_id,
        'username': username,
        'auth_method': auth_method,
        'iat': now,
        'exp': now + timedelta(hours=config.JWT_EXPIRATION_HOURS),
        'type': 'session'
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm='HS256')


def verify_session_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') != 'session':
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def create_flow_token(user_id: str, expires_minutes: int = 15) -> str:
    """multi-use token covering the full signup/enrollment flow."""
    return create_action_token(user_id, 'flow', expires_minutes)


def verify_flow_token(token: str) -> Optional[str]:
    """verify flow token and return user_id without consuming it."""
    return _verify_action_token(token, 'flow')


def verify_flow_token_for_user(token: str, expected_user_id: str) -> bool:
    """verify flow token and assert it belongs to the expected user."""
    user_id = verify_flow_token(token)
    return user_id is not None and user_id == expected_user_id


def create_action_token(user_id: str, action: str, expires_minutes: int = 5) -> str:
    now = _now()
    payload = {
        'sub': user_id,
        'action': action,
        'jti': secrets.token_urlsafe(16),
        'iat': now,
        'exp': now + timedelta(minutes=expires_minutes),
        'type': 'action'
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm='HS256')


def _verify_action_token(token: str, expected_action: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') != 'action':
            return None
        if payload.get('action') != expected_action:
            return None
        return payload.get('sub')
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def verify_action_token(token: str, expected_action: str) -> Optional[str]:
    return _verify_action_token(token, expected_action)


def verify_action_token_for_user(token: str, expected_action: str, expected_user_id: str) -> bool:
    """verify token signature, expiry, action type, and user_id binding.
    prevents a valid token issued for user a being used to act on user b."""
    user_id = _verify_action_token(token, expected_action)
    return user_id is not None and user_id == expected_user_id
