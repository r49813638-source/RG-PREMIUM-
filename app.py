from flask import Flask, request, jsonify, render_template
import requests, json, time, base64, os, random

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

BASE_URL = "https://all-apii.onrender.com"
INFO_URL = "https://info-api-vyre.onrender.com"

ACCOUNTS_FILE = "accounts.json"
TOKEN_FILE = "token.json"

# ---------------- SESSION (FAST + RETRY) ----------------

def create_session():
    s = requests.Session()

    retries = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )

    adapter = HTTPAdapter(
        max_retries=retries,
        pool_connections=100,
        pool_maxsize=100
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
            timeout=80
        )
        j = r.json()
        if j.get("status") == "success":
            tokens = load_tokens()
            tokens[str(uid)] = j["token"]
            save_tokens(tokens)
            return j["token"]
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] Token for {uid}")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
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

# ✅ NEW ROUTE (ADD THIS)
@app.route('/ping')
def ping():
    try:
        requests.get(BASE_URL, timeout=10)
        requests.get(INFO_URL, timeout=10)
    except:
        pass

    return jsonify({"status": "running"})

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

        res = None

        for attempt in range(3):
            try:
                response = session.get(
                    BASE_URL + "/add_friend",
                    params={"token": token, "player_id": target},
                    timeout=80
                )
                res = response.json()
                break
            except requests.exceptions.Timeout:
                print(f"[RETRY] Timeout retry {attempt+1}")
                time.sleep(2)
            except Exception as e:
                print(f"[ERROR] {e}")
                break

        if not res:
            failed += 1
            logs.append({"uid": uid, "status": "timeout_fail"})
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

        time.sleep(0.5)

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
    data = request.json or {}
    uid = data.get("uid")
    if not uid:
        return jsonify({"status": "failed", "error": "UID missing"})

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = session.get(
            INFO_URL + "/get",
            params={"uid": uid, "region": "IND"},
            headers=headers,
            timeout=80
        )
        j = r.json()
        print("DEBUG INFO RESPONSE:", j)
        return jsonify(j)
    except requests.exceptions.Timeout:
        return jsonify({"status": "failed", "error": "Request timed out"})
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "failed", "error": str(e)})
    except Exception as e:
        return jsonify({"status": "failed", "error": f"Unknown error: {e}"})

# === Startup ===
import sys

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"[🚀] Starting {__name__.upper()} on port {port} ...")
    app.run(host='0.0.0.0', port=port, debug=False)
