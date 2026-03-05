import requests
import json
import time
import random
import numpy as np

AUTH_URL = "http://localhost:5001"
KEYPHRASE = "the quick brown fox jumped over the lazy dog"


def generate_timings(phrase, base_wpm=80.0, jitter=0.05):
    """generate synthetic keystroke intervals for testing."""
    base_interval = 60000 / (base_wpm * 5)

    timings = []
    for _ in range(len(phrase) - 1):
        timings.append(int(base_interval + random.uniform(-10, 10)))

    return [int(t * random.uniform(1.0 - jitter, 1.0 + jitter)) for t in timings]


def verify_signup_flow():
    print("=== signup flow verification ===")

    username = f"verify_{int(time.time())}"
    print(f"1. creating user '{username}'...")

    resp = requests.post(f"{AUTH_URL}/api/user/create", json={'username': username})
    if resp.status_code != 200:
        print(f"   FAIL: create user returned {resp.status_code}")
        print(resp.text)
        return

    data = resp.json()
    user_id = data['user_id']
    print(f"   ok. id: {user_id}")

    # re-register same user (zombie cleanup test)
    print("2. re-registering same user (zombie test)...")
    resp = requests.post(f"{AUTH_URL}/api/user/create", json={'username': username})
    if resp.status_code == 200:
        data = resp.json()
        user_id = data['user_id']
        print(f"   ok. new id: {user_id}")
    else:
        print(f"   FAIL: returned {resp.status_code}, expected 200")

    # set passphrase
    print("3. setting passphrase...")
    resp = requests.post(f"{AUTH_URL}/api/user/set-passphrase", json={
        'user_id': user_id,
        'passphrase': 'correct horse battery staple verify'
    })
    if resp.status_code != 200:
        print(f"   FAIL: returned {resp.status_code}")
        print(resp.text)
        return
    print("   ok.")

    # enroll 3 samples
    print("4. enrolling (3 samples)...")
    base_pattern = generate_timings(KEYPHRASE, base_wpm=90, jitter=0.0)

    for i in range(3):
        sample = [int(t * random.uniform(0.95, 1.05)) for t in base_pattern]
        resp = requests.post(f"{AUTH_URL}/api/enroll", json={
            'user_id': user_id,
            'timings': sample
        })
        if resp.status_code != 200:
            print(f"   FAIL: sample {i+1} returned {resp.status_code}")
            return
        print(f"   sample {i+1} ok.")
    print("   enrollment complete.")

    # authenticate
    print("5. authenticating...")
    auth_sample = [int(t * random.uniform(0.95, 1.05)) for t in base_pattern]
    resp = requests.post(f"{AUTH_URL}/api/authenticate", json={
        'user_id': user_id,
        'timings': auth_sample
    })
    if resp.status_code != 200:
        print(f"   FAIL: returned {resp.status_code}")
        return

    result = resp.json()
    if result.get('authenticated'):
        print("   ok: authenticated!")
    else:
        print("   FAIL: rejected.")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    verify_signup_flow()
