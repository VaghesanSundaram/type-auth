from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import time
import numpy as np

import config
import database
from keystroke_validator import validate_timings, compute_mean_profile, get_expected_timing_length, KEYPHRASE
from rate_limiter import rate_limit, check_user_auth_limit, record_user_auth_attempt
from auth_tokens import (
    create_flow_token, verify_flow_token, verify_flow_token_for_user,
    create_action_token, verify_action_token, verify_action_token_for_user,
    create_session_token
)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
CORS(app, origins=config.ALLOWED_ORIGINS, supports_credentials=True)


def validate_callback(callback: str) -> bool:
    if not callback:
        return False
    if callback.startswith('/'):
        return True
    return callback in config.ALLOWED_CALLBACKS


def get_safe_callback(callback: str) -> str:
    return callback if validate_callback(callback) else '/'


def validate_timings_input(timings) -> tuple[bool, str]:
    """validate timing array: correct length, all values finite and within plausible range."""
    expected = get_expected_timing_length()
    if not isinstance(timings, list):
        return False, 'timings must be an array'
    if len(timings) != expected:
        return False, f'expected {expected} timing intervals, got {len(timings)}'
    if not all(isinstance(t, (int, float)) and 0 < t < 5.0 for t in timings):
        return False, 'timing values must be positive numbers less than 5 seconds'
    return True, ''


# --- api ---

@app.route('/api/user/create', methods=['POST'])
def api_create_user():
    data = request.get_json()

    if not data or 'username' not in data:
        return jsonify({'error': 'username is required'}), 400

    username = data['username'].strip().lower()
    if len(username) < 3:
        return jsonify({'error': 'username must be at least 3 characters'}), 400

    # transactional zombie cleanup + insert (prevents toctou race)
    success, result = database.cleanup_and_create_user(username)

    if success:
        return jsonify({
            'success': True,
            'user_id': result,
            'username': username,
            'flow_token': create_flow_token(result)
        })
    return jsonify({'error': result}), 409


@app.route('/api/user/set-passphrase', methods=['POST'])
def api_set_passphrase():
    data = request.get_json()

    try:
        if not data or 'token' not in data or 'passphrase' not in data:
            return jsonify({'error': 'token and passphrase are required'}), 400

        # verify the flow token to identify the user — no bare user_id accepted
        user_id = verify_flow_token(data['token'])
        if not user_id:
            return jsonify({'error': 'invalid or expired token'}), 401

        passphrase = data['passphrase']
        if len(passphrase) < config.MIN_PASSPHRASE_LENGTH:
            return jsonify({
                'error': f'passphrase must be at least {config.MIN_PASSPHRASE_LENGTH} characters'
            }), 400

        user = database.get_user_by_id(user_id)
        if not user:
            return jsonify({'error': 'user not found'}), 404

        if database.update_passphrase(user_id, passphrase):
            return jsonify({'success': True})
        return jsonify({'error': 'failed to set passphrase'}), 500

    except Exception as e:
        print(f'set-passphrase error: {e}')
        return jsonify({'error': 'internal server error'}), 500


@app.route('/api/user/<username>/check', methods=['GET'])
@rate_limit('user-check')
def api_check_user(username: str):
    user = database.get_user_by_username(username.lower())

    if not user:
        return jsonify({'exists': False, 'has_profile': False})

    return jsonify({
        'exists': True,
        'has_profile': database.has_profile(user['id']),
        'user_id': user['id'],
        'auth_token': create_action_token(user['id'], 'auth', expires_minutes=5)
    })


@app.route('/api/user/<user_id>/enroll-token', methods=['POST'])
def api_enroll_token(user_id: str):
    user = database.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'user not found'}), 404

    # clear any partial samples from a previous session,
    # but keep the existing profile active until new enrollment completes
    database.clear_enrollment_samples(user_id)
    database.cleanup_expired_enrollment_samples()

    return jsonify({'flow_token': create_flow_token(user_id)})


@app.route('/api/enroll', methods=['POST'])
def api_enroll():
    data = request.get_json()

    if not data or 'token' not in data or 'user_id' not in data or 'timings' not in data:
        return jsonify({'error': 'token, user_id, and timings are required'}), 400

    user_id = data['user_id']

    # verify the flow token is valid and belongs to this user
    if not verify_flow_token_for_user(data['token'], user_id):
        return jsonify({'error': 'invalid or expired token'}), 401

    timings = data['timings']
    valid, err = validate_timings_input(timings)
    if not valid:
        return jsonify({'error': err}), 400

    # ignore any expired samples so back-button / abandoned sessions start fresh
    existing = database.get_enrollment_samples(user_id)
    sample_index = len(existing)

    expires_at = time.time() + config.ENROLL_EXPIRY_MINUTES * 60
    database.save_enrollment_sample(user_id, sample_index, timings, expires_at)
    count = sample_index + 1

    if count >= 3:
        all_samples = database.get_enrollment_samples(user_id)
        new_profile = compute_mean_profile(all_samples)
        database.clear_enrollment_samples(user_id)

        user = database.get_user_by_id(user_id)
        if database.has_profile(user_id):
            # re-enrollment: swap new profile in atomically, old stays active until this point
            database.save_pending_profile(user_id, new_profile)
            database.activate_pending_profile(user_id)
        else:
            # initial enrollment
            database.save_profile(user_id, new_profile)

        # issue an auth code so the callback never carries a session token in the url
        code = database.create_auth_code(
            user_id, user['username'], 'biometric', config.AUTH_CODE_EXPIRY_SECONDS
        )
        return jsonify({'success': True, 'complete': True, 'auth_code': code})

    return jsonify({
        'success': True,
        'complete': False,
        'samples_collected': count,
        'samples_needed': 3
    })


