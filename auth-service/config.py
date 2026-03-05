import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_or_create_secret_key() -> str:
    key = os.environ.get('SECRET_KEY')
    if key:
        return key

    key = secrets.token_hex(32)
    env_path = Path(__file__).parent / '.env'
    try:
        with open(env_path, 'a') as f:
            f.write(f'SECRET_KEY={key}\n')
    except OSError:
        pass
    return key


SECRET_KEY = _get_or_create_secret_key()

# default false — never expose auth stats in production
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
ALLOWED_CALLBACKS = [
    'http://localhost:3000/auth-callback',
    '/auth-callback',
    '/'
]

RATE_LIMIT_ATTEMPTS = int(os.environ.get('RATE_LIMIT_ATTEMPTS', '5'))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW', '900'))
JWT_EXPIRATION_HOURS = int(os.environ.get('JWT_EXPIRATION_HOURS', '1'))

# short-lived single-use code exchanged for session token (oauth-style)
AUTH_CODE_EXPIRY_SECONDS = 60

# enrollment samples expire after this window
ENROLL_EXPIRY_MINUTES = 30

MIN_PASSPHRASE_LENGTH = 20
