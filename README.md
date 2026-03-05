# Tempo ID

Keystroke dynamics auth. It verifies identity by how you type, not just what you type.

## How it works

When you sign up, you type a fixed phrase 3 times. The time between each keystroke is recorded and averaged into a profile. When you log in, you type it once — your timing is compared against the profile using Pearson correlation and MSE. If it doesn't match after 3 attempts, you fall back to a passphrase.

## Architecture

Two services:

| Service | Role | Port |
|---|---|---|
| `auth-service/` | Identity provider — owns all auth logic and user data | `5001` |
| `dummy-app/` | Demo app — no auth of its own, delegates everything to the auth service | `3000` |

The dummy app redirects to the auth service for login/signup, then exchanges a short-lived code for a session token server-to-server. The session token never appears in a URL.

## Setup

```bash
pip install -r auth-service/requirements.txt
pip install -r dummy-app/requirements.txt
```

## Running

```powershell
# starts both services, streams logs, ctrl+c to stop
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Or manually in two terminals:

```bash
python auth-service/app.py   # http://localhost:5001
python dummy-app/server.py   # http://localhost:3000
```

Secret keys are auto-generated on first run and written to `.env` in each service directory.

## Usage

1. Go to [http://localhost:3000](http://localhost:3000)
2. Sign up — pick a username, set a passphrase (≥20 chars), type the phrase 3 times
3. Log in — type the phrase once, it either matches or it doesn't
4. After 3 failed attempts, fall back to the passphrase

## Smoke test

```bash
python verify_flow.py
```

## Stack

**Auth service:** Flask, NumPy, SciPy, bcrypt, PyJWT, python-dotenv
**Demo app:** Flask, Requests, python-dotenv

## Config

**`auth-service/.env`**

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | auto-generated | JWT signing key |
| `DEBUG` | `false` | Flask debug mode |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS whitelist |
| `RATE_LIMIT_ATTEMPTS` | `5` | Max failed auth attempts before lockout |
| `RATE_LIMIT_WINDOW` | `900` | Lockout window in seconds |
| `JWT_EXPIRATION_HOURS` | `1` | Session token lifetime |

**`dummy-app/.env`**

| Variable | Default | Description |
|---|---|---|
| `APP_SECRET_KEY` | auto-generated | Flask session cookie key |