@app.route('/api/authenticate', methods=['POST'])
def api_authenticate():
    data = request.get_json()

    if not data or 'token' not in data or 'user_id' not in data or 'timings' not in data:
        return jsonify({'error': 'token, user_id, and timings are required'}), 400

    user_id = data['user_id']

    # verify the action token is valid and bound to this specific user
    if not verify_action_token_for_user(data['token'], 'auth', user_id):
        return jsonify({'error': 'invalid or expired token'}), 401

    # unified per-user rate limit (shared with passphrase-fallback)
    is_limited, retry_after = check_user_auth_limit(user_id)
    if is_limited:
        return jsonify({
            'error': 'too many failed attempts. please try again later.',
            'retry_after': retry_after
        }), 429

    timings = data['timings']
    valid, err = validate_timings_input(timings)
    if not valid:
        return jsonify({'error': err}), 400

    profile = database.get_profile(user_id)
    if profile is None:
        return jsonify({'error': 'no profile found for user'}), 404

    success, _, _ = validate_timings(profile, np.array(timings))
    record_user_auth_attempt(user_id, success)

    if success:
        user = database.get_user_by_id(user_id)
        code = database.create_auth_code(
            user_id, user['username'], 'biometric', config.AUTH_CODE_EXPIRY_SECONDS
        )
        return jsonify({'authenticated': True, 'auth_code': code})

    return jsonify({'authenticated': False})


@app.route('/api/passphrase-fallback', methods=['POST'])
def api_passphrase_fallback():
    data = request.get_json()

    if not data or 'username' not in data or 'passphrase' not in data:
        return jsonify({'error': 'username and passphrase are required'}), 400

    username = data['username'].strip().lower()

    # look up user first so we can apply the per-user rate limit
    user = database.get_user_by_username(username)
    if user:
        is_limited, retry_after = check_user_auth_limit(user['id'])
        if is_limited:
            return jsonify({
                'error': 'too many failed attempts. please try again later.',
                'retry_after': retry_after
            }), 429

    # verify_passphrase does a constant-time dummy check when user doesn't exist
    success = database.verify_passphrase(username, data['passphrase'])

    if user:
        record_user_auth_attempt(user['id'], success)

    if success and user:
        code = database.create_auth_code(
            user['id'], username, 'fallback', config.AUTH_CODE_EXPIRY_SECONDS
        )
        return jsonify({'authenticated': True, 'auth_code': code})

    return jsonify({'authenticated': False}), 401


@app.route('/api/exchange-code', methods=['POST'])
def api_exchange_code():
    """exchange a short-lived auth code for a session token.
    called server-to-server by the service provider — session token never touches a url."""
    data = request.get_json()

    if not data or 'code' not in data:
        return jsonify({'error': 'code is required'}), 400

    payload = database.consume_auth_code(data['code'])
    if not payload:
        return jsonify({'error': 'invalid or expired code'}), 401

    session_token = create_session_token(
        payload['user_id'], payload['username'], payload['auth_method']
    )
    return jsonify({
        'session_token': session_token,
        'user_id': payload['user_id'],
        'username': payload['username'],
        'auth_method': payload['auth_method']
    })


# --- pages ---

@app.route('/setup-passphrase')
def setup_passphrase_page():
    token = request.args.get('token')
    callback = get_safe_callback(request.args.get('callback', '/'))

    user_id = verify_flow_token(token) if token else None
    if not user_id:
        return 'invalid or expired token', 400

    user = database.get_user_by_id(user_id)
    if not user:
        return 'user not found', 404

    return render_template('setup_passphrase.html',
        user_id=user_id, username=user['username'], callback=callback, token=token)


@app.route('/enroll')
def enroll_page():
    token = request.args.get('token')
    callback = get_safe_callback(request.args.get('callback', '/'))

    # accept flow token (signup) or auth token (login with no profile yet)
    if token:
        user_id = verify_flow_token(token) or verify_action_token(token, 'auth')
    else:
        user_id = None

    if not user_id:
        return 'invalid or expired token', 400

    user = database.get_user_by_id(user_id)
    return render_template('enroll.html',
        user_id=user_id,
        username=user['username'] if user else 'user',
        callback=callback,
        keyphrase=KEYPHRASE,
        token=token)


@app.route('/auth')
def auth_page():
    token = request.args.get('token')
    callback = get_safe_callback(request.args.get('callback', '/'))

    user_id = verify_action_token(token, 'auth') if token else None
    if not user_id:
        return 'invalid or expired token', 400

    user = database.get_user_by_id(user_id)
    username = user['username'] if user else 'user'

    return render_template('auth.html',
        user_id=user_id, username=username, callback=callback, keyphrase=KEYPHRASE, token=token)


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'tempo-id-auth'})


if __name__ == '__main__':
    print(f'Tempo ID Auth Service — http://localhost:5001 (debug={config.DEBUG})')
    app.run(host='0.0.0.0', port=5001, debug=config.DEBUG)
