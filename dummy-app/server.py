import os
import secrets
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session
from dotenv import load_dotenv
import requests as http

load_dotenv()

app = Flask(__name__)

AUTH_URL = 'http://localhost:5001'
SELF_URL = 'http://localhost:3000'


def _get_or_create_secret_key() -> str:
    key = os.environ.get('APP_SECRET_KEY')
    if key:
        return key
    key = secrets.token_hex(32)
    env_path = Path(__file__).parent / '.env'
    try:
        with open(env_path, 'a') as f:
            f.write(f'APP_SECRET_KEY={key}\n')
    except OSError:
        pass
    return key


app.secret_key = _get_or_create_secret_key()


# --- csrf helpers ---

def _generate_csrf_token() -> str:
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(32)
    return session['_csrf']


def _validate_csrf() -> bool:
    token = session.get('_csrf')
    form_token = request.form.get('_csrf_token')
    return bool(token and form_token and token == form_token)


# make csrf_token() available in all templates
app.jinja_env.globals['csrf_token'] = _generate_csrf_token


# --- routes ---

@app.route('/')
def index():
    return render_template('index.html', user=session.get('user'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not _validate_csrf():
            return render_template('login.html', error='Invalid request. Please try again.')

        username = request.form.get('username', '').strip().lower()
        if not username:
            return render_template('login.html', error='Please enter a username')

        try:
            resp = http.get(f'{AUTH_URL}/api/user/{username}/check')
            data = resp.json()

            if not data.get('exists'):
                return render_template('login.html', error='User not found. Please sign up first.')

            token = data.get('auth_token')

            if not data.get('has_profile'):
                return redirect(f'{AUTH_URL}/enroll?token={token}&callback={SELF_URL}/auth-callback')

            return redirect(f'{AUTH_URL}/auth?token={token}&callback={SELF_URL}/auth-callback')

        except http.exceptions.RequestException:
            return render_template('login.html', error='Auth service unavailable. Please try again.')

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        if not _validate_csrf():
            return render_template('signup.html', error='Invalid request. Please try again.')

        username = request.form.get('username', '').strip().lower()
        if not username:
            return render_template('signup.html', error='Please enter a username')
        if len(username) < 3:
            return render_template('signup.html', error='Username must be at least 3 characters')

        try:
            resp = http.post(f'{AUTH_URL}/api/user/create', json={'username': username})
            data = resp.json()

            if resp.status_code == 409:
                return render_template('signup.html', error='Username already exists. Try logging in.')
            if not data.get('success'):
                return render_template('signup.html', error=data.get('error', 'Failed to create user'))

            token = data.get('flow_token')
            return redirect(f'{AUTH_URL}/setup-passphrase?token={token}&callback={SELF_URL}/auth-callback')

        except http.exceptions.RequestException:
            return render_template('signup.html', error='Auth service unavailable. Please try again.')

    return render_template('signup.html')


@app.route('/auth-callback')
def auth_callback():
    status = request.args.get('status')
    code = request.args.get('code')

    if status == 'success' and code:
        try:
            # exchange the short-lived code for a session token server-to-server
            # the full session token never appears in a url this way
            resp = http.post(f'{AUTH_URL}/api/exchange-code', json={'code': code})
            if not resp.ok:
                return redirect(url_for('login'))

            data = resp.json()
            session['user'] = {
                'user_id': data['user_id'],
                'username': data['username'],
                'auth_method': data['auth_method']
            }
            return redirect(url_for('dashboard'))

        except http.exceptions.RequestException:
            return redirect(url_for('login'))

    if status == 'cancelled':
        return redirect(url_for('index'))

    return redirect(url_for('login'))


@app.route('/dashboard')
def dashboard():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=user)


@app.route('/re-enroll', methods=['POST'])
def re_enroll():
    if not _validate_csrf():
        return redirect(url_for('dashboard'))

    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    # only allow re-enrollment when the user authenticated via fallback
    if user.get('auth_method') != 'fallback':
        return redirect(url_for('dashboard'))

    try:
        resp = http.post(f'{AUTH_URL}/api/user/{user["user_id"]}/enroll-token')
        data = resp.json()

        if not resp.ok or not data.get('flow_token'):
            return render_template('dashboard.html', user=user, error='Failed to start re-enrollment.')

        token = data.get('flow_token')
        return redirect(f'{AUTH_URL}/enroll?token={token}&callback={SELF_URL}/auth-callback')

    except http.exceptions.RequestException:
        return render_template('dashboard.html', user=user, error='Auth service unavailable.')


@app.route('/logout', methods=['POST'])
def logout():
    if not _validate_csrf():
        return redirect(url_for('index'))
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    print('SecureApp — http://localhost:3000')
    app.run(host='0.0.0.0', port=3000, debug=False)
