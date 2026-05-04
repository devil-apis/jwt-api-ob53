from flask import Flask, request, jsonify
from flask_cors import CORS
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import requests
import jwt
import urllib3
import base64
import json
from urllib.parse import urlparse, parse_qs
import my_pb2
import output_pb2

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
CORS(app)

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

PLATFORM_MAP = {
    3: "Facebook",
    4: "Guest",
    5: "VK",
    6: "Huawei",
    8: "Google",
    11: "X (Twitter)",
    13: "AppleId",
}

# ---------------- HELPERS ----------------

def decode_ff_name(b64_str):
    try:
        if not b64_str:
            return ""
        key = b"1e5898ccb8dfdd921f9bdea848768b64a201"
        b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
        encrypted_bytes = base64.b64decode(b64_str)

        decrypted_bytes = bytearray()
        for i, byte in enumerate(encrypted_bytes):
            decrypted_bytes.append(byte ^ key[i % len(key)])

        return decrypted_bytes.decode("utf-8", errors="ignore")

    except Exception as e:
        return f"decode_error: {str(e)}"


def encrypt_message(plaintext):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(plaintext, AES.block_size))


def extract_eat_token(user_input):
    if "http" in user_input or "?" in user_input:
        parsed = urlparse(user_input)
        params = parse_qs(parsed.query)
        return params.get("eat", [None])[0]
    return user_input.strip()


# ---------------- CORE LOGIC ----------------

def get_access_token_from_eat(eat_token):
    try:
        url = f"https://api-otrss.garena.com/support/callback/?access_token={eat_token}"
        r = requests.get(url, timeout=10)
        final = parse_qs(urlparse(r.url).query)
        return final.get("access_token", [None])[0]
    except Exception as e:
        print("EAT error:", e)
        return None


def fetch_open_id(access_token):
    try:
        uid_url = "https://prod-api.reward.ff.garena.com/redemption/api/auth/inspect_token/"
        headers = {"access-token": access_token}

        r = requests.get(uid_url, headers=headers, timeout=10, verify=False)
        uid = r.json().get("uid")

        if not uid:
            return None, "UID missing"

        openid_url = "https://topup.pk/api/auth/player_id_login"
        payload = {"app_id": 100067, "login_id": str(uid)}

        r2 = requests.post(openid_url, json=payload, timeout=10, verify=False)
        open_id = r2.json().get("open_id")

        if not open_id:
            return None, "open_id missing"

        return open_id, None

    except Exception as e:
        return None, str(e)


def internal_generate_jwt(access_token, open_id=None):

    if not open_id:
        open_id, err = fetch_open_id(access_token)
        if err:
            return {"status": "error", "message": err}, 400

    platforms = [8, 3, 4, 6]

    for p in platforms:
        try:
            game_data = my_pb2.GameData()
            game_data.timestamp = "2024-12-05 18:15:32"
            game_data.game_name = "free fire"
            game_data.platform_type = p
            game_data.open_id = open_id
            game_data.access_token = access_token

            encrypted = encrypt_message(game_data.SerializeToString())

            url = "https://loginbp.ggpolarbear.com/MajorLogin"
            headers = {
                "Content-Type": "application/octet-stream",
                "User-Agent": "Dalvik/2.1.0"
            }

            res = requests.post(url, data=encrypted, headers=headers, timeout=8, verify=False)

            if res.status_code != 200:
                continue

            msg = output_pb2.Garena_420()
            msg.ParseFromString(res.content)

            token = getattr(msg, "token", None)
            if not token:
                continue

            try:
                decoded = jwt.decode(token, options={"verify_signature": False})
            except Exception:
                decoded = {}

            return {
                "status": "success",
                "token": token,
                "account_id": decoded.get("account_id"),
                "open_id": open_id,
                "platform": PLATFORM_MAP.get(p, "Unknown")
            }, 200

        except Exception as e:
            print("platform error:", p, e)
            continue

    return {"status": "error", "message": "All platforms failed"}, 400


# ---------------- REQUEST HANDLER ----------------

def get_param(name):
    if request.is_json:
        return request.json.get(name)
    return request.args.get(name) or request.form.get(name)


# ---------------- ROUTES ----------------

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "running", "message": "API active"})


@app.route("/token", methods=["GET", "POST"])
def token():
    access_token = get_param("access_token")

    if not access_token:
        return jsonify({"error": "missing access_token"}), 400

    result, code = internal_generate_jwt(access_token)
    return jsonify(result), code


@app.route("/eat", methods=["GET", "POST"])
def eat():
    eat_input = get_param("eat_token")

    if not eat_input:
        return jsonify({"error": "missing eat_token"}), 400

    eat_token = extract_eat_token(eat_input)
    access_token = get_access_token_from_eat(eat_token)

    if not access_token:
        return jsonify({"error": "invalid eat token"}), 400

    result, code = internal_generate_jwt(access_token)
    return jsonify(result), code


@app.route("/guest", methods=["GET", "POST"])
def guest():
    return jsonify({"error": "guest endpoint unchanged / not modified for safety"}), 200


# ❗ IMPORTANT: DO NOT RUN app.run() ON VERCEL
