from flask import Flask, request, jsonify, render_template
import requests, json, time, base64, os, random

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

BASE_URL = "https://all-aapi-production.up.railway.app"
INFO_URL = "https://info-api-vyre.onrender.com"

ACCOUNTS_FILE = "accounts.json"
TOKEN_FILE = "token.json"

# ---------------- SESSION (FAST + RETRY) ----------------

def create_session():
    s = requests.Session()

    retries = Retry(
        total=2,                 # fast retry
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )

    adapter = HTTPAdapter(
        max_retries=retries,
        pool_connections=50,
        pool_maxsize=50
    )

    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

session = create_session()

# ---------------- TOKEN UTILS ----------------

def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return {}
    try:
        return json.load(open(TOKEN_FILE))
    except:
        return {}

def save_tokens(data):
    json.dump(data, open(TOKEN_FILE, "w"), indent=2)

def token_expired(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return time.time() > data.get("exp", 0)
    except:
        return True

def request_token(uid, password):
    try:
        r = session.get(
            BASE_URL + "/token",
            params={"uid": uid, "password": password},
            timeout=6
        )
        j = r.json()
        if j.get("status") == "success":
            tokens = load_tokens()
            tokens[str(uid)] = j["token"]
            save_tokens(tokens)
            return j["token"]
    except requests.exceptions.RequestException:
        return None
    return None

def get_token(uid, password):
    uid = str(uid)
    tokens = load_tokens()
    if uid in tokens and not token_expired(tokens[uid]):
        return tokens[uid]
    return request_token(uid, password)

# ---------------- PAGES ----------------

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/spam")
def spam_page():
    return render_template("spam.html")

@app.route("/info")
def info_page():
    return render_template("info.html")

# ---------------- SPAM API ----------------

@app.route("/api/spam_add", methods=["POST"])
def spam_add():
    data = request.json or {}
    target = data.get("target")
    limit = int(data.get("limit", 0))

    if not target or limit <= 0:
        return jsonify({"status": "failed", "error": "Invalid input"})

    if not os.path.exists(ACCOUNTS_FILE):
        return jsonify({"status": "failed", "error": "accounts.json missing"})

    accounts = json.load(open(ACCOUNTS_FILE))
    random.shuffle(accounts)

    success = failed = duplicate = used = 0
    logs = []

    for acc in accounts:
        if used >= limit:
            break

        uid = acc.get("uid")
        password = acc.get("password")

        token = get_token(uid, password)
        if not token:
            failed += 1
            logs.append({"uid": uid, "status": "token_failed"})
            used += 1
            continue

        try:
            res = session.get(
                BASE_URL + "/add_friend",
                params={"token": token, "player_id": target},
                timeout=8
            ).json()
        except requests.exceptions.RequestException:
            failed += 1
            logs.append({"uid": uid, "status": "timeout"})
            used += 1
            continue

        status = res.get("status", "failed")

        if status == "success":
            success += 1
        elif status == "duplicate":
            duplicate += 1
        else:
            failed += 1

        logs.append({"uid": uid, "status": status})
        used += 1

        time.sleep(0.2)  # fast but safe

    return jsonify({
        "success": success,
        "failed": failed,
        "duplicate": duplicate,
        "total": used,
        "logs": logs
    })

# ---------------- INFO API ----------------

@app.route("/api/info", methods=["POST"])
def info():
    uid = request.json.get("uid")
    if not uid:
        return jsonify({"status": "failed", "error": "UID missing"})

    try:
        r = session.get(
            INFO_URL + "/get",
            params={"uid": uid, "region": "IND"},
            timeout=6
        )
        return jsonify(r.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "failed", "error": str(e)})

# === Startup ===
import sys

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"[🚀] Starting {__name__.upper()} on port {port} ...")
    app.run(host='0.0.0.0', port=port, debug=False)
